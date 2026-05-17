"""
Tests unitaires — utils/wallet_service.py

Stratégie : `db.session` est mocké entièrement → aucune DB requise.
On teste la logique métier pure : montants, commissions, règles de validation.
"""

from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch


# ── Helpers de construction de mocks ──────────────────────────────────────────

def _make_wallet(balance_pending=Decimal('0'), balance_available=Decimal('0'), wallet_id=1):
    w = MagicMock()
    w.id = wallet_id
    w.balance_pending = balance_pending
    w.balance_available = balance_available
    return w


def _make_user(wallet=None, stripe_account_id=None, onboarding_complete=False, account_status='active'):
    u = MagicMock()
    u.wallet = wallet
    u.stripe_account_id = stripe_account_id
    u.stripe_onboarding_complete = onboarding_complete
    u.stripe_account_status = account_status
    return u


# ── credit_wallet_for_beat_sale ────────────────────────────────────────────────

class TestCreditWalletForBeatSale:

    def test_amount_equals_composer_revenue(self, mocker):
        """Le montant crédité doit correspondre exactement au composer_revenue."""
        mock_db = mocker.patch('utils.wallet_service.db')
        mocker.patch('models.WalletTransaction', autospec=False)

        wallet = _make_wallet()
        composer = MagicMock()
        composer.get_or_create_wallet.return_value = wallet

        purchase = MagicMock()
        purchase.composer_revenue = Decimal('45.00')
        purchase.track.title = 'Test Beat'
        purchase.track.composer_user = composer
        purchase.format_purchased = 'wav'
        purchase.id = 42

        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)

        assert wallet.balance_pending == Decimal('45.00')
        mock_db.session.add.assert_called_once()

    def test_transaction_status_is_pending(self, mocker):
        """La transaction doit être créée en statut 'pending'."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        composer = MagicMock()
        composer.get_or_create_wallet.return_value = wallet

        purchase = MagicMock()
        purchase.composer_revenue = Decimal('10.00')
        purchase.track.composer_user = composer
        purchase.format_purchased = 'mp3'
        purchase.id = 1

        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)

        kwargs = txn_cls.call_args[1]
        assert kwargs['status'] == 'pending'
        assert kwargs['type'] == 'credit_beat_sale'

    def test_available_at_is_7_days_from_now(self, mocker):
        """Les fonds ne doivent être disponibles qu'après 7 jours."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        composer = MagicMock()
        composer.get_or_create_wallet.return_value = wallet

        purchase = MagicMock()
        purchase.composer_revenue = Decimal('20.00')
        purchase.track.composer_user = composer
        purchase.format_purchased = 'mp3'
        purchase.id = 1

        before = datetime.now()
        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)
        after = datetime.now()

        available_at = txn_cls.call_args[1]['available_at']
        expected_min = before + timedelta(days=7)
        expected_max = after + timedelta(days=7)
        assert expected_min <= available_at <= expected_max

    def test_cumulates_with_existing_balance(self, mocker):
        """Le solde existant ne doit pas être écrasé mais augmenté."""
        mocker.patch('utils.wallet_service.db')
        mocker.patch('models.WalletTransaction')

        wallet = _make_wallet(balance_pending=Decimal('30.00'))
        composer = MagicMock()
        composer.get_or_create_wallet.return_value = wallet

        purchase = MagicMock()
        purchase.composer_revenue = Decimal('15.00')
        purchase.track.composer_user = composer
        purchase.format_purchased = 'wav'
        purchase.id = 5

        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)

        assert wallet.balance_pending == Decimal('45.00')


# ── credit_wallet_for_mixmaster_deposit ───────────────────────────────────────

