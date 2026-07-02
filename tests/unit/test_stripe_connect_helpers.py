"""
Tests unitaires — stripe_connect_helpers.py

Chaque helper est testé en isolation avec les appels Stripe mockés.
Aucun accès base de données réel (sauf create_connect_account et
handle_webhook_account_updated qui écrivent en DB — on vérifie via
des mocks ou des assertions sur la session).
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import stripe._error as stripe_error


# ── create_connect_account ─────────────────────────────────────────────────────

class TestCreateConnectAccount:

    def test_success_saves_account_id_to_user(self, app, db):
        """En cas de succès, stripe_account_id est sauvegardé sur l'utilisateur."""
        from models import User
        from stripe_connect_helpers import create_connect_account
        import uuid

        uid = uuid.uuid4().hex[:8]
        user = User(
            email=f'connect_{uid}@test.laprod.fr',
            username=f'connect_{uid}',
            email_verified=True,
            account_status='active',
        )
        db.session.add(user)
        db.session.commit()

        mock_account = MagicMock()
        mock_account.id = 'acct_new_test_123'

        with patch('stripe.Account.create', return_value=mock_account):
            result = create_connect_account(user)

        assert result['success'] is True
        assert result['account_id'] == 'acct_new_test_123'
        fresh = db.session.get(User, user.id)
        assert fresh.stripe_account_id == 'acct_new_test_123'
        assert fresh.stripe_account_status == 'pending'

        db.session.delete(fresh)
        db.session.commit()

    def test_stripe_error_returns_failure_dict(self, app):
        """Si Stripe lève une erreur, le dict retourné a success=False."""
        from models import User
        from stripe_connect_helpers import create_connect_account

        user = MagicMock(spec=User)
        user.id       = 999
        user.email    = 'test@test.fr'
        user.username = 'testuser'

        with patch('stripe.Account.create', side_effect=stripe_error.StripeError('API error')):
            result = create_connect_account(user)

        assert result['success'] is False
        assert 'error' in result
        assert 'message' in result


# ── create_account_link ────────────────────────────────────────────────────────

class TestCreateAccountLink:

    def test_returns_url_string(self, app):
        """En cas de succès, create_account_link retourne une URL string."""
        from models import User
        from stripe_connect_helpers import create_account_link

        user = MagicMock(spec=User)
        user.stripe_account_id = 'acct_link_test'

        mock_link = MagicMock()
        mock_link.url = 'https://connect.stripe.com/onboarding/acct_link_test'

        with patch('stripe.AccountLink.create', return_value=mock_link):
            result = create_account_link(user, return_url='https://r.test', refresh_url='https://rf.test')

        assert result == 'https://connect.stripe.com/onboarding/acct_link_test'
        assert isinstance(result, str)

    def test_passes_correct_params_to_stripe(self, app):
        """Les paramètres account, return_url, refresh_url et type sont bien transmis."""
        from models import User
        from stripe_connect_helpers import create_account_link

        user = MagicMock(spec=User)
        user.stripe_account_id = 'acct_param_test'

        mock_link = MagicMock()
        mock_link.url = 'https://connect.stripe.com/x'

        with patch('stripe.AccountLink.create', return_value=mock_link) as mock_create:
            create_account_link(
                user,
                return_url='https://app.laprod.net/wallet',
                refresh_url='https://app.laprod.net/wallet',
            )

        mock_create.assert_called_once_with(
            account='acct_param_test',
            refresh_url='https://app.laprod.net/wallet',
            return_url='https://app.laprod.net/wallet',
            type='account_onboarding',
        )

    def test_stripe_error_propagates(self, app):
        """Une StripeError remonte sans être avalée."""
        from models import User
        from stripe_connect_helpers import create_account_link

        user = MagicMock(spec=User)
        user.stripe_account_id = 'acct_err'

        with patch('stripe.AccountLink.create', side_effect=stripe_error.StripeError('timeout')):
            with pytest.raises(stripe_error.StripeError):
                create_account_link(user, return_url='https://r', refresh_url='https://rf')


