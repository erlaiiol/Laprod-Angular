"""
Blueprint WALLET API — GET + CUD endpoints

GET   /api/wallet           → soldes + historique des transactions (jwt_required)
POST  /api/wallet/withdraw  → initier un retrait vers Stripe Connect (jwt_required)
"""
from datetime import datetime, timedelta

from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import select

from extensions import db, csrf
from models import User, WalletTransaction, Wallet
from utils.wallet_service import perform_withdrawal, process_pending_to_available, process_expirations
from serializers import ok, err, wallet_transaction as ser_wallet_txn
from utils.auth_helpers import require_user

wallet_api_bp = Blueprint('wallet_api', __name__, url_prefix='/api/wallet')


# ── GET /api/wallet ────────────────────────────────────────────────────────────

@wallet_api_bp.route('', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_wallet(current_user):
    """Retourne le wallet de l'utilisateur connecté : soldes + transactions (100 dernières)."""
    if not (current_user.is_beatmaker or current_user.is_mix_engineer):
        return err(
            'Accès réservé aux beatmakers et mix engineers.',
            code='FORBIDDEN', status=403,
        )

    # S'assurer que le wallet existe, puis VERROUILLER sa ligne avant les
    # transitions lazy (pending→available, expirations). Sans ce verrou, deux
    # GET concurrents lisent les mêmes transactions non transitionées et
    # double-comptent les soldes (lost update). Le verrou sérialise la section
    # critique : le second GET attend le commit du premier puis relit des
    # transactions déjà basculées → aucun double-comptage.
    current_user.get_or_create_wallet()
    wallet = db.session.execute(
        select(Wallet).where(Wallet.user_id == current_user.id).with_for_update()
    ).scalar_one()

    process_pending_to_available(wallet)
    process_expirations(wallet)
    # Commit systématique : persiste la création éventuelle du wallet et RELÂCHE
    # le verrou de ligne (un commit sans modification reste peu coûteux).
    db.session.commit()

    show_connect_alert = False
    if not current_user.stripe_onboarding_complete:
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

    stripe_hint = ''
    if not current_user.stripe_onboarding_complete and float(wallet.balance_available) > 0:
        stripe_hint = 'Configurez Stripe Connect pour retirer vos gains.'

    return ok(data={
        'wallet': {
            'balance_available':          float(wallet.balance_available),
            'balance_pending':            float(wallet.balance_pending),
            'stripe_account_id':          current_user.stripe_account_id,
            'stripe_onboarding_complete': current_user.stripe_onboarding_complete,
            'stripe_account_status':      current_user.stripe_account_status,
        },
        'transactions':      [ser_wallet_txn(t) for t in transactions],
        'show_connect_alert': show_connect_alert,
    }, message=stripe_hint)


# ── POST /api/wallet/withdraw ──────────────────────────────────────────────────

@wallet_api_bp.route('/withdraw', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def withdraw(current_user):
    """
    Initie un retrait vers le compte Stripe Connect de l'utilisateur.

    Corps JSON : { "amount": float }

    Retourne :
      { success: true, data: { transfer_id: str, amount: float } }
    """
    if not (current_user.is_beatmaker or current_user.is_mix_engineer):
        current_app.logger.warning(
            "[wallet] Retrait refusé | user=%s | raison=role_non_autorisé | "
            "is_beatmaker=%s | is_mix_engineer=%s",
            current_user.id, current_user.is_beatmaker, current_user.is_mix_engineer,
        )
        return err(
            'Accès réservé aux beatmakers et mix engineers.',
            code='FORBIDDEN', status=403,
        )

    wallet = current_user.get_or_create_wallet()

    process_pending_to_available(wallet)
    process_expirations(wallet)

    if not current_user.stripe_account_id:
        current_app.logger.warning(
            "[wallet] Retrait refusé | user=%s | raison=connect_absent", current_user.id,
        )
        return err(
            'Configurez votre compte Stripe Connect pour recevoir vos gains.',
            code='CONNECT_REQUIRED', status=403,
        )

    if not current_user.stripe_onboarding_complete or current_user.stripe_account_status != 'active':
        current_app.logger.warning(
            "[wallet] Retrait refusé | user=%s | raison=connect_incomplet | onboarding=%s | status=%s",
            current_user.id, current_user.stripe_onboarding_complete, current_user.stripe_account_status,
        )
        return err(
            "Votre compte Stripe n'est pas encore complet. Finalisez la configuration.",
            code='CONNECT_INCOMPLETE', status=403,
        )

    data = request.get_json() or {}
    try:
        amount = float(data.get('amount', 0))
    except (ValueError, TypeError):
        current_app.logger.warning(
            "[wallet] Retrait refusé | user=%s | raison=montant_invalide | payload=%s",
            current_user.id, data.get('amount'),
        )
        return err('Montant invalide.', code='INVALID_AMOUNT', status=400)

    result = perform_withdrawal(current_user, amount)

    if result.get('error') == 'connect_required':
        return err('Configurez votre compte Stripe Connect.', code='CONNECT_REQUIRED', status=403)
    if result.get('error') == 'connect_incomplete':
        return err("Votre compte Stripe n'est pas encore actif.", code='CONNECT_INCOMPLETE', status=403)
    if not result['success']:
        return err(result.get('error', 'Erreur lors du retrait.'), code='WITHDRAWAL_ERROR', status=400)

    db.session.commit()
    return ok(
        data={'transfer_id': result['transfer_id'], 'amount': result['amount']},
        message=f"Retrait de {result['amount']}€ effectué. Fonds sous 1-2 jours ouvrés.",
    )
