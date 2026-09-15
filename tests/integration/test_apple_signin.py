"""
Tests d'intégration — Sign in with Apple (web + natif).

Miroir de tests/integration/test_google_oauth_mobile.py pour la partie
redirection web/mobile, complété par le flow natif (POST direct, pas de
redirection) propre à Apple. `apple_signin.verify_identity_token` /
`exchange_authorization_code` / `revoke_refresh_token` sont mockées : la
cryptographie JWKS/JWT est déjà couverte par tests/unit/test_apple_signin.py.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from utils import apple_signin
from routes import auth_api


def _claims(sub=None, email=None, email_verified=True):
    return {
        'iss': 'https://appleid.apple.com',
        'sub': sub or f'apple-sub-{uuid.uuid4().hex[:12]}',
        'email': email or f'apple_{uuid.uuid4().hex[:8]}@privaterelay.appleid.com',
        'email_verified': 'true' if email_verified else 'false',
    }


@pytest.fixture()
def apple_user(db, bound_factories):
    """Utilisateur déjà lié à Apple (CAS 1 du helper)."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(email_verified=True, user_type_selected=True)
    u.apple_sub = f'apple-sub-{uuid.uuid4().hex[:12]}'
    u.oauth_provider = 'apple'
    db.session.commit()
    return u


class TestAppleLoginStateTagging:

    def test_web_login_state_carries_web_platform(self, client, app):
        resp = client.get('/api/auth/apple/login')
        assert resp.status_code == 302
        assert 'appleid.apple.com/auth/authorize' in resp.location

        import re
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(resp.location).query)
        state = qs['state'][0]
        with app.app_context():
            payload = auth_api._verify_apple_state(state)
        assert payload == {'platform': 'web'}

    def test_mobile_login_state_carries_mobile_platform(self, client, app):
        resp = client.get('/api/auth/apple/login?platform=mobile')
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(resp.location).query)
        state = qs['state'][0]
        with app.app_context():
            payload = auth_api._verify_apple_state(state)
        assert payload == {'platform': 'mobile'}


class TestAppleCallbackRedirectDestination:

    def test_mobile_state_redirects_to_custom_scheme(self, client, db, app, apple_user, mocker):
        mocker.patch.object(apple_signin, 'verify_identity_token',
                             return_value=_claims(sub=apple_user.apple_sub, email=apple_user.email))
        mocker.patch.object(apple_signin, 'exchange_authorization_code', return_value={})

        with app.app_context():
            state = auth_api._sign_apple_state({'platform': 'mobile'})

        resp = client.post('/api/auth/apple/callback', data={
            'state': state, 'code': 'c', 'id_token': 't',
        })

        assert resp.status_code == 302
        assert resp.location.startswith('net.laprod.app://oauth-callback?code=')

    def test_web_state_redirects_to_frontend_url(self, client, db, app, apple_user, mocker):
        mocker.patch.object(apple_signin, 'verify_identity_token',
                             return_value=_claims(sub=apple_user.apple_sub, email=apple_user.email))
        mocker.patch.object(apple_signin, 'exchange_authorization_code', return_value={})

        with app.app_context():
            state = auth_api._sign_apple_state({'platform': 'web'})

        resp = client.post('/api/auth/apple/callback', data={
            'state': state, 'code': 'c', 'id_token': 't',
        })

        frontend = app.config.get('FRONTEND_URL', 'https://laprod.net')
        assert resp.status_code == 302
        assert resp.location.startswith(f'{frontend}/oauth-callback?code=')

    def test_invalid_state_fails_closed(self, client, db, app):
        """Un state absent/forgé ne doit jamais aboutir à une connexion — le
        flow retombe en erreur générique (pas de plateforme de confiance connue,
        donc pas de redirection custom scheme non plus)."""
        resp = client.post('/api/auth/apple/callback', data={
            'state': 'not-a-real-signed-state', 'code': 'c', 'id_token': 't',
        })
        assert resp.status_code == 302
        assert 'error=oauth_failed' in resp.location

    def test_invalid_identity_token_fails_closed(self, client, db, app, mocker):
        mocker.patch.object(apple_signin, 'verify_identity_token',
                             side_effect=apple_signin.AppleSignInError('bad sig'))

        with app.app_context():
            state = auth_api._sign_apple_state({'platform': 'web'})

        resp = client.post('/api/auth/apple/callback', data={
            'state': state, 'code': 'c', 'id_token': 'garbage',
        })
        assert resp.status_code == 302
        assert 'error=oauth_failed' in resp.location


