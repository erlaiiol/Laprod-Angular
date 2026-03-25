"""
Service wallet — fonctions métier pour le système de gains LaProd.

Pattern : Separate Charges and Transfers (Stripe)
- LaProd encaisse 100% du paiement.
- Les revenus du vendeur s'accumulent dans un wallet interne (status=pending).
- Après 7 jours, ils passent en 'available' (retirables).
- Le retrait déclenche un stripe.Transfer vers le compte Connect du vendeur.
"""
from decimal import Decimal
from datetime import datetime, timedelta

from extensions import db


# ---------------------------------------------------------------------------
# Crédits wallet — appelés depuis les routes de paiement
# ---------------------------------------------------------------------------

def credit_wallet_for_beat_sale(purchase):
    """
    Crédite le wallet du compositeur après une vente de beat.
    Appelé depuis routes/payment.py success() après db.session.flush().
    Pas de commit ici : géré par la route appelante.
    """
    from models import WalletTransaction

    composer = purchase.track.composer_user
    wallet = composer.get_or_create_wallet()

    amount = Decimal(str(purchase.composer_revenue))
    available_at = datetime.now() + timedelta(days=7)

    txn = WalletTransaction(
        wallet_id=wallet.id,
        type='credit_beat_sale',
        amount=amount,
        status='pending',
        available_at=available_at,
        purchase_id=purchase.id,
        description=f"Vente beat '{purchase.track.title}' ({purchase.format_purchased.upper()})"
    )
    db.session.add(txn)

    wallet.balance_pending = (wallet.balance_pending or Decimal('0')) + amount
    wallet.updated_at = datetime.now()


def credit_wallet_for_mixmaster_deposit(mixmaster_request):
    """
    Crédite le wallet de l'engineer pour l'acompte 30% du mixmaster.
    amount = deposit_amount * 90% (après commission LaProd 10%).
    Pas de commit ici : géré par la route appelante.
    """
    from models import WalletTransaction

    engineer = mixmaster_request.engineer
    wallet = engineer.get_or_create_wallet()

    amount = Decimal(str(round(float(mixmaster_request.deposit_amount) * 0.90, 2)))
    available_at = datetime.now() + timedelta(days=7)

    txn = WalletTransaction(
        wallet_id=wallet.id,
        type='credit_mixmaster_deposit',
        amount=amount,
        status='pending',
        available_at=available_at,
        mixmaster_request_id=mixmaster_request.id,
        description=f"Acompte mix/master #{mixmaster_request.id} (30% · commission 10% déduite)"
    )
    db.session.add(txn)

    wallet.balance_pending = (wallet.balance_pending or Decimal('0')) + amount
    wallet.updated_at = datetime.now()


def credit_wallet_for_mixmaster_revision(mixmaster_request):
    """
    Crédite le wallet de l'engineer pour un acompte de révision (10% brut → 9% net).
    Pattern lazy : le Transfer Stripe vers Connect sera créé lors du retrait.
    Pas de commit ici : géré par la route appelante.
    """
    from models import WalletTransaction

    engineer = mixmaster_request.engineer
    wallet = engineer.get_or_create_wallet()

    amount = Decimal(str(mixmaster_request.get_revision_transfer_amount()))
    available_at = datetime.now() + timedelta(days=7)
    revision_num = mixmaster_request.revision_count  # déjà incrémenté au moment de l'appel

    txn = WalletTransaction(
        wallet_id=wallet.id,
        type='credit_mixmaster_revision',
        amount=amount,
        status='pending',
        available_at=available_at,
        mixmaster_request_id=mixmaster_request.id,
        description=f"Acompte révision {revision_num} mix/master #{mixmaster_request.id} (10% · commission 10% déduite)"
    )
    db.session.add(txn)

    wallet.balance_pending = (wallet.balance_pending or Decimal('0')) + amount
    wallet.updated_at = datetime.now()


def credit_wallet_for_mixmaster_final(mixmaster_request):
    """
    Crédite le wallet de l'engineer pour le solde final du mixmaster.
    Le montant tient compte du nombre de révisions déjà payées :
    - 0 révision : 70% × 90% = 63%
    - 1 révision : 60% × 90% = 54%
    - 2 révisions : 50% × 90% = 45%
    Pas de commit ici : géré par la route appelante.
    """
    from models import WalletTransaction

    engineer = mixmaster_request.engineer
    wallet = engineer.get_or_create_wallet()

    amount = Decimal(str(mixmaster_request.get_final_transfer_amount()))
    available_at = datetime.now() + timedelta(days=7)

    txn = WalletTransaction(
        wallet_id=wallet.id,
        type='credit_mixmaster_final',
        amount=amount,
        status='pending',
        available_at=available_at,
        mixmaster_request_id=mixmaster_request.id,
        description=f"Solde final mix/master #{mixmaster_request.id} (commission 10% déduite)"
    )
    db.session.add(txn)

    wallet.balance_pending = (wallet.balance_pending or Decimal('0')) + amount
    wallet.updated_at = datetime.now()


