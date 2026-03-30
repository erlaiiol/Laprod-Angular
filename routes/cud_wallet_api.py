"""
Blueprint CUD WALLET API — POST endpoints pour les actions wallet (frontend Angular)

POST  /api/wallet/withdraw   → Initier un retrait vers Stripe Connect (jwt_required)
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db
from models import User
from utils.wallet_service import perform_withdrawal, process_pending_to_available, process_expirations

cud_wallet_api_bp = Blueprint('cud_wallet_api', __name__, url_prefix='/cud_wallet')


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


# ── POST /api/wallet/withdraw ──────────────────────────────────────────────────

@cud_wallet_api_bp.route('/withdraw', methods=['POST'])
@jwt_required()
def withdraw():
    """
    Initie un retrait vers le compte Stripe Connect de l'utilisateur.

    Corps JSON : { "amount": float }

    Retourne :
      { success: true, data: { transfer_id: str, amount: float } }
    """
    current_user_id = int(get_jwt_identity())
    user = db.session.get(User, current_user_id)
    if not user:
        return _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    if not (user.is_beatmaker or user.is_mix_engineer):
        return _err(
            'Accès réservé aux beatmakers et mix engineers.',
            code='FORBIDDEN', status=403,
        )

    wallet = user.get_or_create_wallet()

    # Transitions lazy avant de vérifier la balance disponible
    process_pending_to_available(wallet)
    process_expirations(wallet)

    if not user.stripe_account_id:
        return _err(
            'Configurez votre compte Stripe Connect pour recevoir vos gains.',
            code='CONNECT_REQUIRED', status=403,
        )

    if not user.stripe_onboarding_complete or user.stripe_account_status != 'active':
        return _err(
            "Votre compte Stripe n'est pas encore complet. Finalisez la configuration.",
            code='CONNECT_INCOMPLETE', status=403,
        )

    data = request.get_json() or {}
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        return _err('Montant invalide.', code='INVALID_AMOUNT', status=400)

    result = perform_withdrawal(user, amount)

    if result.get('error') == 'connect_required':
        return _err(
            'Configurez votre compte Stripe Connect.', code='CONNECT_REQUIRED', status=403,
        )
    if result.get('error') == 'connect_incomplete':
        return _err(
            "Votre compte Stripe n'est pas encore actif.", code='CONNECT_INCOMPLETE', status=403,
        )
    if not result['success']:
        return _err(result.get('error', 'Erreur lors du retrait.'), code='WITHDRAWAL_ERROR', status=400)

    db.session.commit()
    return _ok(
        data={'transfer_id': result['transfer_id'], 'amount': result['amount']},
        message=f"Retrait de {result['amount']}€ effectué. Fonds sous 1-2 jours ouvrés.",
    )
