"""
Blueprint WALLET API — GET endpoints pour les données wallet (frontend Angular)

GET  /api/wallet       → soldes + historique des transactions (jwt_required)
"""
from datetime import datetime, timedelta

from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db, csrf
from models import User, WalletTransaction
from utils.wallet_service import process_pending_to_available, process_expirations
from serializers import ok, err, wallet_transaction as ser_wallet_txn

wallet_api_bp = Blueprint('wallet_api', __name__, url_prefix='/api/wallet')


# ── GET /api/wallet ────────────────────────────────────────────────────────────

@wallet_api_bp.route('', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_wallet():
    """Retourne le wallet de l'utilisateur connecté : soldes + transactions (100 dernières)."""
    current_user_id = int(get_jwt_identity())
    user = db.session.get(User, current_user_id)
    if not user:
        return _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    if not (user.is_beatmaker or user.is_mix_engineer):
        return err(
            'Accès réservé aux beatmakers et mix engineers.',
            code='FORBIDDEN', status=403,
        )

    wallet = user.get_or_create_wallet()

    # Transitions lazy : pending → available, expirations 2 ans
    transitioned = process_pending_to_available(wallet)
    expired      = process_expirations(wallet)
    if transitioned > 0 or expired > 0:
        db.session.commit()

    # Alerte Connect si fonds > 6 mois sans onboarding
    show_connect_alert = False
    if not user.stripe_onboarding_complete:
        six_months_ago = datetime.now() - timedelta(days=180)
        oldest = db.session.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.status.in_(['pending', 'available']),
            WalletTransaction.created_at <= six_months_ago,
        ).first()
        if oldest:
            show_connect_alert = True

    transactions = (
        db.session.query(WalletTransaction)
        .filter(WalletTransaction.wallet_id == wallet.id)
        .order_by(WalletTransaction.created_at.desc())
        .limit(100)
        .all()
    )

    # Toast informatif si Stripe non configuré et gains disponibles
    stripe_hint = ''
    if not user.stripe_onboarding_complete and float(wallet.balance_available) > 0:
        stripe_hint = 'Configurez Stripe Connect pour retirer vos gains.'

    return ok(data={
        'wallet': {
            'balance_available':       float(wallet.balance_available),
            'balance_pending':         float(wallet.balance_pending),
            'stripe_account_id':       user.stripe_account_id,
            'stripe_onboarding_complete': user.stripe_onboarding_complete,
            'stripe_account_status':   user.stripe_account_status,
        },
        'transactions':      [ser_wallet_txn(t) for t in transactions],
        'show_connect_alert': show_connect_alert,
    }, message=stripe_hint)