# ── check_account_status ───────────────────────────────────────────────────────

class TestCheckAccountStatus:

    def _make_account(self, charges=True, payouts=True, details=True):
        acc = MagicMock()
        acc.charges_enabled   = charges
        acc.payouts_enabled   = payouts
        acc.details_submitted = details
        return acc

    def test_active_account_returns_onboarding_complete(self, app):
        """Compte avec charges+payouts activés → onboarding_complete=True, status='active'."""
        from stripe_connect_helpers import check_account_status

        with patch('stripe.Account.retrieve', return_value=self._make_account()):
            result = check_account_status('acct_active')

        assert result['onboarding_complete'] is True
        assert result['status'] == 'active'
        assert result['charges_enabled'] is True
        assert result['payouts_enabled'] is True

    def test_pending_account_returns_onboarding_incomplete(self, app):
        """Compte avec charges/payouts désactivés → onboarding_complete=False, status='pending'."""
        from stripe_connect_helpers import check_account_status

        with patch(
            'stripe.Account.retrieve',
            return_value=self._make_account(charges=False, payouts=False, details=False),
        ):
            result = check_account_status('acct_pending')

        assert result['onboarding_complete'] is False
        assert result['status'] == 'pending'

    def test_partial_enabled_is_incomplete(self, app):
        """Seuls les charges activés mais pas les payouts → toujours incomplet."""
        from stripe_connect_helpers import check_account_status

        with patch(
            'stripe.Account.retrieve',
            return_value=self._make_account(charges=True, payouts=False),
        ):
            result = check_account_status('acct_partial')

        assert result['onboarding_complete'] is False
        assert result['status'] == 'pending'

    def test_does_not_write_to_db(self, app, db):
        """check_account_status ne doit pas modifier la base de données."""
        from stripe_connect_helpers import check_account_status

        # On patch db.session.commit pour détecter un appel inattendu
        with patch('stripe_connect_helpers.db.session') as mock_session:
            with patch('stripe.Account.retrieve', return_value=self._make_account()):
                check_account_status('acct_nowrite')

        mock_session.commit.assert_not_called()

    def test_stripe_error_propagates(self, app):
        """Une StripeError remonte sans être avalée."""
        from stripe_connect_helpers import check_account_status

        with patch('stripe.Account.retrieve', side_effect=stripe_error.AuthenticationError()):
            with pytest.raises(stripe_error.StripeError):
                check_account_status('acct_err')


# ── create_dashboard_link ──────────────────────────────────────────────────────

class TestCreateDashboardLink:

    def test_returns_url_string(self, app):
        """En cas de succès, retourne une URL string."""
        from stripe_connect_helpers import create_dashboard_link

        mock_link = MagicMock()
        mock_link.url = 'https://dashboard.stripe.com/express/acct_test'

        with patch('stripe.Account.create_login_link', return_value=mock_link):
            result = create_dashboard_link('acct_test')

        assert result == 'https://dashboard.stripe.com/express/acct_test'
        assert isinstance(result, str)

    def test_passes_account_id_to_stripe(self, app):
        """L'account_id est bien transmis à stripe.Account.create_login_link."""
        from stripe_connect_helpers import create_dashboard_link

        mock_link = MagicMock()
        mock_link.url = 'https://dashboard.stripe.com/x'

        with patch('stripe.Account.create_login_link', return_value=mock_link) as mock_create:
            create_dashboard_link('acct_param123')

        mock_create.assert_called_once_with('acct_param123')

    def test_stripe_error_propagates(self, app):
        """Une StripeError remonte sans être avalée."""
        from stripe_connect_helpers import create_dashboard_link

        with patch(
            'stripe.Account.create_login_link',
            side_effect=stripe_error.StripeError('rate limit'),
        ):
            with pytest.raises(stripe_error.StripeError):
                create_dashboard_link('acct_err')


# ── refund_payment ─────────────────────────────────────────────────────────────

