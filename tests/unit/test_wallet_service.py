"""
Tests unitaires — utils/wallet_service.py

Stratégie : `db.session` est mocké entièrement → aucune DB requise.
On teste la logique métier pure : montants, commissions, règles de validation.
"""

import pytest
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

    @pytest.mark.parametrize('amount', [
        Decimal('45.00'),
        Decimal('21.30'),
        Decimal('100.47'),
    ])
    def test_amount_equals_composer_revenue(self, mocker, amount):
        """Le montant crédité doit correspondre exactement au composer_revenue."""
        mock_db = mocker.patch('utils.wallet_service.db')
        mocker.patch('models.WalletTransaction', autospec=False)

        wallet = _make_wallet()
        composer = MagicMock()
        composer.get_or_create_wallet.return_value = wallet

        purchase = MagicMock()
        purchase.composer_revenue = amount
        purchase.track.title = 'Test Beat'
        purchase.track.composer_user = composer
        purchase.format_purchased = 'wav'
        purchase.id = 42

        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)

        assert wallet.balance_pending == amount
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

    @pytest.mark.parametrize('initial,credit,expected_total', [
        (Decimal('0.00'),  Decimal('45.00'),  Decimal('45.00')),
        (Decimal('10.00'), Decimal('21.30'),  Decimal('31.30')),
        (Decimal('50.00'), Decimal('100.47'), Decimal('150.47')),
    ])
    def test_cumulates_with_existing_balance(self, mocker, initial, credit, expected_total):
        """Le solde existant ne doit pas être écrasé mais augmenté."""
        mocker.patch('utils.wallet_service.db')
        mocker.patch('models.WalletTransaction')

        wallet = _make_wallet(balance_pending=initial)
        composer = MagicMock()
        composer.get_or_create_wallet.return_value = wallet

        purchase = MagicMock()
        purchase.composer_revenue = credit
        purchase.track.composer_user = composer
        purchase.format_purchased = 'wav'
        purchase.id = 5

        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(purchase)

        assert wallet.balance_pending == expected_total


# ── credit_wallet_for_mixmaster_deposit ───────────────────────────────────────

