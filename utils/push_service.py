"""
Envoi de notifications push via Firebase Cloud Messaging (FCM).

Best-effort strict, même discipline que le cache Redis (cf. docs/conventions.md
§ Cache Redis) : un push manqué ne doit jamais faire échouer le flux appelant
(job planifié, route API). L'absence d'identifiants Firebase (dev/local) ne
doit pas non plus faire planter le serveur — _get_app() renvoie alors None et
send_push() se contente de ne rien envoyer.

Mobile uniquement (Capacitor natif, cf. docs/roadmap.md § Chantier 2 — décision
2.1) : aucun appel de ce module ne doit être déclenché depuis un contexte web.
"""
import json
import os
from datetime import datetime

from extensions import db
from models import DeviceToken, User

REENGAGEMENT_INACTIVITY_DAYS  = 14
MAX_PUSH_PER_USER_PER_30_DAYS = 1   # un seul push de réactivation par mois glissant, tous rôles confondus

_ALLOWED_PLATFORMS = {'android', 'ios'}

_firebase_app = None
_firebase_app_initialized = False


def _get_app():
    """Initialise paresseusement l'app Firebase Admin, une seule fois par process.

    FIREBASE_CREDENTIALS_JSON contient le JSON du compte de service Firebase
    (jamais un chemin de fichier — cohérent avec le fait qu'aucun secret n'est
    committé ni déposé sur le système de fichiers du conteneur).
    """
    global _firebase_app, _firebase_app_initialized
    if _firebase_app_initialized:
        return _firebase_app

    _firebase_app_initialized = True
    creds_json = os.environ.get('FIREBASE_CREDENTIALS_JSON')
    if not creds_json:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
        cred = credentials.Certificate(json.loads(creds_json))
        _firebase_app = firebase_admin.initialize_app(cred)
    except Exception:
        _firebase_app = None
    return _firebase_app


def register_token(user_id, token, platform):
    """Enregistre ou réactive un jeton d'appareil.

    Idempotent : un même jeton réenregistré (relance de l'app, refresh du
    jeton par l'OS) met juste à jour son propriétaire et last_seen_at plutôt
    que de dupliquer la ligne — `token` est unique en base.
    Ne commite pas : la route appelante commite (cf. utils/crud_helpers.py::commit_or_rollback).
    """
    existing = DeviceToken.query.filter_by(token=token).first()
    if existing:
        existing.user_id      = user_id
        existing.platform     = platform
        existing.is_active    = True
        existing.last_seen_at = datetime.now()
        return existing

    device = DeviceToken(user_id=user_id, token=token, platform=platform)
    db.session.add(device)
    return device


def deactivate_token(user_id, token):
    """Désactive un jeton précis appartenant à l'utilisateur (logout, désinstall)."""
    DeviceToken.query.filter_by(user_id=user_id, token=token).update({'is_active': False})


def deactivate_all_tokens(user_id):
    """Désactive tous les jetons d'un utilisateur (retrait du consentement push)."""
    DeviceToken.query.filter_by(user_id=user_id).update({'is_active': False})


def send_push(user_id, title, body, link=None):
    """Envoie un push best-effort à tous les appareils actifs de l'utilisateur.

    Ne fait rien (retourne False) si :
      - l'utilisateur n'a pas activé push_opt_in (permission OS ≠ consentement produit) ;
      - il n'a aucun DeviceToken actif ;
      - Firebase n'est pas configuré (dev/local sans FIREBASE_CREDENTIALS_JSON) ;
      - l'envoi échoue pour une raison quelconque.

    Ne lève jamais — c'est un canal secondaire, jamais un chemin bloquant.
    """
    user = db.session.get(User, user_id)
    if not user or not user.push_opt_in:
        return False

    tokens = DeviceToken.query.filter_by(user_id=user_id, is_active=True).all()
    if not tokens:
        return False

    app = _get_app()
    if app is None:
        return False

    try:
        from firebase_admin import messaging
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data={'link': link} if link else {},
            tokens=[t.token for t in tokens],
        )
        response = messaging.send_each_for_multicast(message, app=app)
    except Exception:
        return False

    for token_obj, result in zip(tokens, response.responses):
        if result.success:
            continue
        error_code = getattr(result.exception, 'code', None)
        # Jeton mort côté FCM : désactivé, jamais supprimé (cf. docstring DeviceToken).
        if error_code in ('UNREGISTERED', 'INVALID_ARGUMENT', 'NOT_FOUND'):
            token_obj.is_active = False

    return response.success_count > 0
