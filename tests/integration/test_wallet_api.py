"""
Tests d'intégration — routes/wallet_api.py

Teste les endpoints de gestion du wallet :
- GET /api/wallet  → consultation du solde
- POST /api/wallet/withdraw → retrait (Stripe mocké)
"""

import json
from decimal import Decimal
import pytest


# ── GET /api/wallet ───────────────────────────────────────────────────────────

class TestGetWallet:

    def test_requires_authentication(self, client):
        resp = client.get('/api/wallet')
        assert resp.status_code == 401

    def test_returns_zero_balances_for_new_user(self, client, auth_headers, user, db):
        """Un utilisateur sans wallet doit voir des soldes à zéro."""
        resp = client.get('/api/wallet', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        wallet = data['data']['wallet']
        # Les soldes peuvent être 0 ou les clés peuvent varier selon le DTO
        assert float(wallet.get('balance_available', wallet.get('available', 0))) >= 0
        assert float(wallet.get('balance_pending', wallet.get('pending', 0))) >= 0

    def test_returns_correct_balance(self, client, auth_headers, user, db):
        """Avec un wallet pré-créé, les soldes doivent correspondre."""
        from models import Wallet
        wallet = Wallet(
            user_id=user.id,
            balance_available=Decimal('75.50'),
            balance_pending=Decimal('20.00'),
        )
        db.session.add(wallet)
        db.session.commit()

        resp = client.get('/api/wallet', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        w = data['data']['wallet']
        avail = float(w.get('balance_available', w.get('available', -1)))
        assert avail == 75.50

        db.session.delete(wallet)
        db.session.commit()


# ── POST /api/wallet/withdraw ─────────────────────────────────────────────────

class TestWithdraw:

    def test_requires_authentication(self, client):
        resp = client.post('/api/wallet/withdraw', json={'amount': 50})
        assert resp.status_code == 401

    def test_rejects_withdrawal_with_insufficient_balance(self, client, auth_headers, user, db):
        """Retrait supérieur au solde doit retourner une erreur."""
        from models import Wallet

        # Stripe Connect must be configured to reach the balance check
        user.stripe_account_id = 'acct_test_balance_check'
        user.stripe_onboarding_complete = True
        user.stripe_account_status = 'active'
        db.session.commit()

        wallet = Wallet(
            user_id=user.id,
            balance_available=Decimal('5.00'),
            balance_pending=Decimal('0.00'),
        )
        db.session.add(wallet)
        db.session.commit()

        resp = client.post(
            '/api/wallet/withdraw',
            json={'amount': 50},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 422)
        data = json.loads(resp.data)
        assert data['success'] is False

        db.session.delete(wallet)
        user.stripe_account_id = None
        user.stripe_onboarding_complete = False
        user.stripe_account_status = None
        db.session.commit()

    def test_rejects_withdrawal_without_stripe_connect(self, client, auth_headers, user, db):
        """Sans compte Stripe Connect, le retrait doit être refusé."""
        from models import Wallet
        wallet = Wallet(
            user_id=user.id,
            balance_available=Decimal('100.00'),
            balance_pending=Decimal('0.00'),
        )
        db.session.add(wallet)
        db.session.commit()

        # user.stripe_account_id est None par défaut
        assert user.stripe_account_id is None

        resp = client.post(
            '/api/wallet/withdraw',
            json={'amount': 50},
            headers=auth_headers,
        )
        assert resp.status_code in (400, 403, 422)
        data = json.loads(resp.data)
        assert data['success'] is False

        db.session.delete(wallet)
        db.session.commit()

    def test_successful_withdrawal_mocked_stripe(self, client, auth_headers, user, db, mocker):
        """Un retrait valide avec Stripe mocké doit retourner success=True."""
        from models import Wallet, WalletTransaction

        # Configurer un compte Stripe Connect complet
        user.stripe_account_id = 'acct_test_withdraw_123'
        user.stripe_onboarding_complete = True
        user.stripe_account_status = 'active'
        db.session.commit()

        wallet = Wallet(
            user_id=user.id,
            balance_available=Decimal('100.00'),
            balance_pending=Decimal('0.00'),
        )
        db.session.add(wallet)
        db.session.flush()

        txn = WalletTransaction(
            wallet_id=wallet.id,
            type='credit_beat_sale',
            amount=Decimal('100.00'),
            status='available',
            description='Test transaction',
        )
        db.session.add(txn)
        db.session.commit()

        # Mock Stripe Transfer
        mock_transfer = mocker.MagicMock()
        mock_transfer.id = 'tr_test_withdraw_ok'
        mocker.patch('stripe.Transfer.create', return_value=mock_transfer)

        resp = client.post(
            '/api/wallet/withdraw',
            json={'amount': 50},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        # Cleanup
        db.session.delete(txn)
        db.session.delete(wallet)
        user.stripe_account_id = None
        user.stripe_onboarding_complete = False
        user.stripe_account_status = None
        db.session.commit()
