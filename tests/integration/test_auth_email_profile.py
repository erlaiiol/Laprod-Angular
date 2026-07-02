"""
Tests d'intégration — vérification email, renvoi, complétion OAuth, sélection de rôle.

Complète test_auth_api.py en testant les endpoints du flow post-inscription :
  POST /api/auth/verify-email
  POST /api/auth/resend-verification
  POST /api/auth/complete-oauth-profile
  POST /api/auth/select-role
"""

import json
import pytest


# ── Fixtures communes ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_refresh_token_store(mocker):
    mocker.patch('routes.auth_api.store_refresh_token', return_value=None)


@pytest.fixture()
def unverified_user(db):
    """Utilisateur inscrit mais email non vérifié (account_status = pending_completion)."""
    from models import User
    u = User(
        email='unverified@email-test.laprod.fr',
        username='unverified_email_user',
        email_verified=False,
        account_status='pending_completion',
        user_type_selected=True,
    )
    u.set_password('TestPassword123!')
    db.session.add(u)
    db.session.commit()
    yield u
    from models import Wallet
    w = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if w:
        db.session.delete(w)
        db.session.flush()
    db.session.delete(u)
    db.session.commit()


@pytest.fixture()
def pending_oauth_user(db):
    """Utilisateur créé via Google OAuth dont le profil n'est pas encore complété."""
    from models import User
    u = User(
        email='oauth@profile-test.laprod.fr',
        username=None,
        google_id='google-sub-profile-test',
        oauth_provider='google',
        email_verified=True,
        account_status='pending_completion',
        user_type_selected=False,
    )
    db.session.add(u)
    db.session.commit()
    yield u
    from models import Wallet
    w = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if w:
        db.session.delete(w)
        db.session.flush()
    db.session.delete(u)
    db.session.commit()