# ---------------------------------------------------------------------------
# Transitions de statuts — appelées au chargement de la page wallet (lazy)
# et par les jobs APScheduler (global)
# ---------------------------------------------------------------------------

def process_pending_to_available(wallet):
    """
    Passe les transactions 'pending' dont available_at est dépassé vers 'available'.
    Met à jour balance_pending et balance_available du wallet.
    Retourne le nombre de transactions transitionées.
    Pas de commit : géré par l'appelant.
    """
    from models import WalletTransaction

    now = datetime.now()
    pending_ready = db.session.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == wallet.id,
        WalletTransaction.status == 'pending',
        WalletTransaction.available_at <= now
    ).all()

    total = Decimal('0')
    for txn in pending_ready:
        txn.status = 'available'
        total += txn.amount

    if total > 0:
        wallet.balance_pending   -= total
        wallet.balance_available += total
        wallet.updated_at = now

    return len(pending_ready)


def process_expirations(wallet):
    """
    Expire les transactions 'pending' ou 'available' créées il y a plus de 2 ans.
    Déduit les montants des balances correspondantes.
    Retourne le nombre de transactions expirées.
    Pas de commit : géré par l'appelant.
    """
    from models import WalletTransaction

    two_years_ago = datetime.now() - timedelta(days=730)

    expirable = db.session.query(WalletTransaction).filter(
        WalletTransaction.wallet_id == wallet.id,
        WalletTransaction.status.in_(['pending', 'available']),
        WalletTransaction.created_at <= two_years_ago
    ).all()

    for txn in expirable:
        if txn.status == 'available':
            wallet.balance_available -= txn.amount
        else:
            wallet.balance_pending -= txn.amount
        txn.status = 'expired'

    if expirable:
        wallet.updated_at = datetime.now()

    return len(expirable)


# ---------------------------------------------------------------------------
# Retrait
# ---------------------------------------------------------------------------

def perform_withdrawal(user, amount_requested):
    """
    Initie un retrait vers le compte Stripe Connect de l'utilisateur.

    Flow :
    1. Valider montant minimum (10€) et balance disponible
    2. Vérifier Connect actif
    3. Créer un stripe.Transfer (LaProd → Connect account)
    4. Marquer les WalletTransactions 'available' → 'transferred' (FIFO)
    5. Créer une transaction 'withdrawal'
    6. Déduire du wallet

    Retourne dict : {'success': bool, 'error': str|None, 'transfer_id': str|None, 'amount': float|None}
    Pas de commit : géré par la route appelante.
    """
    import stripe
    from models import WalletTransaction

    MIN_WITHDRAWAL = Decimal('10.00')
    amount = Decimal(str(amount_requested))

    if amount < MIN_WITHDRAWAL:
        return {'success': False, 'error': f'Montant minimum de retrait : {MIN_WITHDRAWAL}€'}

    wallet = user.wallet
    if not wallet or wallet.balance_available < amount:
        return {'success': False, 'error': 'Solde disponible insuffisant'}

    if not user.stripe_account_id:
        return {'success': False, 'error': 'connect_required'}

    if not user.stripe_onboarding_complete or user.stripe_account_status != 'active':
        return {'success': False, 'error': 'connect_incomplete'}

    try:
        transfer = stripe.Transfer.create(
            amount=int(amount * 100),  # en centimes
            currency='eur',
            destination=user.stripe_account_id,
            metadata={
                'user_id': str(user.id),
                'username': user.username,
                'wallet_id': str(wallet.id),
                'withdrawal_amount': str(amount),
            }
        )

        # Marquer les transactions disponibles comme transférées (FIFO)
        available_txns = db.session.query(WalletTransaction).filter(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.status == 'available'
        ).order_by(WalletTransaction.created_at.asc()).all()

        remaining = amount
        for txn in available_txns:
            if remaining <= 0:
                break
            txn.status = 'transferred'
            txn.stripe_transfer_id = transfer.id
            remaining -= txn.amount

        # Transaction de retrait
        withdrawal_txn = WalletTransaction(
            wallet_id=wallet.id,
            type='withdrawal',
            amount=amount,
            status='transferred',
            stripe_transfer_id=transfer.id,
            description=f'Retrait vers compte Stripe Connect ({transfer.id})'
        )
        db.session.add(withdrawal_txn)

        wallet.balance_available -= amount
        wallet.updated_at = datetime.now()

        return {'success': True, 'transfer_id': transfer.id, 'amount': float(amount)}

    except stripe.error.StripeError as e:
        return {'success': False, 'error': str(e)}
