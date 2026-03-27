"""
Blueprint STRIPE CONNECT API — JSON API pour l'onboarding Stripe Connect (frontend Angular)

GET   /api/stripe/status        → Statut du compte Connect de l'utilisateur
POST  /api/stripe/setup-url     → Crée ou récupère l'URL d'onboarding
POST  /api/stripe/dashboard-url → Lien vers l'Express Dashboard Stripe
POST  /api/stripe/refresh       → Rafraîchit le statut depuis Stripe
"""
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import User
from stripe_connect_helpers import (
    create_connect_account,
    create_account_link,
    check_account_status,
    create_dashboard_link,
)

stripe_connect_api_bp = Blueprint('stripe_connect_api', __name__, url_prefix='/api/stripe')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok(data=None, message='', status=200):
    body = {'success': True, 'feedback': {'level': 'success', 'message': message}}
    if data is not None:
        body['data'] = data
    return jsonify(body), status


def _err(message, level='error', code=None, status=400):
    body = {'success': False, 'feedback': {'level': level, 'message': message}}
    if code:
        body['code'] = code
    return jsonify(body), status


# ── GET /api/stripe/status ─────────────────────────────────────────────────────

@stripe_connect_api_bp.route('/status', methods=['GET'])
@jwt_required()
def get_status():
    """Retourne le statut Stripe Connect de l'utilisateur connecté."""
    current_user_id = int(get_jwt_identity())
    user = db.session.get(User, current_user_id)
    if not user:
        return _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    return _ok(data={
        'stripe_account_id':          user.stripe_account_id,
        'stripe_onboarding_complete': user.stripe_onboarding_complete,
        'stripe_account_status':      user.stripe_account_status,
    })


# ── POST /api/stripe/setup-url ─────────────────────────────────────────────────

@stripe_connect_api_bp.route('/setup-url', methods=['POST'])
@jwt_required()
def get_setup_url():
    """
    Crée un compte Stripe Connect si nécessaire, puis retourne l'URL d'onboarding.

    Corps JSON (optionnel) : { "return_url": str, "refresh_url": str }
    Par défaut pointe vers /wallet dans l'Angular.
    """
    current_user_id = int(get_jwt_identity())
    user = db.session.get(User, current_user_id)
    if not user:
        return _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    if not (user.is_beatmaker or user.is_mix_engineer):
        return _err(
            'Réservé aux beatmakers et mix engineers.', code='FORBIDDEN', status=403,
        )

    try:
        data         = request.get_json() or {}
        base_angular = current_app.config.get('ANGULAR_BASE_URL', 'http://localhost:4200')
        return_url   = data.get('return_url',  f"{base_angular}/wallet")
        refresh_url  = data.get('refresh_url', f"{base_angular}/wallet")

        if not user.stripe_account_id:
            result = create_connect_account(user)
            if not result.get('success'):
                return _err(
                    result.get('message', 'Erreur création compte.'),
                    code='STRIPE_ERROR', status=500,
                )
            # create_connect_account commit déjà l'account_id sur user

        account_link = create_account_link(user, return_url=return_url, refresh_url=refresh_url)
        url = account_link.get('url') if isinstance(account_link, dict) else account_link.url

        return _ok(data={'url': url})

    except Exception as e:
        current_app.logger.error(f"Erreur setup Stripe Connect: {e}", exc_info=True)
        return _err(str(e), code='STRIPE_ERROR', status=500)


# ── POST /api/stripe/dashboard-url ────────────────────────────────────────────

@stripe_connect_api_bp.route('/dashboard-url', methods=['POST'])
@jwt_required()
def get_dashboard_url():
    """Retourne l'URL du dashboard Express Stripe pour l'utilisateur."""
    current_user_id = int(get_jwt_identity())
    user = db.session.get(User, current_user_id)
    if not user or not user.stripe_account_id:
        return _err('Compte Stripe Connect non configuré.', code='NOT_FOUND', status=404)

    try:
        link = create_dashboard_link(user.stripe_account_id)
        url  = link.get('url') if isinstance(link, dict) else link.url
        return _ok(data={'url': url})
    except Exception as e:
        current_app.logger.error(f"Erreur dashboard Stripe: {e}", exc_info=True)
        return _err(str(e), code='STRIPE_ERROR', status=500)


# ── POST /api/stripe/refresh ───────────────────────────────────────────────────

@stripe_connect_api_bp.route('/refresh', methods=['POST'])
@jwt_required()
def refresh_status():
    """Rafraîchit le statut du compte Stripe Connect depuis l'API Stripe."""
    current_user_id = int(get_jwt_identity())
    user = db.session.get(User, current_user_id)
    if not user or not user.stripe_account_id:
        return _err('Compte Stripe non configuré.', code='NOT_FOUND', status=404)

    try:
        status_data = check_account_status(user.stripe_account_id)
        if isinstance(status_data, dict):
            user.stripe_onboarding_complete = status_data.get('onboarding_complete', False)
            user.stripe_account_status      = status_data.get('status', 'pending')
        db.session.commit()

        return _ok(data={
            'stripe_onboarding_complete': user.stripe_onboarding_complete,
            'stripe_account_status':      user.stripe_account_status,
        })
    except Exception as e:
        current_app.logger.error(f"Erreur refresh Stripe Connect: {e}", exc_info=True)
        return _err(str(e), code='STRIPE_ERROR', status=500)
