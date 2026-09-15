"""
Tests d'intégration — API push (routes/push_api.py)

Couvre :
  - /api/push/register    : enregistre un jeton, idempotent sur ré-enregistrement
  - /api/push/register    : refuse une plateforme invalide / un jeton vide
  - /api/push/unregister  : désactive un jeton (le row reste, is_active=False)
  - /api/push/preference  : GET reflète l'état, PUT pose/efface push_opt_in_at
  - /api/push/preference  : désactiver le réglage désactive tous les jetons
  - Toutes les routes exigent un JWT (401 sans authentification)
"""
from models import DeviceToken


class TestPushRegister:

    def test_register_creates_device_token(self, client, db, user, auth_headers):
        resp = client.post('/api/push/register',
                            json={'token': 'tok-abc123', 'platform': 'android'},
                            headers=auth_headers)
        assert resp.status_code == 200

        row = DeviceToken.query.filter_by(token='tok-abc123').first()
        assert row is not None
        assert row.user_id == user.id
        assert row.platform == 'android'
        assert row.is_active is True

    def test_register_same_token_twice_is_idempotent(self, client, db, user, auth_headers):
        client.post('/api/push/register',
                    json={'token': 'tok-dup', 'platform': 'ios'},
                    headers=auth_headers)
        client.post('/api/push/register',
                    json={'token': 'tok-dup', 'platform': 'ios'},
                    headers=auth_headers)

        assert DeviceToken.query.filter_by(token='tok-dup').count() == 1

    def test_register_reactivates_deactivated_token(self, client, db, user, auth_headers):
        client.post('/api/push/register',
                    json={'token': 'tok-reuse', 'platform': 'android'},
                    headers=auth_headers)
        DeviceToken.query.filter_by(token='tok-reuse').update({'is_active': False})
        db.session.commit()

        client.post('/api/push/register',
                    json={'token': 'tok-reuse', 'platform': 'android'},
                    headers=auth_headers)

        row = DeviceToken.query.filter_by(token='tok-reuse').first()
        assert row.is_active is True

    def test_register_rejects_invalid_platform(self, client, db, user, auth_headers):
        resp = client.post('/api/push/register',
                            json={'token': 'tok-bad', 'platform': 'web'},
                            headers=auth_headers)
        assert resp.status_code == 400
        assert resp.get_json()['code'] == 'INVALID_DEVICE_TOKEN'
        assert DeviceToken.query.filter_by(token='tok-bad').count() == 0

    def test_register_rejects_empty_token(self, client, db, user, auth_headers):
        resp = client.post('/api/push/register',
                            json={'token': '', 'platform': 'android'},
                            headers=auth_headers)
        assert resp.status_code == 400

    def test_register_requires_authentication(self, client, db):
        resp = client.post('/api/push/register',
                            json={'token': 'tok-anon', 'platform': 'android'})
        assert resp.status_code == 401


class TestPushUnregister:

    def test_unregister_deactivates_without_deleting(self, client, db, user, auth_headers):
        client.post('/api/push/register',
                    json={'token': 'tok-off', 'platform': 'ios'},
                    headers=auth_headers)

        resp = client.post('/api/push/unregister',
                            json={'token': 'tok-off'},
                            headers=auth_headers)
        assert resp.status_code == 200

        row = DeviceToken.query.filter_by(token='tok-off').first()
        assert row is not None            # jamais supprimé (cf. docstring DeviceToken)
        assert row.is_active is False

    def test_unregister_requires_authentication(self, client, db):
        resp = client.post('/api/push/unregister', json={'token': 'tok-x'})
        assert resp.status_code == 401


class TestPushPreference:

    def test_get_preference_defaults_to_false(self, client, db, user, auth_headers):
        resp = client.get('/api/push/preference', headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['data']['push_opt_in'] is False

    def test_enable_sets_opt_in_and_timestamp(self, client, db, user, auth_headers):
        resp = client.put('/api/push/preference',
                           json={'enabled': True},
                           headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['data']['push_opt_in'] is True

        db.session.refresh(user)
        assert user.push_opt_in is True
        assert user.push_opt_in_at is not None

    def test_disable_clears_timestamp_and_deactivates_tokens(self, client, db, user, auth_headers):
        client.put('/api/push/preference', json={'enabled': True}, headers=auth_headers)
        client.post('/api/push/register',
                    json={'token': 'tok-will-be-killed', 'platform': 'android'},
                    headers=auth_headers)

        resp = client.put('/api/push/preference', json={'enabled': False}, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.get_json()['data']['push_opt_in'] is False

        db.session.refresh(user)
        assert user.push_opt_in is False
        assert user.push_opt_in_at is None

        row = DeviceToken.query.filter_by(token='tok-will-be-killed').first()
        assert row.is_active is False

    def test_preference_requires_authentication(self, client, db):
        assert client.get('/api/push/preference').status_code == 401
        assert client.put('/api/push/preference', json={'enabled': True}).status_code == 401