class TestAppleNativeLogin:

    def test_known_apple_sub_logs_in(self, client, db, apple_user, mocker):
        mocker.patch.object(apple_signin, 'verify_identity_token',
                             return_value=_claims(sub=apple_user.apple_sub, email=apple_user.email))
        mocker.patch.object(apple_signin, 'exchange_authorization_code', return_value={'refresh_token': 'rt-1'})

        resp = client.post('/api/auth/apple/native', json={
            'identity_token': 't', 'authorization_code': 'c',
        })

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['success'] is True
        assert body['data']['user']['id'] == apple_user.id
        assert body['data']['next'] == '/'

    def test_new_user_created_pending_completion(self, client, db, app, mocker):
        email = f'new_apple_{uuid.uuid4().hex[:8]}@privaterelay.appleid.com'
        mocker.patch.object(apple_signin, 'verify_identity_token', return_value=_claims(email=email))
        mocker.patch.object(apple_signin, 'exchange_authorization_code', return_value={'refresh_token': 'rt-2'})

        resp = client.post('/api/auth/apple/native', json={
            'identity_token': 't', 'authorization_code': 'c', 'given_name': 'Zoé',
        })

        assert resp.status_code == 200
        body = resp.get_json()
        assert body['data']['next'] == 'complete-profile'
        assert body['data']['suggested_name'] == 'Zoé'

        from models import User
        with app.app_context():
            created = db.session.query(User).filter_by(email=email).first()
            assert created is not None
            assert created.oauth_provider == 'apple'
            assert created.account_status == 'pending_completion'
            assert created.apple_refresh_token == 'rt-2'

    def test_email_already_linked_to_another_provider_conflicts(self, client, db, bound_factories, mocker):
        from tests.factories.user_factory import UserFactory
        existing = UserFactory(email_verified=True, user_type_selected=True)
        existing.oauth_provider = 'google'
        existing.google_id = f'g-{uuid.uuid4().hex[:8]}'
        db.session.commit()

        mocker.patch.object(apple_signin, 'verify_identity_token',
                             return_value=_claims(email=existing.email))
        mocker.patch.object(apple_signin, 'exchange_authorization_code', return_value={})

        resp = client.post('/api/auth/apple/native', json={
            'identity_token': 't', 'authorization_code': 'c',
        })

        assert resp.status_code == 409
        assert resp.get_json()['code'] == 'OAUTH_CONFLICT'

    def test_invalid_identity_token_rejected(self, client, db, mocker):
        mocker.patch.object(apple_signin, 'verify_identity_token',
                             side_effect=apple_signin.AppleSignInError('bad sig'))

        resp = client.post('/api/auth/apple/native', json={
            'identity_token': 'garbage', 'authorization_code': 'c',
        })

        assert resp.status_code == 401

    def test_missing_tokens_rejected(self, client, db):
        resp = client.post('/api/auth/apple/native', json={})
        assert resp.status_code == 400


class TestAppleAccountDeletionRevokesToken:

    def test_delete_own_account_revokes_apple_token(self, client, db, app, apple_user, mocker):
        # Compte Apple pur : jamais de mot de passe local, comme un vrai compte
        # OAuth (cf. commentaire de delete_own_account) — la factory en pose un
        # par défaut, on le retire pour refléter ce cas.
        apple_user.password_hash = None
        apple_user.apple_refresh_token = 'rt-to-revoke'
        apple_user.apple_refresh_token_client_id = 'net.laprod.app'
        db.session.commit()

        revoke_mock = mocker.patch.object(apple_signin, 'revoke_refresh_token', return_value=True)

        from flask_jwt_extended import create_access_token
        with app.app_context():
            token = create_access_token(identity=str(apple_user.id))

        resp = client.delete('/api/main/users/me',
                              headers={'Authorization': f'Bearer {token}'},
                              json={})

        assert resp.status_code == 200, resp.get_json()
        revoke_mock.assert_called_once_with('rt-to-revoke', 'net.laprod.app')
        db.session.refresh(apple_user)
        assert apple_user.apple_refresh_token is None
