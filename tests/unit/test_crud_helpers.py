"""
Tests unitaires — utils/crud_helpers.py

Stratégie :
- TestGetOr404 / TestHandleRouteExceptions / TestCommitOrRollback utilisent une
  app Flask isolée (module scope) avec un Blueprint de test enregistré avant toute requête.
- TestRequireOwnership est pur Python (pas de DB, pas de Flask).
"""

import json
import pytest
from unittest.mock import MagicMock
from flask import Blueprint


# ── Blueprint de test avec routes qui exercent les décorateurs ─────────────────

_test_bp = Blueprint('crud_helper_tests', __name__)


@_test_bp.route('/test/crud/not-found')
def _route_not_found():
    from utils.crud_helpers import handle_route_exceptions, EntityNotFound
    @handle_route_exceptions
    def inner():
        raise EntityNotFound('Entité introuvable.')
    return inner()


@_test_bp.route('/test/crud/forbidden')
def _route_forbidden():
    from utils.crud_helpers import handle_route_exceptions, EntityForbidden
    @handle_route_exceptions
    def inner():
        raise EntityForbidden('Accès refusé.')
    return inner()


@_test_bp.route('/test/crud/server-error')
def _route_server_error():
    from utils.crud_helpers import commit_or_rollback
    @commit_or_rollback
    def inner():
        raise RuntimeError('panne inattendue')
    return inner()


@_test_bp.route('/test/crud/reraise-not-found')
def _route_reraise_not_found():
    from utils.crud_helpers import handle_route_exceptions, commit_or_rollback, EntityNotFound
    @handle_route_exceptions
    @commit_or_rollback
    def inner():
        raise EntityNotFound('not found')
    return inner()


@_test_bp.route('/test/crud/reraise-forbidden')
def _route_reraise_forbidden():
    from utils.crud_helpers import handle_route_exceptions, commit_or_rollback, EntityForbidden
    @handle_route_exceptions
    @commit_or_rollback
    def inner():
        raise EntityForbidden('forbidden')
    return inner()


# ── App isolée : Blueprint enregistré AVANT toute requête ─────────────────────

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


# ── TestGetOr404 ──────────────────────────────────────────────────────────────

class TestGetOr404:

    def test_returns_entity_when_found(self, db, user):
        """get_or_404 retourne l'entité quand elle existe en base."""
        from models import User
        from utils.crud_helpers import get_or_404
        result = get_or_404(User, user.id)
        assert result.id == user.id

    def test_raises_entity_not_found_when_missing(self, db):
        """get_or_404 lève EntityNotFound quand l'entité n'existe pas."""
        from models import User
        from utils.crud_helpers import get_or_404, EntityNotFound
        with pytest.raises(EntityNotFound):
            get_or_404(User, 99999)


# ── TestRequireOwnership ──────────────────────────────────────────────────────

class TestRequireOwnership:

    def test_passes_when_current_user_is_owner(self):
        """Aucune exception si current_user est propriétaire de l'entité."""
        from utils.crud_helpers import require_ownership
        entity = MagicMock(); entity.user_id = 42
        current_user = MagicMock(); current_user.id = 42; current_user.is_admin = False
        require_ownership(entity, 'user_id', current_user)  # ne doit pas lever

    def test_raises_entity_forbidden_when_not_owner(self):
        """EntityForbidden levée si l'utilisateur n'est pas propriétaire."""
        from utils.crud_helpers import require_ownership, EntityForbidden
        entity = MagicMock(); entity.user_id = 99
        current_user = MagicMock(); current_user.id = 1; current_user.is_admin = False
        with pytest.raises(EntityForbidden):
            require_ownership(entity, 'user_id', current_user)

    def test_admin_bypasses_ownership_check(self):
        """Un admin passe même si l'entité appartient à un autre user."""
        from utils.crud_helpers import require_ownership
        entity = MagicMock(); entity.user_id = 99
        current_user = MagicMock(); current_user.id = 1; current_user.is_admin = True
        require_ownership(entity, 'user_id', current_user)  # ne doit pas lever


# ── TestHandleRouteExceptions ─────────────────────────────────────────────────

class TestHandleRouteExceptions:

    def test_entity_not_found_returns_404(self, client):
        """EntityNotFound → réponse HTTP 404 JSON avec success=False."""
        resp = client.get('/test/crud/not-found')
        assert resp.status_code == 404
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_entity_forbidden_returns_403(self, client):
        """EntityForbidden → réponse HTTP 403 JSON avec success=False."""
        resp = client.get('/test/crud/forbidden')
        assert resp.status_code == 403
        data = json.loads(resp.data)
        assert data['success'] is False


# ── TestCommitOrRollback ──────────────────────────────────────────────────────

class TestCommitOrRollback:

    def test_reraises_entity_not_found(self, client):
        """commit_or_rollback re-lève EntityNotFound → handle_route_exceptions retourne 404."""
        resp = client.get('/test/crud/reraise-not-found')
        assert resp.status_code == 404

    def test_reraises_entity_forbidden(self, client):
        """commit_or_rollback re-lève EntityForbidden → handle_route_exceptions retourne 403."""
        resp = client.get('/test/crud/reraise-forbidden')
        assert resp.status_code == 403

    def test_returns_500_on_generic_exception(self, client):
        """Une exception générique → rollback + réponse 500 JSON."""
        resp = client.get('/test/crud/server-error')
        assert resp.status_code == 500
        data = json.loads(resp.data)
        assert data['success'] is False
