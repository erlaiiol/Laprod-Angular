"""
Sign in with Apple — vérification des identity tokens et appels serveur-à-serveur
(échange de code, révocation).

Trois responsabilités, séparées comme dans le reste du dossier `utils/` :
1. Vérifier un identity token Apple (JWT RS256) contre les clés publiques
   d'Apple (JWKS, cache Redis best-effort — cf. R4, aucun code ne doit supposer
   que Redis répond).
2. Générer le `client_secret` Apple (JWT ES256 signé avec la clé privée .p8,
   valable quelques minutes) — Apple exige un secret *régénéré*, jamais statique,
   contrairement à GOOGLE_CLIENT_SECRET.
3. Parler au serveur Apple (échange code → refresh_token, révocation à la
   suppression de compte).

Utilisé par routes/auth_api.py (login web + natif) et par la suppression de
compte (routes/main_api.py, routes/admin_api.py).
"""
import time
import requests
from flask import current_app
from authlib.jose import jwt, JsonWebKey
from authlib.jose.errors import JoseError

_KEYS_URL = 'https://appleid.apple.com/auth/keys'
_TOKEN_URL = 'https://appleid.apple.com/auth/token'
_REVOKE_URL = 'https://appleid.apple.com/auth/revoke'
_ISSUER = 'https://appleid.apple.com'

_JWKS_CACHE_KEY = 'laprod:apple:jwks'
_JWKS_CACHE_TTL = 24 * 3600  # les clés Apple tournent rarement, 24h est large et sûr


class AppleSignInError(Exception):
    """Identity token invalide, ou échange/révocation refusés par Apple."""


def _get_redis():
    """Connexion Redis fraîche — même pattern que routes/auth_api.py::_get_redis."""
    import redis as _redis_module
    return _redis_module.Redis(
        host=current_app.config['REDIS_HOST'],
        port=current_app.config['REDIS_PORT'],
        db=current_app.config['REDIS_DB'],
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
    )


def _fetch_jwks_dict() -> dict:
    """Renvoie le JWKS Apple courant. Tente le cache Redis, retombe toujours sur
    un appel réseau direct si le cache est indisponible ou vide (R4)."""
    import json

    try:
        r = _get_redis()
        cached = r.get(_JWKS_CACHE_KEY)
        if cached:
            return json.loads(cached)
    except Exception as exc:
        current_app.logger.warning(f'[Apple] cache JWKS indisponible : {exc}')

    resp = requests.get(_KEYS_URL, timeout=5)
    resp.raise_for_status()
    jwks = resp.json()

    try:
        r = _get_redis()
        r.setex(_JWKS_CACHE_KEY, _JWKS_CACHE_TTL, json.dumps(jwks))
    except Exception as exc:
        current_app.logger.warning(f'[Apple] écriture cache JWKS échouée (non bloquant) : {exc}')

    return jwks


def verify_identity_token(identity_token: str, audience: str) -> dict:
    """
    Vérifie la signature (clé publique Apple, JWKS), l'émetteur et l'audience
    d'un identity token Apple. Renvoie les claims (dont `sub`, `email`,
    `email_verified`) ou lève AppleSignInError.
    """
    try:
        jwks = _fetch_jwks_dict()
        key_set = JsonWebKey.import_key_set(jwks)
        claims = jwt.decode(identity_token, key_set)
        claims.validate()
    except JoseError as exc:
        raise AppleSignInError(f'identity token invalide : {exc}') from exc
    except (requests.RequestException, ValueError) as exc:
        raise AppleSignInError(f'JWKS Apple injoignable : {exc}') from exc

    if claims.get('iss') != _ISSUER:
        raise AppleSignInError(f"émetteur inattendu : {claims.get('iss')}")
    if claims.get('aud') != audience:
        raise AppleSignInError(f"audience inattendue : {claims.get('aud')}")
    if not claims.get('sub'):
        raise AppleSignInError('claim sub manquante')

    return dict(claims)


def _client_secret(client_id: str) -> str:
    """
    Construit le client_secret Apple (JWT ES256, valable 5 min) requis pour tout
    appel serveur-à-serveur (échange de code, révocation). `client_id` est soit
    APPLE_SERVICES_ID (flow web), soit APPLE_BUNDLE_ID (flow natif) — Apple exige
    que le secret cible exactement le client qui a obtenu le code/token à échanger.
    """
    private_key = current_app.config.get('APPLE_PRIVATE_KEY') or ''
    # Le .p8 est stocké en variable d'environnement sur une seule ligne ; les
    # retours à la ligne y sont encodés en "\n" littéral.
    private_key = private_key.replace('\\n', '\n')

    now = int(time.time())
    header = {'alg': 'ES256', 'kid': current_app.config['APPLE_KEY_ID']}
    payload = {
        'iss': current_app.config['APPLE_TEAM_ID'],
        'iat': now,
        'exp': now + 300,
        'aud': _ISSUER,
        'sub': client_id,
    }
    try:
        return jwt.encode(header, payload, private_key).decode('ascii')
    except JoseError as exc:
        raise AppleSignInError(f'génération du client_secret Apple échouée : {exc}') from exc


def exchange_authorization_code(code: str, client_id: str, redirect_uri: str | None = None) -> dict:
    """
    Échange un authorization_code contre un refresh_token (conservé uniquement
    pour pouvoir révoquer l'accès à la suppression du compte — id_token n'est
    pas réutilisé ici, on vérifie déjà celui reçu directement).
    `redirect_uri` uniquement pour le flow web (doit correspondre exactement à
    celui envoyé à /auth/authorize) ; absent pour le flow natif.
    """
    data = {
        'client_id': client_id,
        'client_secret': _client_secret(client_id),
        'code': code,
        'grant_type': 'authorization_code',
    }
    if redirect_uri:
        data['redirect_uri'] = redirect_uri

    try:
        resp = requests.post(_TOKEN_URL, data=data, timeout=8)
    except requests.RequestException as exc:
        raise AppleSignInError(f"échange de code injoignable : {exc}") from exc

    payload = resp.json() if resp.content else {}
    if resp.status_code != 200 or 'error' in payload:
        raise AppleSignInError(f"échange de code refusé par Apple : {payload.get('error', resp.status_code)}")

    return payload


def revoke_refresh_token(refresh_token: str, client_id: str) -> bool:
    """
    Révoque un refresh_token Apple (suppression de compte — cf. Apple "Sign in
    with Apple REST API", section Revoke Tokens). Best-effort et NON bloquant :
    une révocation échouée ne doit jamais empêcher la suppression du compte
    côté LaProd, elle est seulement loggée.
    """
    try:
        data = {
            'client_id': client_id,
            'client_secret': _client_secret(client_id),
            'token': refresh_token,
            'token_type_hint': 'refresh_token',
        }
        resp = requests.post(_REVOKE_URL, data=data, timeout=8)
        if resp.status_code != 200:
            current_app.logger.warning(f'[Apple] révocation refusée (status={resp.status_code}) : {resp.text[:200]}')
            return False
        return True
    except Exception as exc:
        current_app.logger.warning(f'[Apple] révocation impossible (non bloquant) : {exc}')
        return False
