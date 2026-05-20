"""
Tests d'intégration — routes/stripe_connect_api.py

Les appels Stripe réels (create_connect_account, create_account_link,
create_dashboard_link) sont systématiquement mockés.
"""

import json

import pytest


# ── GET /api/stripe-connect/status ────────────────────────────────────────────

class TestGetStatus:

    def test_requires_authentication(self, client):
        resp = client.get('/api/stripe-connect/status')
        assert resp.status_code == 401

    def test_returns_stripe_fields(self, client, auth_headers):
        resp = client.get('/api/stripe-connect/status', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)['data']
        assert 'stripe_account_id' in data
        assert 'stripe_onboarding_complete' in data
        assert 'stripe_account_status' in data


# ── POST /api/stripe-connect/setup-url ────────────────────────────────────────

class TestGetSetupUrl:

    def test_requires_authentication(self, client):
        resp = client.post('/api/stripe-connect/setup-url', json={})
        assert resp.status_code == 401

    def test_non_beatmaker_is_forbidden(self, client, admin_headers):
        """Un utilisateur sans rôle beatmaker/mix_engineer reçoit 403."""
        resp = client.post('/api/stripe-connect/setup-url', headers=admin_headers, json={})
        assert resp.status_code == 403

    def test_beatmaker_gets_onboarding_url(self, client, auth_headers, mocker):
        """Un beatmaker reçoit une URL d'onboarding Stripe (appels Stripe mockés)."""
        mocker.patch(
            'routes.stripe_connect_api.create_connect_account',
            return_value={'success': True},
        )
        mocker.patch(
            'routes.stripe_connect_api.create_account_link',
            return_value={'url': 'https://connect.stripe.com/onboarding/test'},
        )
        resp = client.post('/api/stripe-connect/setup-url', headers=auth_headers, json={})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'url' in data['data']


# ── POST /api/stripe-connect/dashboard-url ────────────────────────────────────

class TestGetDashboardUrl:

    def test_returns_404_when_no_account(self, client, auth_headers, user):
        """Sans stripe_account_id, la route retourne 404."""
        assert user.stripe_account_id is None
        resp = client.post('/api/stripe-connect/dashboard-url', headers=auth_headers)
        assert resp.status_code == 404

    def test_returns_dashboard_url_when_account_exists(self, client, db, user, auth_headers, mocker):
        """Avec un stripe_account_id, on obtient une URL de dashboard Stripe."""
        user.stripe_account_id = 'acct_test_dashboard123'
        db.session.commit()

        mocker.patch(
            'routes.stripe_connect_api.create_dashboard_link',
            return_value={'url': 'https://dashboard.stripe.com/test'},
        )

        resp = client.post('/api/stripe-connect/dashboard-url', headers=auth_headers)

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert 'url' in data['data']
