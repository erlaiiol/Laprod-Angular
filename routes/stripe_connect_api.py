"""
Blueprint STRIPE CONNECT API — JSON API pour l'onboarding Stripe Connect (frontend Angular)

GET   /api/stripe/status        → Statut du compte Connect de l'utilisateur
POST  /api/stripe/setup-url     → Crée ou récupère l'URL d'onboarding
POST  /api/stripe/dashboard-url → Lien vers l'Express Dashboard Stripe
POST  /api/stripe/refresh       → Rafraîchit le statut depuis Stripe
"""
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required

from extensions import db, csrf
from stripe_connect_helpers import (
    create_connect_account,
    create_account_link,
    check_account_status,
    create_dashboard_link,
)
from serializers import ok, err
from utils.auth_helpers import require_user

stripe_connect_api_bp = Blueprint('stripe_connect_api', __name__, url_prefix='/api/stripe-connect')


# ── GET /api/stripe/status ─────────────────────────────────────────────────────

@stripe_connect_api_bp.route('/status', methods=['GET'])
@jwt_required()
@require_user
def get_status(current_user):
    """Retourne le statut Stripe Connect de l'utilisateur connecté."""
    return ok(data={
        'stripe_account_id':          current_user.stripe_account_id,
        'stripe_onboarding_complete': current_user.stripe_onboarding_complete,
        'stripe_account_status':      current_user.stripe_account_status,
    })


# ── POST /api/stripe/setup-url ─────────────────────────────────────────────────

@stripe_connect_api_bp.route('/setup-url', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def get_setup_url(current_user):
    """
    Crée un compte Stripe Connect si nécessaire, puis retourne l'URL d'onboarding.

    Corps JSON (optionnel) : { "return_url": str, "refresh_url": str }
    Par défaut pointe vers /wallet dans l'Angular.
    """
    if not (current_user.is_beatmaker or current_user.is_mix_engineer):
        return err(
            'Réservé aux beatmakers et mix engineers.', code='FORBIDDEN', status=403,
        )

    try:
        data         = request.get_json() or {}
        base_angular = current_app.config.get('FRONTEND_URL', 'laprod.net')
        return_url   = data.get('return_url',  f"{base_angular}/wallet")
        refresh_url  = data.get('refresh_url', f"{base_angular}/wallet")

        if not current_user.stripe_account_id:
            result = create_connect_account(current_user)
            if not result.get('success'):
                return err(
                    result.get('message', 'Erreur création compte.'),
                    code='STRIPE_ERROR', status=500,
                )
            # create_connect_account commit déjà l'account_id sur user

        account_link = create_account_link(current_user, return_url=return_url, refresh_url=refresh_url)
        url = account_link.get('url') if isinstance(account_link, dict) else account_link.url

        return ok(data={'url': url})

    except Exception as e:
        current_app.logger.error(f"Erreur setup Stripe Connect: {e}", exc_info=True)
        return err(str(e), code='STRIPE_ERROR', status=500)


# ── POST /api/stripe/dashboard-url ────────────────────────────────────────────

@stripe_connect_api_bp.route('/dashboard-url', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def get_dashboard_url(current_user):
    """Retourne l'URL du dashboard Express Stripe pour l'utilisateur."""
    if not current_user.stripe_account_id:
        return err('Compte Stripe Connect non configuré.', code='NOT_FOUND', status=404)

    try:
        link = create_dashboard_link(current_user.stripe_account_id)
        url  = link.get('url') if isinstance(link, dict) else link.url
        return ok(data={'url': url})
    except Exception as e:
        current_app.logger.error(f"Erreur dashboard Stripe: {e}", exc_info=True)
        return err(str(e), code='STRIPE_ERROR', status=500)


# ── POST /api/stripe/refresh ───────────────────────────────────────────────────

@stripe_connect_api_bp.route('/refresh', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def refresh_status(current_user):
    """Rafraîchit le statut du compte Stripe Connect depuis l'API Stripe."""
    if not current_user.stripe_account_id:
        return err('Compte Stripe non configuré.', code='NOT_FOUND', status=404)

    try:
        status_data = check_account_status(current_user.stripe_account_id)
        if isinstance(status_data, dict):
            current_user.stripe_onboarding_complete = status_data.get('onboarding_complete', False)
            current_user.stripe_account_status      = status_data.get('status', 'pending')
        db.session.commit()

        return ok(data={
            'stripe_onboarding_complete': current_user.stripe_onboarding_complete,
            'stripe_account_status':      current_user.stripe_account_status,
        })
    except Exception as e:
        current_app.logger.error(f"Erreur refresh Stripe Connect: {e}", exc_info=True)
        return err(str(e), code='STRIPE_ERROR', status=500)
