"""
Tests d'intégration — routes/stripe_connect_api.py

Les appels Stripe réels (create_connect_account, create_account_link,
create_dashboard_link, check_account_status) sont systématiquement mockés.

Convention de mock :
  - create_account_link  retourne une URL string (plus de dict)
  - create_dashboard_link retourne une URL string
  - check_account_status retourne un dict {onboarding_complete, status, ...}
"""

import json
import uuid

import pytest
import stripe._error as stripe_error


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

    def test_returns_null_when_no_account(self, client, auth_headers, user):
        """Sans compte Stripe, stripe_account_id est None."""
        assert user.stripe_account_id is None
        resp = client.get('/api/stripe-connect/status', headers=auth_headers)
        assert resp.status_code == 200
        assert json.loads(resp.data)['data']['stripe_account_id'] is None


# ── POST /api/stripe-connect/setup-url ────────────────────────────────────────

class TestGetSetupUrl:

    def test_requires_authentication(self, client):
        resp = client.post('/api/stripe-connect/setup-url', json={})
        assert resp.status_code == 401

    def test_non_beatmaker_is_forbidden(self, client, admin_headers):
        """Un utilisateur sans rôle beatmaker/mix_engineer reçoit 403."""
        resp = client.post('/api/stripe-connect/setup-url', headers=admin_headers, json={})
        assert resp.status_code == 403
        assert json.loads(resp.data)['code'] == 'FORBIDDEN'

    def test_beatmaker_without_account_creates_account_then_returns_url(
        self, client, auth_headers, mocker
    ):
        """
        Beatmaker sans stripe_account_id : create_connect_account est appelé,
        puis create_account_link retourne une URL string.
        """
        mocker.patch(
            'routes.stripe_connect_api.create_connect_account',
            return_value={'success': True},
        )
        mocker.patch(
            'routes.stripe_connect_api.create_account_link',
            return_value='https://connect.stripe.com/onboarding/test',
        )
        resp = client.post('/api/stripe-connect/setup-url', headers=auth_headers, json={})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['data']['url'] == 'https://connect.stripe.com/onboarding/test'

    def test_beatmaker_gets_onboarding_url(self, client, auth_headers, mocker):
        """Alias rétrocompatible — vérifie que 'url' est présent dans data."""
        mocker.patch(
            'routes.stripe_connect_api.create_connect_account',
            return_value={'success': True},
        )
        mocker.patch(
            'routes.stripe_connect_api.create_account_link',
            return_value='https://connect.stripe.com/onboarding/test',
        )
        resp = client.post('/api/stripe-connect/setup-url', headers=auth_headers, json={})
        assert resp.status_code == 200
        assert 'url' in json.loads(resp.data)['data']

    def test_beatmaker_with_existing_account_skips_create(
        self, client, db, user, auth_headers, mocker
    ):
        """Si stripe_account_id existe déjà, create_connect_account n'est PAS appelé."""
        user.stripe_account_id = 'acct_existing'
        db.session.commit()

        mock_create = mocker.patch('routes.stripe_connect_api.create_connect_account')
        mocker.patch(
            'routes.stripe_connect_api.create_account_link',
            return_value='https://connect.stripe.com/onboarding/existing',
        )

        resp = client.post('/api/stripe-connect/setup-url', headers=auth_headers, json={})

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 200
        mock_create.assert_not_called()

    def test_create_account_fails_returns_500(self, client, auth_headers, mocker):
        """Si create_connect_account échoue, la route retourne 500."""
        mocker.patch(
            'routes.stripe_connect_api.create_connect_account',
            return_value={'success': False, 'message': 'Stripe indisponible'},
        )
        resp = client.post('/api/stripe-connect/setup-url', headers=auth_headers, json={})
        assert resp.status_code == 500
        assert json.loads(resp.data)['code'] == 'STRIPE_ERROR'

    def test_create_account_link_raises_returns_500(self, client, auth_headers, mocker):
        """Si create_account_link lève une StripeError, la route retourne 500."""
        mocker.patch(
            'routes.stripe_connect_api.create_connect_account',
            return_value={'success': True},
        )
        mocker.patch(
            'routes.stripe_connect_api.create_account_link',
            side_effect=stripe_error.StripeError('Stripe API unreachable'),
        )
        resp = client.post('/api/stripe-connect/setup-url', headers=auth_headers, json={})
        assert resp.status_code == 500
        assert json.loads(resp.data)['code'] == 'STRIPE_ERROR'

    def test_custom_return_url_is_forwarded(self, client, auth_headers, mocker):
        """Le return_url passé dans le body est transmis à create_account_link."""
        mocker.patch(
            'routes.stripe_connect_api.create_connect_account',
            return_value={'success': True},
        )
        mock_link = mocker.patch(
            'routes.stripe_connect_api.create_account_link',
            return_value='https://connect.stripe.com/custom',
        )
        client.post(
            '/api/stripe-connect/setup-url',
            headers=auth_headers,
            json={'return_url': 'https://laprod.net/custom-return'},
        )
        _, kwargs = mock_link.call_args
        assert kwargs.get('return_url') == 'https://laprod.net/custom-return'


