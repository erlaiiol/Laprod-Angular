"""
Jobs APScheduler pour le système de wallet.
- Toutes les heures : pending → available (pour les transactions dont available_at est passé)
- Chaque nuit à 2h  : expiration des fonds non retirés depuis 2 ans
"""
from datetime import datetime, timedelta
from decimal import Decimal


def run_pending_to_available_job(app):
    """
    Passe TOUTES les WalletTransactions 'pending' dont available_at est dépassé
    vers le statut 'available'. Met à jour les balances des wallets concernés.
    Tourne toutes les heures via APScheduler.
    """
    with app.app_context():
        from extensions import db
        from models import WalletTransaction, Wallet

        now = datetime.now()
        pending_ready = db.session.query(WalletTransaction).filter(
            WalletTransaction.status == 'pending',
            WalletTransaction.available_at <= now
        ).all()

        if not pending_ready:
            return

        # Agréger les deltas par wallet_id pour une seule mise à jour par wallet
        wallet_deltas = {}
        for txn in pending_ready:
            txn.status = 'available'
            wallet_deltas[txn.wallet_id] = wallet_deltas.get(txn.wallet_id, Decimal('0')) + txn.amount

        for wallet_id, delta in wallet_deltas.items():
            wallet = db.session.get(Wallet, wallet_id)
            if wallet:
                wallet.balance_pending   -= delta
                wallet.balance_available += delta
                wallet.updated_at = now

        db.session.commit()
        app.logger.info(f"[Wallet Job] {len(pending_ready)} transaction(s) passées à 'available'")


def run_expiration_job(app):
    """
    Expire les WalletTransactions 'pending' ou 'available' créées il y a plus de 2 ans.
    Envoie un email d'avertissement aux utilisateurs qui ont des fonds depuis >3 mois
    sans avoir configuré Stripe Connect.
    Tourne chaque nuit à 2h via APScheduler.
    """
    with app.app_context():
        from extensions import db
        from models import WalletTransaction, Wallet, User

        now = datetime.now()
        two_years_ago   = now - timedelta(days=730)
        three_months_ago = now - timedelta(days=90)

        # --- Expiration 2 ans ---
        expirable = db.session.query(WalletTransaction).filter(
            WalletTransaction.status.in_(['pending', 'available']),
            WalletTransaction.created_at <= two_years_ago
        ).all()

        deltas_available = {}
        deltas_pending   = {}
        for txn in expirable:
            if txn.status == 'available':
                deltas_available[txn.wallet_id] = deltas_available.get(txn.wallet_id, Decimal('0')) + txn.amount
            else:
                deltas_pending[txn.wallet_id] = deltas_pending.get(txn.wallet_id, Decimal('0')) + txn.amount
            txn.status = 'expired'

        all_wallet_ids = set(deltas_available) | set(deltas_pending)
        for wallet_id in all_wallet_ids:
            wallet = db.session.get(Wallet, wallet_id)
            if wallet:
                wallet.balance_available -= deltas_available.get(wallet_id, Decimal('0'))
                wallet.balance_pending   -= deltas_pending.get(wallet_id, Decimal('0'))
                wallet.updated_at = now

        if expirable:
            db.session.commit()
            app.logger.info(f"[Wallet Job] {len(expirable)} transaction(s) expirée(s) (2 ans)")

        # --- Emails d'avertissement : fonds depuis >3 mois sans Connect ---
        wallets_at_risk = (
            db.session.query(Wallet)
            .join(User)
            .filter(
                Wallet.balance_pending > 0,
                User.stripe_onboarding_complete == False,
            )
            .all()
        )

        for wallet in wallets_at_risk:
            oldest = db.session.query(WalletTransaction).filter(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.status.in_(['pending', 'available']),
                WalletTransaction.created_at <= three_months_ago
            ).first()

            if oldest:
                try:
                    from utils import email_service
                    email_service.send_wallet_warning_email(wallet.user)
                except Exception as e:
                    app.logger.error(
                        f"[Wallet Job] Erreur email avertissement user#{wallet.user_id}: {e}"
                    )