@pytest.fixture()
def pending_oauth_headers(app, pending_oauth_user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(pending_oauth_user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def no_role_user(db):
    """Utilisateur actif dont le rôle n'a pas encore été sélectionné."""
    from models import User
    u = User(
        email='norole@role-test.laprod.fr',
        username='no_role_user_test',
        email_verified=True,
        account_status='active',
        user_type_selected=False,
    )
    u.set_password('TestPassword123!')
    db.session.add(u)
    db.session.commit()
    yield u
    from models import Wallet
    w = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if w:
        db.session.delete(w)
        db.session.flush()
    db.session.delete(u)
    db.session.commit()


@pytest.fixture()
def no_role_headers(app, no_role_user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(no_role_user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


# ── POST /api/auth/verify-email ────────────────────────────────────────────────

class TestVerifyEmail:

    def test_missing_token_returns_error(self, client):
        resp = client.post('/api/auth/verify-email', json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_invalid_token_returns_error_with_code(self, client, mocker):
        mocker.patch('routes.auth_api.email_service.verify_email_token', return_value=None)
        resp = client.post('/api/auth/verify-email', json={'token': 'bad-token'})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['success'] is False
        assert data.get('code') == 'TOKEN_EXPIRED'

    def test_valid_token_sets_email_verified_and_activates_account(
        self, client, db, mocker, unverified_user
    ):
        mocker.patch(
            'routes.auth_api.email_service.verify_email_token',
            return_value=unverified_user.email,
        )
        resp = client.post('/api/auth/verify-email', json={'token': 'valid-token'})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        db.session.refresh(unverified_user)
        assert unverified_user.email_verified is True
        assert unverified_user.account_status == 'active'

    def test_already_verified_returns_already_verified_code(self, client, mocker, user):
        mocker.patch(
            'routes.auth_api.email_service.verify_email_token',
            return_value=user.email,
        )
        resp = client.post('/api/auth/verify-email', json={'token': 'any-token'})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        assert data.get('code') == 'ALREADY_VERIFIED'

    def test_token_for_unknown_email_returns_404(self, client, mocker):
        mocker.patch(
            'routes.auth_api.email_service.verify_email_token',
            return_value='nobody@nowhere.com',
        )
        resp = client.post('/api/auth/verify-email', json={'token': 'token-unknown'})
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert data['success'] is False


# ── POST /api/auth/resend-verification ────────────────────────────────────────

class TestResendVerification:

    def test_missing_identifier_returns_error(self, client):
        resp = client.post('/api/auth/resend-verification', json={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_unknown_email_returns_ambiguous_ok(self, client):
        resp = client.post(
            '/api/auth/resend-verification',
            json={'identifier': 'nobody@nowhere.com'},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

    def test_already_verified_user_returns_ambiguous_ok(self, client, user):
        """Même réponse que pour un inconnu — évite l'énumération d'emails."""
        resp = client.post(
            '/api/auth/resend-verification',
            json={'identifier': user.email},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

    def test_unverified_user_triggers_email_send(self, client, db, mocker, unverified_user):
        mock_send = mocker.patch(
            'routes.auth_api.email_service.send_verification_email',
            return_value=True,
        )
        resp = client.post(
            '/api/auth/resend-verification',
            json={'identifier': unverified_user.email},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        mock_send.assert_called_once_with(unverified_user)

    def test_accepts_username_as_identifier(self, client, mocker, unverified_user):
        mocker.patch(
            'routes.auth_api.email_service.send_verification_email',
            return_value=True,
        )
        resp = client.post(
            '/api/auth/resend-verification',
            json={'identifier': unverified_user.username},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

    def test_email_send_failure_returns_500(self, client, mocker, unverified_user):
        mocker.patch(
            'routes.auth_api.email_service.send_verification_email',
            return_value=False,
        )
        resp = client.post(
            '/api/auth/resend-verification',
            json={'identifier': unverified_user.email},
        )
        assert resp.status_code == 500
        data = json.loads(resp.data)
        assert data['success'] is False


# ── POST /api/auth/complete-oauth-profile ─────────────────────────────────────

class TestCompleteOauthProfile:

    def _valid_payload(self):
        return {
            'username':     'my_google_user',
            'signature':    'Jean Dupont',
            'accept_terms': True,
        }

    def test_unauthenticated_returns_401(self, client):
        resp = client.post('/api/auth/complete-oauth-profile', json=self._valid_payload())
        assert resp.status_code == 401

    def test_already_active_account_returns_error(self, client, auth_headers):
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=self._valid_payload(),
            headers=auth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_valid_completion_activates_account(
        self, client, db, pending_oauth_user, pending_oauth_headers
    ):
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=self._valid_payload(),
            headers=pending_oauth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        assert 'access_token' in data['data']['tokens']
        assert 'refresh_token' in data['data']['tokens']

        db.session.refresh(pending_oauth_user)
        assert pending_oauth_user.account_status == 'active'
        assert pending_oauth_user.username == 'my_google_user'

    def test_completion_returns_select_role_next_when_no_role(
        self, client, pending_oauth_user, pending_oauth_headers
    ):
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=self._valid_payload(),
            headers=pending_oauth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is True
        assert data['data']['next'] == 'select-role'

    def test_username_too_short_returns_error(
        self, client, pending_oauth_user, pending_oauth_headers
    ):
        payload = self._valid_payload()
        payload['username'] = 'ab'
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=payload,
            headers=pending_oauth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_no_signature_returns_error(
        self, client, pending_oauth_user, pending_oauth_headers
    ):
        payload = self._valid_payload()
        payload['signature'] = ''
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=payload,
            headers=pending_oauth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_terms_not_accepted_returns_error(
        self, client, pending_oauth_user, pending_oauth_headers
    ):
        payload = self._valid_payload()
        payload['accept_terms'] = False
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=payload,
            headers=pending_oauth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_taken_username_returns_error(
        self, client, user, pending_oauth_user, pending_oauth_headers
    ):
        payload = self._valid_payload()
        payload['username'] = user.username
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=payload,
            headers=pending_oauth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_invalid_username_chars_return_error(
        self, client, pending_oauth_user, pending_oauth_headers
    ):
        payload = self._valid_payload()
        payload['username'] = 'invalid user!'
        resp = client.post(
            '/api/auth/complete-oauth-profile',
            json=payload,
            headers=pending_oauth_headers,
        )
        data = json.loads(resp.data)
        assert data['success'] is False


# ── POST /api/auth/select-role ─────────────────────────────────────────────────

class TestSelectRole:

    def test_unauthenticated_returns_401(self, client):
        resp = client.post('/api/auth/select-role', json={'is_artist': True})
        assert resp.status_code == 401

    def test_no_role_selected_returns_error(self, client, no_role_headers):
        resp = client.post('/api/auth/select-role', json={
            'is_artist': False, 'is_beatmaker': False, 'is_mix_engineer': False,
        }, headers=no_role_headers)
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_select_artist_role_succeeds(self, client, db, no_role_user, no_role_headers):
        resp = client.post('/api/auth/select-role', json={
            'is_artist': True, 'is_beatmaker': False, 'is_mix_engineer': False,
        }, headers=no_role_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        db.session.refresh(no_role_user)
        assert no_role_user.user_type_selected is True
        assert no_role_user.is_artist is True

    def test_select_beatmaker_role_succeeds(self, client, db, mocker, no_role_user, no_role_headers):
        mocker.patch(
            'routes.auth_api.notification_service.notify_stripe_connect_setup',
            return_value=None,
        )
        resp = client.post('/api/auth/select-role', json={
            'is_artist': False, 'is_beatmaker': True, 'is_mix_engineer': False,
        }, headers=no_role_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        db.session.refresh(no_role_user)
        assert no_role_user.is_beatmaker is True

    def test_mix_engineer_role_returns_submit_sample_next(
        self, client, db, mocker, no_role_user, no_role_headers
    ):
        mocker.patch(
            'routes.auth_api.notification_service.notify_stripe_connect_setup',
            return_value=None,
        )
        resp = client.post('/api/auth/select-role', json={
            'is_artist': False, 'is_beatmaker': False, 'is_mix_engineer': True,
        }, headers=no_role_headers)
        data = json.loads(resp.data)
        assert data['success'] is True
        assert data['data']['next'] == 'submit-sample'

    def test_artist_role_returns_home_next(self, client, no_role_user, no_role_headers):
        resp = client.post('/api/auth/select-role', json={
            'is_artist': True, 'is_beatmaker': False, 'is_mix_engineer': False,
        }, headers=no_role_headers)
        data = json.loads(resp.data)
        assert data['data']['next'] == '/'

    def test_multiple_roles_can_be_selected(self, client, db, mocker, no_role_user, no_role_headers):
        mocker.patch(
            'routes.auth_api.notification_service.notify_stripe_connect_setup',
            return_value=None,
        )
        resp = client.post('/api/auth/select-role', json={
            'is_artist': True, 'is_beatmaker': True, 'is_mix_engineer': False,
        }, headers=no_role_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

        db.session.refresh(no_role_user)
        assert no_role_user.is_artist is True
        assert no_role_user.is_beatmaker is True

    def test_empty_body_returns_error(self, client, no_role_headers):
        resp = client.post('/api/auth/select-role', json={}, headers=no_role_headers)
        data = json.loads(resp.data)
        assert data['success'] is False
