"""
Vérification des tokens Cloudflare Turnstile (CAPTCHA anti-bot).

Utilisé par les routes d'auth (register + login après échecs) pour bloquer les
bots côté web. Volontairement tolérant à une panne Cloudflare : voir le
commentaire fail-open ci-dessous.
"""
import requests
from flask import current_app

_SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def verify_turnstile_token(token: str | None, secret: str | None, remote_ip: str | None = None) -> bool:
    """
    Valide un token Turnstile auprès de Cloudflare.

    - Token absent / secret non configuré → False (échec, on refuse).
    - Réponse Cloudflare `success=false` → False.
    - Service Cloudflare injoignable (timeout/réseau) → True (fail-open) : on ne
      bloque pas les utilisateurs légitimes pendant une panne CF ; le débit reste
      plafonné par nginx (limit_req) et Flask-Limiter en amont.
    """
    if not token or not secret:
        return False
    try:
        resp = requests.post(
            _SITEVERIFY_URL,
            data={'secret': secret, 'response': token, 'remoteip': remote_ip or ''},
            timeout=5,
        )
        return bool(resp.json().get('success'))
    except Exception as exc:
        current_app.logger.critical(f"[Turnstile] siteverify injoignable, fail-open : {exc}")
        return True