class TestCreditWalletForMixmasterDeposit:

    @pytest.mark.parametrize('deposit,expected_net', [
        (Decimal('100.00'), Decimal('90.00')),   # montant rond
        (Decimal('45.00'),  Decimal('40.50')),   # demi-entier : 45 × 0.9 = 40.50
        (Decimal('21.30'),  Decimal('19.17')),   # décimales exactes : 21.30 × 0.9 = 19.17
        (Decimal('100.47'), Decimal('90.42')),   # arrondi requis : 100.47 × 0.9 = 90.423 → 90.42
    ])
    def test_commission_10_percent(self, mocker, deposit, expected_net):
        """L'engineer reçoit 90% du dépôt (commission LaProd = 10%)."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet

        request = MagicMock()
        request.deposit_amount = deposit
        request.engineer = engineer
        request.id = 7

        from utils.wallet_service import credit_wallet_for_mixmaster_deposit
        credit_wallet_for_mixmaster_deposit(request)

        kwargs = txn_cls.call_args[1]
        assert kwargs['amount'] == expected_net
        assert wallet.balance_pending == expected_net

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
    """
    Après le fix with_for_update(), perform_withdrawal() charge le wallet via
    db.session.execute(select(Wallet).where(...).with_for_update()).scalar_one_or_none()
    et non plus via user.wallet. Les mocks doivent configurer ce chemin.
    """

    def _setup_locked_wallet(self, mock_db, balance: Decimal) -> MagicMock:
        """Configure mock_db pour retourner un wallet locké avec le solde donné."""
        locked = _make_wallet(balance_available=balance)
        mock_db.session.execute.return_value.scalar_one_or_none.return_value = locked
        return locked

    def test_rejects_amount_below_minimum(self, mocker):
        """Retrait < 10€ doit être refusé avant tout accès DB."""
        mock_db = mocker.patch('utils.wallet_service.db')
        user = _make_user()

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('5.00'))

        assert result['success'] is False
        assert '10' in result['error']
        # La DB ne doit pas être consultée pour un montant sous le minimum
        mock_db.session.execute.assert_not_called()

    def test_rejects_insufficient_balance(self, mocker):
        """Retrait supérieur au solde disponible doit être refusé."""
        mock_db = mocker.patch('utils.wallet_service.db')
        self._setup_locked_wallet(mock_db, Decimal('20.00'))
        user = _make_user(stripe_account_id='acct_test')
        user.id = 1

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert 'insuffisant' in result['error'].lower()

    def test_rejects_no_stripe_connect(self, mocker):
        """Retrait sans compte Stripe Connect doit retourner 'connect_required'."""
        mock_db = mocker.patch('utils.wallet_service.db')
        self._setup_locked_wallet(mock_db, Decimal('100.00'))
        user = _make_user(stripe_account_id=None)
        user.id = 1

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert result['error'] == 'connect_required'

    def test_rejects_incomplete_onboarding(self, mocker):
        """Retrait sans onboarding Stripe complet doit retourner 'connect_incomplete'."""
        mock_db = mocker.patch('utils.wallet_service.db')
        self._setup_locked_wallet(mock_db, Decimal('100.00'))
        user = _make_user(
            stripe_account_id='acct_test123',
            onboarding_complete=False,
            account_status='pending',
        )
        user.id = 1

        from utils.wallet_service import perform_withdrawal
        result = perform_withdrawal(user, Decimal('50.00'))

        assert result['success'] is False
        assert result['error'] == 'connect_incomplete'

    def test_successful_withdrawal(self, mocker):
        """Retrait valide doit créer un Transfer Stripe et retourner success=True."""
        mock_db = mocker.patch('utils.wallet_service.db')
        locked_wallet = self._setup_locked_wallet(mock_db, Decimal('80.00'))

        mock_transfer = MagicMock()
        mock_transfer.id = 'tr_test_abc123'
        mocker.patch('stripe.Transfer.create', return_value=mock_transfer)
        mocker.patch('models.WalletTransaction')

        mock_txn = MagicMock()
        mock_txn.amount = Decimal('80.00')
        mock_txn.status = 'available'
        mock_db.session.query.return_value.filter.return_value.order_by.return_value.all.return_value = [mock_txn]

        user = _make_user(
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
        # Le wallet locké doit avoir été débité
        assert locked_wallet.balance_available == Decimal('30.00')

    def test_stripe_error_returns_failure(self, mocker):
        """Une erreur Stripe ne doit pas modifier le wallet et retourner success=False."""
        mock_db = mocker.patch('utils.wallet_service.db')
        locked_wallet = self._setup_locked_wallet(mock_db, Decimal('100.00'))

        from stripe._error import StripeError
        mocker.patch('stripe.Transfer.create', side_effect=StripeError('Stripe down'))

        user = _make_user(
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
        # Le wallet ne doit PAS avoir été modifié
        assert locked_wallet.balance_available == Decimal('100.00')


# ── process_pending_to_available ──────────────────────────────────────────────

class TestProcessPendingToAvailable:
    # WalletTransaction n'est PAS patché ici : la classe SQLAlchemy réelle doit être
    # utilisée car `WalletTransaction.available_at <= now` construit une expression
    # de colonne SQLAlchemy. Patcher la classe avec un MagicMock casserait cet opérateur.
    # Le mock_db.session.query ignore ses arguments, donc la vraie classe fonctionne bien.

    def test_only_processes_transactions_past_available_at(self, mocker):
        """Les transactions retournées par la DB (available_at <= now) passent à 'available'."""
        mock_db = mocker.patch('utils.wallet_service.db')

        wallet = _make_wallet(balance_pending=Decimal('30.00'), balance_available=Decimal('0'))

        ready_txn = MagicMock()
        ready_txn.amount = Decimal('30.00')
        ready_txn.status = 'pending'
        mock_db.session.query.return_value.filter.return_value.all.return_value = [ready_txn]

        from utils.wallet_service import process_pending_to_available
        process_pending_to_available(wallet)

        assert ready_txn.status == 'available'

    @pytest.mark.parametrize('txn_amounts,init_pending,init_avail,exp_avail', [
        # deux transactions, solde available existant
        ([Decimal('20.00'), Decimal('30.00')], Decimal('50.00'), Decimal('10.00'), Decimal('60.00')),
        # transaction unique décimale
        ([Decimal('45.00')],                   Decimal('45.00'), Decimal('0.00'),  Decimal('45.00')),
        # deux transactions irrégulières, cumul exact
        ([Decimal('21.30'), Decimal('100.47')], Decimal('121.77'), Decimal('10.00'), Decimal('131.77')),
    ])
    def test_moves_amount_from_pending_to_available(
        self, mocker, txn_amounts, init_pending, init_avail, exp_avail
    ):
        """Le montant total passe de balance_pending à balance_available."""
        mock_db = mocker.patch('utils.wallet_service.db')

        wallet = _make_wallet(balance_pending=init_pending, balance_available=init_avail)
        txns = [MagicMock(amount=a) for a in txn_amounts]
        mock_db.session.query.return_value.filter.return_value.all.return_value = txns

        from utils.wallet_service import process_pending_to_available
        process_pending_to_available(wallet)

        assert wallet.balance_pending == Decimal('0.00')
        assert wallet.balance_available == exp_avail

    def test_returns_count_of_processed_transactions(self, mocker):
        """La valeur de retour est le nombre de transactions transitionées."""
        mock_db = mocker.patch('utils.wallet_service.db')

        wallet = _make_wallet(balance_pending=Decimal('60.00'))
        txns = [MagicMock(amount=Decimal('20.00')) for _ in range(3)]
        mock_db.session.query.return_value.filter.return_value.all.return_value = txns

        from utils.wallet_service import process_pending_to_available
        count = process_pending_to_available(wallet)

        assert count == 3


# ── process_expirations ───────────────────────────────────────────────────────

class TestProcessExpirations:

    @pytest.mark.parametrize('amount', [
        Decimal('40.00'),
        Decimal('21.30'),
        Decimal('100.47'),
    ])
    def test_expires_old_pending_transactions(self, mocker, amount):
        """Les transactions 'pending' > 2 ans passent en 'expired' et déduisent balance_pending."""
        mock_db = mocker.patch('utils.wallet_service.db')

        wallet = _make_wallet(balance_pending=amount)

        old_txn = MagicMock()
        old_txn.amount = amount
        old_txn.status = 'pending'
        mock_db.session.query.return_value.filter.return_value.all.return_value = [old_txn]

        from utils.wallet_service import process_expirations
        process_expirations(wallet)

        assert old_txn.status == 'expired'
        assert wallet.balance_pending == Decimal('0.00')

    @pytest.mark.parametrize('amount', [
        Decimal('25.00'),
        Decimal('21.30'),
        Decimal('100.47'),
    ])
    def test_expires_old_available_transactions(self, mocker, amount):
        """Les transactions 'available' > 2 ans passent en 'expired' et déduisent balance_available."""
        mock_db = mocker.patch('utils.wallet_service.db')

        wallet = _make_wallet(balance_available=amount)

        old_txn = MagicMock()
        old_txn.amount = amount
        old_txn.status = 'available'
        mock_db.session.query.return_value.filter.return_value.all.return_value = [old_txn]

        from utils.wallet_service import process_expirations
        process_expirations(wallet)

        assert old_txn.status == 'expired'
        assert wallet.balance_available == Decimal('0.00')

    def test_recent_transactions_not_expired(self, mocker):
        """Les transactions récentes (< 2 ans) ne sont pas touchées (DB retourne liste vide)."""
        mock_db = mocker.patch('utils.wallet_service.db')

        wallet = _make_wallet(balance_pending=Decimal('15.00'))
        mock_db.session.query.return_value.filter.return_value.all.return_value = []

        from utils.wallet_service import process_expirations
        count = process_expirations(wallet)

        assert count == 0
        assert wallet.balance_pending == Decimal('15.00')


# ── credit_wallet_for_mixmaster_revision ──────────────────────────────────────

class TestCreditWalletForMixmasterRevision:

    def test_type_is_credit_mixmaster_revision(self, mocker):
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet
        request = MagicMock()
        request.engineer = engineer
        request.get_revision_transfer_amount.return_value = Decimal('9.00')
        request.revision_count = 1
        request.id = 1

        from utils.wallet_service import credit_wallet_for_mixmaster_revision
        credit_wallet_for_mixmaster_revision(request)

        assert txn_cls.call_args[1]['type'] == 'credit_mixmaster_revision'

    def test_amount_from_get_revision_transfer_amount(self, mocker):
        """Le montant correspond à ce que retourne get_revision_transfer_amount()."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet
        request = MagicMock()
        request.engineer = engineer
        request.get_revision_transfer_amount.return_value = Decimal('13.50')
        request.revision_count = 2
        request.id = 2

        from utils.wallet_service import credit_wallet_for_mixmaster_revision
        credit_wallet_for_mixmaster_revision(request)

        assert txn_cls.call_args[1]['amount'] == Decimal('13.50')
        assert wallet.balance_pending == Decimal('13.50')