class TestRefundPayment:

    def test_full_refund_returns_success_dict(self, app):
        """Un remboursement total retourne success=True avec les détails du refund."""
        from stripe_connect_helpers import refund_payment

        mock_refund = MagicMock()
        mock_refund.id     = 're_test_123'
        mock_refund.status = 'succeeded'
        mock_refund.amount = 999  # centimes

        with patch('stripe.Refund.create', return_value=mock_refund):
            result = refund_payment('pi_test_123')

        assert result['success'] is True
        assert result['refund_id'] == 're_test_123'
        assert result['amount'] == pytest.approx(9.99)

    def test_partial_refund_passes_amount_in_cents(self, app):
        """Un montant partiel est converti en centimes avant l'appel Stripe."""
        from stripe_connect_helpers import refund_payment

        mock_refund = MagicMock()
        mock_refund.id     = 're_partial'
        mock_refund.status = 'succeeded'
        mock_refund.amount = 500

        with patch('stripe.Refund.create', return_value=mock_refund) as mock_create:
            refund_payment('pi_partial', amount=5.00)

        _, kwargs = mock_create.call_args
        assert kwargs['amount'] == 500

    def test_stripe_error_returns_failure_dict(self, app):
        """Si Stripe échoue, le dict retourné a success=False."""
        from stripe_connect_helpers import refund_payment

        with patch('stripe.Refund.create', side_effect=stripe_error.StripeError('card error')):
            result = refund_payment('pi_err')

        assert result['success'] is False
        assert 'error' in result


# ── handle_webhook_account_updated ────────────────────────────────────────────

class TestHandleWebhookAccountUpdated:

    def test_updates_user_to_active_when_both_enabled(self, app, db):
        """Webhook account.updated avec charges+payouts → statut active."""
        from models import User
        from stripe_connect_helpers import handle_webhook_account_updated
        import uuid

        uid  = uuid.uuid4().hex[:8]
        user = User(
            email=f'webhook_{uid}@test.laprod.fr',
            username=f'webhook_{uid}',
            email_verified=True,
            account_status='active',
            stripe_account_id='acct_webhook_active',
        )
        db.session.add(user)
        db.session.commit()

        mock_account = MagicMock()
        mock_account.charges_enabled = True
        mock_account.payouts_enabled = True

        with patch('stripe.Account.retrieve', return_value=mock_account):
            handle_webhook_account_updated('acct_webhook_active')

        fresh = db.session.get(User, user.id)
        assert fresh.stripe_account_status      == 'active'
        assert fresh.stripe_onboarding_complete is True

        db.session.delete(fresh)
        db.session.commit()

    def test_updates_user_to_pending_when_not_fully_enabled(self, app, db):
        """Webhook avec payouts désactivés → statut pending."""
        from models import User
        from stripe_connect_helpers import handle_webhook_account_updated
        import uuid

        uid  = uuid.uuid4().hex[:8]
        user = User(
            email=f'webhook2_{uid}@test.laprod.fr',
            username=f'webhook2_{uid}',
            email_verified=True,
            account_status='active',
            stripe_account_id='acct_webhook_pending',
            stripe_onboarding_complete=True,
        )
        db.session.add(user)
        db.session.commit()

        mock_account = MagicMock()
        mock_account.charges_enabled = True
        mock_account.payouts_enabled = False

        with patch('stripe.Account.retrieve', return_value=mock_account):
            handle_webhook_account_updated('acct_webhook_pending')

        fresh = db.session.get(User, user.id)
        assert fresh.stripe_account_status      == 'pending'
        assert fresh.stripe_onboarding_complete is False

        db.session.delete(fresh)
        db.session.commit()

    def test_no_op_when_account_id_not_found(self, app, db):
        """Si aucun utilisateur ne correspond à l'account_id, pas d'erreur."""
        from stripe_connect_helpers import handle_webhook_account_updated

        mock_account = MagicMock()
        mock_account.charges_enabled = True
        mock_account.payouts_enabled = True

        # Ne doit pas lever d'exception
        with patch('stripe.Account.retrieve', return_value=mock_account):
            handle_webhook_account_updated('acct_unknown_xyz')
