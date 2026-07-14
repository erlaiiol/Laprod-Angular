"""
Tests d'intégration — routes/auth_api.py

Teste les endpoints HTTP avec la base SQLite en mémoire.
store_refresh_token (Redis) est mocké pour ne pas dépendre d'un serveur Redis.
"""

import json
import pytest


# ── Fixture : mock store_refresh_token pour les tests login ───────────────────

@pytest.fixture(autouse=True)
def mock_refresh_token_store(mocker):
    """Évite les appels Redis dans store_refresh_token."""
    mocker.patch('routes.auth_api.store_refresh_token', return_value=None)


# ── GET /api/auth/ping ─────────────────────────────────────────────────────────

class TestPing:

    def test_ping_returns_200(self, client):
        resp = client.get('/api/auth/ping')
        assert resp.status_code == 200

    def test_ping_returns_status_ok(self, client):
        data = json.loads(resp := client.get('/api/auth/ping').data)
        assert data['status'] == 'ok'


# ── POST /api/auth/login ───────────────────────────────────────────────────────

class TestLogin:

    def test_valid_credentials_return_tokens(self, client, user):
        """Un login correct doit retourner des tokens JWT valides."""
        resp = client.post(
            '/api/auth/login',
            json={'identifier': user.email, 'password': 'TestPassword123!'},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        assert 'access_token' in data['data']['tokens']
        assert 'refresh_token' in data['data']['tokens']

    def test_wrong_password_returns_401(self, client, user):
        resp = client.post(
            '/api/auth/login',
            json={'identifier': user.email, 'password': 'WrongPassword!'},
        )
        assert resp.status_code == 401

    def test_unknown_user_returns_401(self, client):
        resp = client.post(
            '/api/auth/login',
            json={'identifier': 'nobody@nowhere.com', 'password': 'whatever'},
        )
        assert resp.status_code == 401

    def test_unknown_user_still_hashes_to_prevent_timing_oracle(self, client, mocker):
        """Un identifiant inconnu doit tout de même déclencher un hash factice :
        sans lui, la réponse plus rapide révèle par timing l'inexistence du compte."""
        spy = mocker.patch('routes.auth_api.check_password_hash')
        resp = client.post(
            '/api/auth/login',
            json={'identifier': 'ghost@nowhere.com', 'password': 'whatever'},
        )
        assert resp.status_code == 401
        spy.assert_called_once()

    def test_missing_fields_returns_400(self, client):
        resp = client.post('/api/auth/login', json={})
        assert resp.status_code in (400, 422)

    def test_no_json_body_returns_error(self, client):
        resp = client.post('/api/auth/login', data='', content_type='text/plain')
        assert resp.status_code in (400, 415, 422)

    def test_unverified_email_returns_403(self, client, db):
        """Un utilisateur dont l'email n'est pas vérifié ne peut pas se connecter."""
        from models import User
        u = User(
            email='unverified@test.laprod.fr',
            username='unverified_user',
            email_verified=False,
            account_status='active',
            user_type_selected=True,
        )
        u.set_password('TestPassword123!')
        db.session.add(u)
        db.session.commit()

        resp = client.post(
            '/api/auth/login',
            json={'identifier': 'unverified@test.laprod.fr', 'password': 'TestPassword123!'},
        )
        assert resp.status_code == 403

        db.session.delete(u)
        db.session.commit()

    def test_password_too_long_returns_401(self, client, user):
        """Un mot de passe > 50 caractères est rejeté avant même de tester en DB."""
        resp = client.post(
            '/api/auth/login',
            json={'identifier': user.email, 'password': 'A' * 51},
        )
        assert resp.status_code == 401

    def test_login_by_username(self, client, user):
        """L'identifiant peut être le username et pas l'email."""
        resp = client.post(
            '/api/auth/login',
            json={'identifier': user.username, 'password': 'TestPassword123!'},
        )
        assert resp.status_code == 200


# ── GET /api/auth/me ───────────────────────────────────────────────────────────

class TestMe:

    def test_authenticated_user_gets_own_data(self, client, auth_headers, user):
        resp = client.get('/api/auth/me', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['data']['user']['email'] == user.email

    def test_unauthenticated_returns_401(self, client):
        resp = client.get('/api/auth/me')
        assert resp.status_code == 401


# ── POST /api/auth/register ────────────────────────────────────────────────────

class TestRegister:

    def _valid_payload(self, suffix=''):
        return {
            'username': f'newuser{suffix}',
            'email': f'new{suffix}@register.laprod.fr',
            'password': 'TestPass123!',
            'password_confirm': 'TestPass123!',
            'accept_terms': True,
            'signature': 'Ma Signature',
        }

    def test_missing_fields_returns_400(self, client):
        resp = client.post('/api/auth/register', json={})
        assert resp.status_code == 400

    def test_invalid_email_returns_400(self, client):
        payload = self._valid_payload()
        payload['email'] = 'not-an-email'
        resp = client.post('/api/auth/register', json=payload)
        assert resp.status_code == 400

    def test_duplicate_username_returns_400(self, client, user):
        payload = self._valid_payload()
        payload['username'] = user.username
        resp = client.post('/api/auth/register', json=payload)
        assert resp.status_code == 400

    def test_duplicate_email_returns_400(self, client, user):
        payload = self._valid_payload()
        payload['email'] = user.email
        resp = client.post('/api/auth/register', json=payload)
        assert resp.status_code == 400

    def test_successful_registration_creates_user(self, client, db, mocker):
        mocker.patch(
            'routes.auth_api.email_service.send_verification_email',
            return_value=True,
        )
        payload = self._valid_payload(suffix='_ok')
        resp = client.post('/api/auth/register', json=payload)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        from models import User
        created = db.session.query(User).filter_by(email=payload['email']).first()
        assert created is not None
        db.session.delete(created)
        db.session.commit()


# ── POST /api/auth/logout ──────────────────────────────────────────────────────

class TestLogout:

    def test_authenticated_user_can_logout(self, client, auth_headers, mocker):
        mocker.patch('routes.auth_api.revoke_all_refresh_tokens', return_value=None)
        resp = client.post('/api/auth/logout', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True

    def test_logout_blocklists_token(self, client, db, auth_headers, mocker):
        mocker.patch('routes.auth_api.revoke_all_refresh_tokens', return_value=None)
        from models import TokenBlocklist
        count_before = db.session.query(TokenBlocklist).count()
        resp = client.post('/api/auth/logout', headers=auth_headers)
        assert resp.status_code == 200
        count_after = db.session.query(TokenBlocklist).count()
        assert count_after == count_before + 1
