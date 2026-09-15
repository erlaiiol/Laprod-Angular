"""
Tests unitaires — utils/apple_signin.py

Couvre la cryptographie réelle (signature/vérification JWT), pas seulement des
mocks : un identity token est signé avec une clé RSA de test, vérifié contre un
JWKS de test (le vrai code de production, `_fetch_jwks_dict` mocké pour éviter
l'appel réseau vers appleid.apple.com).
"""
import time
import pytest
from authlib.jose import jwt as jose_jwt, JsonWebKey
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from utils import apple_signin


KID = 'test-kid-1'
AUDIENCE = 'net.laprod.app.web'


@pytest.fixture(scope='module')
def rsa_keypair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return priv_pem, pub_pem


@pytest.fixture()
def fake_jwks(rsa_keypair, mocker):
    _, pub_pem = rsa_keypair
    jwk = JsonWebKey.import_key(pub_pem, {'kid': KID, 'alg': 'RS256', 'use': 'sig'})
    mocker.patch.object(apple_signin, '_fetch_jwks_dict', return_value={'keys': [jwk.as_dict()]})


def _sign_identity_token(priv_pem, **claim_overrides):
    now = int(time.time())
    claims = {
        'iss': apple_signin._ISSUER,
        'aud': AUDIENCE,
        'sub': 'apple-user-sub-123',
        'iat': now,
        'exp': now + 3600,
        'email': 'user@privaterelay.appleid.com',
        'email_verified': 'true',
    }
    claims.update(claim_overrides)
    return jose_jwt.encode({'alg': 'RS256', 'kid': KID}, claims, priv_pem).decode('ascii')


class TestVerifyIdentityToken:

    def test_valid_token_returns_claims(self, rsa_keypair, fake_jwks):
        priv_pem, _ = rsa_keypair
        token = _sign_identity_token(priv_pem)

        claims = apple_signin.verify_identity_token(token, AUDIENCE)

        assert claims['sub'] == 'apple-user-sub-123'
        assert claims['email'] == 'user@privaterelay.appleid.com'

    def test_wrong_audience_rejected(self, rsa_keypair, fake_jwks):
        priv_pem, _ = rsa_keypair
        token = _sign_identity_token(priv_pem, aud='some.other.client')

        with pytest.raises(apple_signin.AppleSignInError):
            apple_signin.verify_identity_token(token, AUDIENCE)

    def test_wrong_issuer_rejected(self, rsa_keypair, fake_jwks):
        priv_pem, _ = rsa_keypair
        token = _sign_identity_token(priv_pem, iss='https://not-apple.example.com')

        with pytest.raises(apple_signin.AppleSignInError):
            apple_signin.verify_identity_token(token, AUDIENCE)

    def test_expired_token_rejected(self, rsa_keypair, fake_jwks):
        priv_pem, _ = rsa_keypair
        now = int(time.time())
        token = _sign_identity_token(priv_pem, iat=now - 7200, exp=now - 3600)

        with pytest.raises(apple_signin.AppleSignInError):
            apple_signin.verify_identity_token(token, AUDIENCE)

    def test_tampered_signature_rejected(self, rsa_keypair, fake_jwks):
        priv_pem, _ = rsa_keypair
        token = _sign_identity_token(priv_pem)
        tampered = token[:-4] + ('A' if token[-4] != 'A' else 'B') + token[-3:]

        with pytest.raises(apple_signin.AppleSignInError):
            apple_signin.verify_identity_token(tampered, AUDIENCE)

    def test_signed_by_unknown_key_rejected(self, fake_jwks):
        """Un token signé par une clé qui n'est PAS dans le JWKS Apple (attaquant
        avec sa propre paire de clés) doit être refusé même si `kid` correspond
        par coïncidence — la signature ne matchera jamais la clé publique
        enregistrée."""
        other_priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other_priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        token = _sign_identity_token(other_pem)

        with pytest.raises(apple_signin.AppleSignInError):
            apple_signin.verify_identity_token(token, AUDIENCE)


class TestClientSecretAndTokenExchange(object):

    def test_client_secret_is_valid_es256_jwt(self, app):
        from cryptography.hazmat.primitives.asymmetric import ec
        priv = ec.generate_private_key(ec.SECP256R1())
        priv_pem = priv.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        pub_pem = priv.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        with app.app_context():
            app.config['APPLE_PRIVATE_KEY'] = priv_pem
            app.config['APPLE_KEY_ID'] = 'key-id-1'
            app.config['APPLE_TEAM_ID'] = 'team-id-1'
            secret = apple_signin._client_secret(AUDIENCE)

        claims = jose_jwt.decode(secret, pub_pem)
        assert claims['iss'] == 'team-id-1'
        assert claims['sub'] == AUDIENCE
        assert claims['aud'] == apple_signin._ISSUER

    def test_exchange_authorization_code_raises_on_apple_error(self, app, mocker):
        resp = mocker.MagicMock(status_code=400, content=b'{"error":"invalid_grant"}')
        resp.json.return_value = {'error': 'invalid_grant'}
        mocker.patch('utils.apple_signin.requests.post', return_value=resp)
        mocker.patch.object(apple_signin, '_client_secret', return_value='fake-secret')

        with app.app_context():
            with pytest.raises(apple_signin.AppleSignInError):
                apple_signin.exchange_authorization_code('bad-code', AUDIENCE)

    def test_revoke_refresh_token_is_best_effort(self, app, mocker):
        """Une révocation qui échoue ne doit jamais lever d'exception — c'est le
        contrat qui protège la suppression de compte (cf. routes/main_api.py)."""
        mocker.patch('utils.apple_signin.requests.post', side_effect=Exception('network down'))
        mocker.patch.object(apple_signin, '_client_secret', return_value='fake-secret')

        with app.app_context():
            result = apple_signin.revoke_refresh_token('rt', AUDIENCE)

        assert result is False
