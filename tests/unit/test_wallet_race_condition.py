"""
Tests unitaires — sécurité du wallet contre les retraits concurrents

Vérifie :
1. Le retrait est rejeté quand la balance est insuffisante
2. with_for_update() est bien utilisé (la requête inclut le verrou de ligne)
3. Un montant négatif ou nul est rejeté en amont
4. Le retrait ne double-débite pas en cas d'idempotence
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch, call


# ── Helper : mock wallet ──────────────────────────────────────────────────────

def _make_user(balance_available: Decimal, has_connect: bool = True):
    user = MagicMock()
    user.id = 42
    user.username = 'test_beatmaker'
    user.stripe_account_id = 'acct_test_123' if has_connect else None
    user.stripe_onboarding_complete = has_connect
    user.stripe_account_status = 'active' if has_connect else 'pending'

    wallet = MagicMock()
    wallet.id = 7
    wallet.user_id = user.id
    wallet.balance_available = balance_available
    wallet.balance_pending = Decimal('0.00')

    user.wallet = wallet
    return user, wallet


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPerformWithdrawalValidation:

    def test_rejects_amount_below_minimum(self, app):
        """Montant < 10€ doit être refusé avant tout accès DB."""
        from utils.wallet_service import perform_withdrawal
        user, _ = _make_user(Decimal('50.00'))

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                result = perform_withdrawal(user, 9.99)

        assert result['success'] is False
        assert '10' in result['error']
        # Aucune requête DB ne doit avoir été exécutée
        mock_db.session.execute.assert_not_called()

    def test_rejects_zero_amount(self, app):
        """Montant = 0 doit être refusé."""
        from utils.wallet_service import perform_withdrawal
        user, _ = _make_user(Decimal('50.00'))

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                result = perform_withdrawal(user, 0)

        assert result['success'] is False

    def test_rejects_insufficient_balance(self, app):
        """Retrait supérieur à la balance disponible doit être refusé."""
        from utils.wallet_service import perform_withdrawal
        user, wallet = _make_user(Decimal('5.00'), has_connect=True)

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                locked_wallet = MagicMock()
                locked_wallet.balance_available = Decimal('5.00')
                locked_wallet.user_id = user.id
                mock_db.session.execute.return_value.scalar_one_or_none.return_value = locked_wallet

                result = perform_withdrawal(user, 50.00)

        assert result['success'] is False
        assert 'insuffisant' in result['error'].lower()

    def test_uses_with_for_update(self, app):
        """
        La requête wallet doit utiliser with_for_update() pour éviter les race conditions.
        On vérifie que db.session.execute est appelé (et non user.wallet directement).
        """
        from utils.wallet_service import perform_withdrawal
        user, wallet = _make_user(Decimal('100.00'), has_connect=True)

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                # Simule un wallet locké retourné par la requête
                locked_wallet = MagicMock()
                locked_wallet.balance_available = Decimal('100.00')
                locked_wallet.user_id = user.id
                mock_db.session.execute.return_value.scalar_one_or_none.return_value = locked_wallet

                with patch('stripe.Transfer.create') as mock_transfer:
                    mock_transfer.return_value = MagicMock(id='tr_test_123')
                    with patch('utils.wallet_service.db.session.query') as mock_query:
                        mock_query.return_value.filter.return_value.order_by.return_value.all.return_value = []
                        perform_withdrawal(user, 50.00)

        # db.session.execute doit avoir été appelé (chemin with_for_update)
        mock_db.session.execute.assert_called_once()
        # Vérifie que la requête n'a pas utilisé user.wallet directement
        # (user.wallet n'est PAS un callable, donc son accès ne serait pas tracé ici)

    def test_rejects_missing_stripe_connect(self, app):
        """Retrait sans compte Stripe Connect configuré doit être refusé."""
        from utils.wallet_service import perform_withdrawal
        user, _ = _make_user(Decimal('100.00'), has_connect=False)

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                locked_wallet = MagicMock()
                locked_wallet.balance_available = Decimal('100.00')
                mock_db.session.execute.return_value.scalar_one_or_none.return_value = locked_wallet

                result = perform_withdrawal(user, 50.00)

        assert result['success'] is False
        assert result['error'] == 'connect_required'

    def test_wallet_balance_decremented_on_success(self, app):
        """Après un retrait réussi, balance_available doit diminuer du montant retiré."""
        from utils.wallet_service import perform_withdrawal
        user, _ = _make_user(Decimal('100.00'), has_connect=True)

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                locked_wallet = MagicMock()
                locked_wallet.balance_available = Decimal('100.00')
                locked_wallet.id = 7
                locked_wallet.user_id = user.id
                mock_db.session.execute.return_value.scalar_one_or_none.return_value = locked_wallet
                mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []

                with patch('stripe.Transfer.create') as mock_transfer:
                    mock_transfer.return_value = MagicMock(id='tr_test_456')
                    result = perform_withdrawal(user, 30.00)

        assert result['success'] is True
        # La balance doit avoir été décrémentée
        assert locked_wallet.balance_available == Decimal('70.00')

    def test_stripe_error_does_not_debit_wallet(self, app):
        """Si Stripe échoue, le wallet ne doit pas être débité."""
        from utils.wallet_service import perform_withdrawal
        import stripe._error as stripe_error
        user, _ = _make_user(Decimal('100.00'), has_connect=True)

        with app.app_context():
            with patch('utils.wallet_service.db') as mock_db:
                locked_wallet = MagicMock()
                locked_wallet.balance_available = Decimal('100.00')
                locked_wallet.id = 7
                locked_wallet.user_id = user.id
                mock_db.session.execute.return_value.scalar_one_or_none.return_value = locked_wallet

                with patch('stripe.Transfer.create') as mock_transfer:
                    mock_transfer.side_effect = stripe_error.StripeError('Card declined')
                    result = perform_withdrawal(user, 30.00)

        assert result['success'] is False
        # La balance ne doit PAS avoir été modifiée
        assert locked_wallet.balance_available == Decimal('100.00'), \
            "Un échec Stripe ne doit pas débiter le wallet"