# ── POST /api/stripe-connect/dashboard-url ────────────────────────────────────

class TestGetDashboardUrl:

    def test_requires_authentication(self, client):
        resp = client.post('/api/stripe-connect/dashboard-url')
        assert resp.status_code == 401

    def test_returns_404_when_no_account(self, client, auth_headers, user):
        """Sans stripe_account_id, la route retourne 404."""
        assert user.stripe_account_id is None
        resp = client.post('/api/stripe-connect/dashboard-url', headers=auth_headers)
        assert resp.status_code == 404
        assert json.loads(resp.data)['code'] == 'NOT_FOUND'

    def test_returns_dashboard_url_when_account_exists(
        self, client, db, user, auth_headers, mocker
    ):
        """Avec un stripe_account_id, on obtient une URL de dashboard Stripe."""
        user.stripe_account_id = 'acct_test_dashboard123'
        db.session.commit()

        mocker.patch(
            'routes.stripe_connect_api.create_dashboard_link',
            return_value='https://dashboard.stripe.com/test',
        )

        resp = client.post('/api/stripe-connect/dashboard-url', headers=auth_headers)

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['data']['url'] == 'https://dashboard.stripe.com/test'

    def test_stripe_error_returns_500(self, client, db, user, auth_headers, mocker):
        """Si Stripe lève une exception, la route retourne 500."""
        user.stripe_account_id = 'acct_error_test'
        db.session.commit()

        mocker.patch(
            'routes.stripe_connect_api.create_dashboard_link',
            side_effect=stripe_error.StripeError('Network error'),
        )

        resp = client.post('/api/stripe-connect/dashboard-url', headers=auth_headers)

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 500
        assert json.loads(resp.data)['code'] == 'STRIPE_ERROR'


# ── POST /api/stripe-connect/refresh ──────────────────────────────────────────

class TestRefreshStatus:

    def test_requires_authentication(self, client):
        resp = client.post('/api/stripe-connect/refresh')
        assert resp.status_code == 401

    def test_returns_404_when_no_account(self, client, auth_headers, user):
        """Sans stripe_account_id, la route retourne 404."""
        assert user.stripe_account_id is None
        resp = client.post('/api/stripe-connect/refresh', headers=auth_headers)
        assert resp.status_code == 404

    def test_active_account_sets_onboarding_complete(
        self, client, db, user, auth_headers, mocker
    ):
        """Un compte actif (charges + payouts enabled) met onboarding_complete à True."""
        user.stripe_account_id = 'acct_active'
        db.session.commit()

        mocker.patch(
            'routes.stripe_connect_api.check_account_status',
            return_value={
                'onboarding_complete': True,
                'status':              'active',
                'charges_enabled':     True,
                'payouts_enabled':     True,
                'details_submitted':   True,
            },
        )

        resp = client.post('/api/stripe-connect/refresh', headers=auth_headers)

        user_after = db.session.get(type(user), user.id)
        onboarding = user_after.stripe_onboarding_complete
        status_val = user_after.stripe_account_status

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 200
        body = json.loads(resp.data)['data']
        assert body['stripe_onboarding_complete'] is True
        assert body['stripe_account_status'] == 'active'
        assert onboarding is True
        assert status_val == 'active'

    def test_pending_account_sets_onboarding_incomplete(
        self, client, db, user, auth_headers, mocker
    ):
        """Un compte en attente met onboarding_complete à False."""
        user.stripe_account_id = 'acct_pending'
        db.session.commit()

        mocker.patch(
            'routes.stripe_connect_api.check_account_status',
            return_value={
                'onboarding_complete': False,
                'status':              'pending',
                'charges_enabled':     False,
                'payouts_enabled':     False,
                'details_submitted':   False,
            },
        )

        resp = client.post('/api/stripe-connect/refresh', headers=auth_headers)

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 200
        body = json.loads(resp.data)['data']
        assert body['stripe_onboarding_complete'] is False
        assert body['stripe_account_status'] == 'pending'

    def test_stripe_error_returns_500(self, client, db, user, auth_headers, mocker):
        """Si check_account_status lève une StripeError, la route retourne 500."""
        user.stripe_account_id = 'acct_err'
        db.session.commit()

        mocker.patch(
            'routes.stripe_connect_api.check_account_status',
            side_effect=stripe_error.StripeError('API timeout'),
        )

        resp = client.post('/api/stripe-connect/refresh', headers=auth_headers)

        user.stripe_account_id = None
        db.session.commit()

        assert resp.status_code == 500
        assert json.loads(resp.data)['code'] == 'STRIPE_ERROR'