class TestCreditWalletForMixmasterDeposit:

    def test_commission_10_percent(self, mocker):
        """L'engineer reçoit 90% du dépôt (commission LaProd = 10%)."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet

        request = MagicMock()
        request.deposit_amount = Decimal('100.00')
        request.engineer = engineer
        request.id = 7

        from utils.wallet_service import credit_wallet_for_mixmaster_deposit
        credit_wallet_for_mixmaster_deposit(request)

        kwargs = txn_cls.call_args[1]
        assert kwargs['amount'] == Decimal('90.00')
        assert wallet.balance_pending == Decimal('90.00')

    def test_commission_on_non_round_amount(self, mocker):
        """La commission doit être calculée avec arrondi à 2 décimales."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet

        request = MagicMock()
        request.deposit_amount = Decimal('333.33')
        request.engineer = engineer
        request.id = 8

        from utils.wallet_service import credit_wallet_for_mixmaster_deposit
        credit_wallet_for_mixmaster_deposit(request)

        # 333.33 * 0.90 = 299.997 → arrondi à 300.00
        kwargs = txn_cls.call_args[1]
        assert kwargs['amount'] == Decimal('300.00')

    def test_transaction_type(self, mocker):
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet
        request = MagicMock()
        request.deposit_amount = Decimal('50.00')
        request.engineer = engineer
        request.id = 1

        from utils.wallet_service import credit_wallet_for_mixmaster_deposit
        credit_wallet_for_mixmaster_deposit(request)

        assert txn_cls.call_args[1]['type'] == 'credit_mixmaster_deposit'


# ── perform_withdrawal ────────────────────────────────────────────────────────

class TestPerformWithdrawal:

    def test_rejects_amount_below_minimum(self, mocker):
        """Retrait < 10€ doit être refusé avec un message clair."""
        mocker.patch('utils.wallet_service.db')
        user = _make_user()

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('5.00'))

        assert result['success'] is False
        assert '10' in result['error']

    def test_rejects_insufficient_balance(self, mocker):
        """Retrait supérieur au solde disponible doit être refusé."""
        mocker.patch('utils.wallet_service.db')
        wallet = _make_wallet(balance_available=Decimal('20.00'))
        user = _make_user(wallet=wallet)

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert 'insuffisant' in result['error'].lower()

    def test_rejects_no_stripe_connect(self, mocker):
        """Retrait sans compte Stripe Connect doit retourner 'connect_required'."""
        mocker.patch('utils.wallet_service.db')
        wallet = _make_wallet(balance_available=Decimal('100.00'))
        user = _make_user(wallet=wallet, stripe_account_id=None)

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert result['error'] == 'connect_required'

    def test_rejects_incomplete_onboarding(self, mocker):
        """Retrait sans onboarding Stripe complet doit retourner 'connect_incomplete'."""
        mocker.patch('utils.wallet_service.db')
        wallet = _make_wallet(balance_available=Decimal('100.00'))
        user = _make_user(
            wallet=wallet,
            stripe_account_id='acct_test123',
            onboarding_complete=False,
            account_status='pending',
        )

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert result['error'] == 'connect_incomplete'

    def test_successful_withdrawal(self, mocker):
        """Retrait valide doit créer un Transfer Stripe et retourner success=True."""
        mock_db = mocker.patch('utils.wallet_service.db')

        # stripe est importé en lazy dans perform_withdrawal → on patch le module directement
        mock_transfer = MagicMock()
        mock_transfer.id = 'tr_test_abc123'
        mocker.patch('stripe.Transfer.create', return_value=mock_transfer)

        # WalletTransaction (importé depuis models à l'intérieur de la fonction)
        mocker.patch('models.WalletTransaction')

        # Simuler une transaction disponible en DB
        mock_txn = MagicMock()
        mock_txn.amount = Decimal('80.00')
        mock_txn.status = 'available'
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_txn]

        wallet = _make_wallet(balance_available=Decimal('80.00'))
        user = _make_user(
            wallet=wallet,
            stripe_account_id='acct_test123',
            onboarding_complete=True,
            account_status='active',
        )
        user.id = 1
        user.username = 'test'

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is True
        assert result['transfer_id'] == 'tr_test_abc123'
        assert result['amount'] == 50.0

    def test_stripe_error_returns_failure(self, mocker):
        """Une erreur Stripe doit retourner success=False sans lever d'exception."""
        mocker.patch('utils.wallet_service.db')

        from stripe._error import StripeError
        mocker.patch('stripe.Transfer.create', side_effect=StripeError('Stripe down'))

        wallet = _make_wallet(balance_available=Decimal('100.00'))
        user = _make_user(
            wallet=wallet,
            stripe_account_id='acct_test123',
            onboarding_complete=True,
            account_status='active',
        )
        user.id = 1
        user.username = 'test'

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert 'Stripe down' in result['error']
