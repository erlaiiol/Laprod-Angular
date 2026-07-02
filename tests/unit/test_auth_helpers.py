"""
Tests unitaires — utils/auth_helpers.py

Teste les décorateurs require_user et require_admin dans un contexte Flask réel
(routes de test temporaires) avec des tokens JWT générés directement.

Note : Ce module déclare sa propre fixture `app` (module scope) pour que le
blueprint de test puisse être enregistré AVANT toute requête, indépendamment
des tests d'intégration qui partagent la session Flask principale.
"""

import json
import pytest
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, create_access_token


# ── Blueprint de test ─────────────────────────────────────────────────────────

_test_bp = Blueprint('auth_helper_tests', __name__)


@_test_bp.route('/test/user-only', methods=['GET'])
@jwt_required()
def _user_only_route():
    from utils.auth_helpers import require_user
    @require_user
    def inner(current_user):
        return jsonify({'user_id': current_user.id})
    return inner()


@_test_bp.route('/test/admin-only', methods=['GET'])
@jwt_required()
def _admin_only_route():
    from utils.auth_helpers import require_admin
    @require_admin
    def inner(current_user):
        return jsonify({'is_admin': current_user.is_admin})
    return inner()


# ── App isolée : le blueprint est enregistré AVANT toute requête ──────────────

@pytest.fixture(scope='module')
def app():
    from app import create_app
    from extensions import db as _db

    _app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'RATELIMIT_STORAGE_URL': 'memory://',
    })
    _app.register_blueprint(_test_bp)

    with _app.app_context():
        _db.create_all()
        yield _app
        _db.session.remove()
        _db.drop_all()


# ── Tests require_user ────────────────────────────────────────────────────────

class TestRequireUser:

    def test_authenticated_user_can_access_route(self, client, user, app):
        """Un utilisateur JWT valide doit pouvoir accéder à la route."""
        with app.app_context():
            token = create_access_token(identity=str(user.id))
        resp = client.get(
            '/test/user-only',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['user_id'] == user.id

    def test_missing_token_returns_401(self, client):
        """Sans token JWT, la route doit retourner 401."""
        resp = client.get('/test/user-only')
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        """Un token invalide doit retourner 401."""
        resp = client.get(
            '/test/user-only',
            headers={'Authorization': 'Bearer not_a_real_token'},
        )
        assert resp.status_code == 422  # JWT-Extended retourne 422 pour token malformé

    def test_nonexistent_user_returns_404(self, client, app):
        """Un token pour un user_id qui n'existe pas en DB doit retourner 404."""
        with app.app_context():
            token = create_access_token(identity='99999')
        resp = client.get(
            '/test/user-only',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert resp.status_code == 404


# ── Tests require_admin ───────────────────────────────────────────────────────

class TestRequireAdmin:

    def test_admin_user_can_access_admin_route(self, client, admin_user, app):
        """Un admin doit pouvoir accéder aux routes admin."""
        with app.app_context():
            token = create_access_token(identity=str(admin_user.id))
        resp = client.get(
            '/test/admin-only',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['is_admin'] is True

    def test_regular_user_gets_403_on_admin_route(self, client, user, app):
        """Un non-admin doit recevoir 403 sur les routes admin."""
        with app.app_context():
            token = create_access_token(identity=str(user.id))
        resp = client.get(
            '/test/admin-only',
            headers={'Authorization': f'Bearer {token}'},
        )
        assert resp.status_code == 403

    def test_missing_token_returns_401_on_admin_route(self, client):
        """Sans token, la route admin doit retourner 401."""
        resp = client.get('/test/admin-only')
        assert resp.status_code == 401