# ── credit_wallet_for_mixmaster_final ─────────────────────────────────────────

class TestCreditWalletForMixmasterFinal:

    def test_type_is_credit_mixmaster_final(self, mocker):
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet
        request = MagicMock()
        request.engineer = engineer
        request.get_final_transfer_amount.return_value = Decimal('63.00')
        request.id = 3

        from utils.wallet_service import credit_wallet_for_mixmaster_final
        credit_wallet_for_mixmaster_final(request)

        assert txn_cls.call_args[1]['type'] == 'credit_mixmaster_final'

    def test_amount_from_get_final_transfer_amount(self, mocker):
        """Le montant correspond à ce que retourne get_final_transfer_amount()."""
        mocker.patch('utils.wallet_service.db')
        txn_cls = mocker.patch('models.WalletTransaction')

        wallet = _make_wallet()
        engineer = MagicMock()
        engineer.get_or_create_wallet.return_value = wallet
        request = MagicMock()
        request.engineer = engineer
        request.get_final_transfer_amount.return_value = Decimal('54.00')
        request.id = 4

        from utils.wallet_service import credit_wallet_for_mixmaster_final
        credit_wallet_for_mixmaster_final(request)

        assert txn_cls.call_args[1]['amount'] == Decimal('54.00')
        assert wallet.balance_pending == Decimal('54.00')
