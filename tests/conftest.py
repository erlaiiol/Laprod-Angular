"""
Fixtures pytest partagées pour tous les tests LaProd.

Stratégie :
- Les env vars sont fixées AVANT tout import Flask pour éviter les erreurs
  de configuration (SECRET_KEY manquante, DB URI invalide, etc.).
- La base de données est SQLite en mémoire : rapide, pas de dépendance externe.
- Redis est mocké via sys.modules : aucun serveur Redis requis.
- APScheduler n'est PAS démarré (is_main_process=False en test).
- Le rate limiting est désactivé (RATELIMIT_ENABLED=False).
"""

import os
import sys
from decimal import Decimal
from unittest.mock import MagicMock

# ── 1. Variables d'environnement requises (avant tout import app) ─────────────
os.environ.setdefault('SECRET_KEY', 'test-secret-key-laprod-not-for-production')
os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('STRIPE_SECRET_KEY', 'sk_test_dummy_key_for_tests')
os.environ.setdefault('STRIPE_PUBLIC_KEY', 'pk_test_dummy_key_for_tests')
os.environ.setdefault('STRIPE_WEBHOOK_SECRET', 'whsec_dummy_for_tests')
os.environ.setdefault('GOOGLE_CLIENT_ID', 'dummy-google-client-id')
os.environ.setdefault('GOOGLE_CLIENT_SECRET', 'dummy-google-client-secret')
os.environ.setdefault('GOOGLE_DISCOVERY_URL', 'https://accounts.google.com/.well-known/openid-configuration')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt-secret-key')
os.environ.setdefault('MAIL_USERNAME', 'test@laprod.fr')
os.environ.setdefault('MAIL_PASSWORD', 'test-mail-password')
os.environ.setdefault('MAIL_DEFAULT_SENDER', 'test@laprod.fr')
os.environ.setdefault('REDIS_HOST', 'localhost')
os.environ.setdefault('REDIS_PORT', '6379')
os.environ.setdefault('REDIS_DB', '0')
# Forcer le stockage en mémoire pour flask-limiter → aucun serveur Redis requis
os.environ.setdefault('REDIS_URL', 'memory://')

import pytest

# ── 2b. Patch config.py avant l'import de app.py ──────────────────────────────
# app.py appelle create_app() au niveau module → il faut que config.py soit déjà
# patché pour que les options de pool PostgreSQL ne soient pas passées à SQLite.
import config as _cfg
_cfg.SQLALCHEMY_ENGINE_OPTIONS = {}


# ── 3. Fixtures Flask ──────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def app():
    """Application Flask avec SQLite en mémoire, CSRF et rate limiting désactivés."""
    from app import create_app
    from extensions import db as _db

    _app = create_app(test_config={
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False,
        'RATELIMIT_STORAGE_URL': 'memory://',
        # Stripe (mocké globalement dans les tests qui en ont besoin)
        'PLATFORM_COMMISSION': 0.10,
        # Contrats - valeurs de test
        'CONTRACT_EXCLUSIVE_PRICE': 150,
        'CONTRACT_DURATIONS': {'1': 5, '2': 8, '3': 10, 'lifetime': 30},
        'CONTRACT_MECHANICAL_REPRODUCTION_PRICE': 30,
        'CONTRACT_PUBLIC_SHOW_PRICE': 40,
        'CONTRACT_ARRANGEMENT_PRICE': 10,
        'CONTRACT_TERRITORY_EUROPE': 5,
        'CONTRACT_TERRITORY_WORLD': 10,
    })

    with _app.app_context():
        _db.create_all()
        yield _app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def db(app):
    """Session DB avec rollback automatique après chaque test."""
    from extensions import db as _db
    yield _db
    _db.session.rollback()


# ── 4. Fixtures utilisateurs ───────────────────────────────────────────────────

@pytest.fixture()
def user(db):
    """Utilisateur standard actif (beatmaker, premium)."""
    from models import User
    u = User(
        email='beatmaker@test.laprod.fr',
        username='test_beatmaker',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_beatmaker=True,
        is_premium=True,
    )
    u.set_password('TestPassword123!')
    db.session.add(u)
    db.session.commit()
    yield u
    # Supprimer le wallet en premier (pas de CASCADE FK → User dans le modèle)
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    db.session.delete(u)
    db.session.commit()


@pytest.fixture()
def admin_user(db):
    """Utilisateur administrateur."""
    from models import User
    u = User(
        email='admin@test.laprod.fr',
        username='test_admin',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_admin=True,
    )
    u.set_password('AdminPassword123!')
    db.session.add(u)
    db.session.commit()
    yield u
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    db.session.delete(u)
    db.session.commit()


# ── 5. Fixtures JWT ────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_headers(app, user):
    """Headers HTTP avec token JWT pour l'utilisateur standard."""
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def admin_headers(app, admin_user):
    """Headers HTTP avec token JWT pour l'administrateur."""
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(admin_user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
