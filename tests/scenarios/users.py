"""
Scénarios utilisateurs nommés.

Chaque fixture représente un profil métier distinct qui influence
le comportement des serializers, des calculs de prix ou des contrôles d'accès.

Catalogue :
  user_free              → plan gratuit (upload=2/j, topline=5/sem)
  user_amateur           → plan amateur (upload=15/j, topline=50/sem, is_premium_active=True)
  user_pro               → plan pro (upload=30/j, topline=200/sem, is_premium_active=True)
  user_premium_expired   → plan pro mais premium_expires_at dans le passé (is_premium_active=False)
  user_artist            → artiste pur (is_artist=True, pas beatmaker)
  user_pending           → onboarding OAuth incomplet (account_status='pending_completion')
  user_admin             → administrateur plateforme
  user_mix_engineer_*    → ingénieurs avec différents tarifs et certifications
  user_stripe_ready      → ingénieur avec Stripe Connect complet

NOTE : ne jamais passer is_premium=True à UserFactory — c'est un hybrid_property
sans setter. Utiliser subscription_plan='pro'/'amateur' + premium_expires_at.

Pour générer un JWT valide depuis un scénario :
    from flask_jwt_extended import create_access_token

    @pytest.fixture()
    def engineer_headers(app, user_mix_engineer_low_min):
        with app.app_context():
            token = create_access_token(identity=str(user_mix_engineer_low_min.id))
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
"""

from datetime import datetime, timedelta
from decimal import Decimal
import pytest
from tests.scenarios import _teardown_user


@pytest.fixture()
def user_free(db, bound_factories):
    """Beatmaker sur plan gratuit, sans Stripe Connect.
    Tokens: upload=20 initiaux (défaut modèle), topline=5/semaine.
    is_premium_active=False.
    Utilisé pour tester les limites de tokens et les accès plan-free."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(is_beatmaker=True, subscription_plan='free')
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_amateur(db, bound_factories):
    """Beatmaker sur plan amateur (LaProd+ Amateur).
    is_premium_active=True, tokens up=15/j, topline=50/sem.
    Utilisé pour tester les fonctionnalités premium de base (pas les stems pro)."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_beatmaker=True,
        subscription_plan='amateur',
        premium_expires_at=None,  # valide indéfiniment
        premium_source='stripe',
        upload_track_tokens=15,
        topline_tokens=50,
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_pro(db, bound_factories):
    """Beatmaker sur plan pro (LaProd+ Pro).
    is_premium_active=True, tokens up=30/j, topline=200/sem.
    Peut uploader des stems et activer les licences exclusives.
    Utilisé pour tester les fonctionnalités premium élevées."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_beatmaker=True,
        subscription_plan='pro',
        premium_expires_at=None,  # valide indéfiniment
        premium_source='stripe',
        upload_track_tokens=30,
        topline_tokens=200,
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_premium_expired(db, bound_factories):
    """Beatmaker avec abonnement pro expiré (premium_expires_at dans le passé).
    is_premium_active=False malgré subscription_plan='pro'.
    Utilisé pour tester les gardes d'accès après expiration de l'abonnement."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_beatmaker=True,
        subscription_plan='pro',
        premium_expires_at=datetime(2024, 1, 1),  # expiré
        premium_source='stripe',
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_artist(db, bound_factories):
    """Artiste pur — commande des sessions mix/master, dépose des toplines.
    Pas de rôle beatmaker."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(is_artist=True)
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_pending(db, bound_factories):
    """Utilisateur venant de s'inscrire via OAuth — profil incomplet.
    account_status='pending_completion', user_type_selected=False.
    Utilisé pour tester le flow d'onboarding post-OAuth."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(account_status='pending_completion', user_type_selected=False,
                    email_verified=False)
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_admin(db, bound_factories):
    """Administrateur plateforme.
    Peut approuver des tracks, gérer les certifications, voir tous les utilisateurs."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(is_admin=True)
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_mix_engineer_low_min(db, bound_factories):
    """Ingénieur certifié : ref=100€, min=10€ (min_pct=10%).
    min_pct < 35% → aucun service n'est auto-forcé par le backend.
    Couvre : test_payment_mixmaster_checkout, test_stripe_mixmaster_order_mode.
    Aussi certifié mastering (is_certified_master_engineer=True) pour
    permettre la sélection du service_mastering dans les tests."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_mix_engineer=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        is_certified_producer_arranger=False,
        mixmaster_reference_price=Decimal('100.00'),
        mixmaster_price_min=Decimal('10.00'),
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_mix_engineer_high_min(db, bound_factories):
    """Ingénieur avec plancher élevé : ref=100€, min=30€ (min_pct=30%).
    min_pct >= 30% → le total minimum est 30€ même avec peu de services.
    Utilisé pour tester la logique de prix plancher (price_min enforcement)."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_mix_engineer=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        is_certified_producer_arranger=False,
        mixmaster_reference_price=Decimal('100.00'),
        mixmaster_price_min=Decimal('30.00'),
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_mix_engineer_mastering(db, bound_factories):
    """Ingénieur certifié mastering par l'admin (is_certified_master_engineer=True).
    Peut accepter des commandes avec service_mastering.
    ref=150€, min=20€."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_mix_engineer=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        is_certified_producer_arranger=False,
        mixmaster_reference_price=Decimal('150.00'),
        mixmaster_price_min=Decimal('20.00'),
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_mix_engineer_autoforce(db, bound_factories):
    """Ingénieur avec min_pct=35% exactement : ref=100€, min=35€.
    min_pct = (35/100)×100 = 35 ≥ 35 → service_cleaning auto-forcé côté backend.
    Utilisé pour tester le mode Rapide (Quick Mode) : l'artiste envoie tous les
    services à '0' mais service_cleaning reste True côté serveur."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_mix_engineer=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        is_certified_producer_arranger=False,
        mixmaster_reference_price=Decimal('100.00'),
        mixmaster_price_min=Decimal('35.00'),
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_mix_engineer_producer(db, bound_factories):
    """Ingénieur autorisé pour l'intervention artistique (is_certified_producer_arranger=True).
    Peut accepter des commandes avec service_artistic (+60%).
    ref=200€, min=30€."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_mix_engineer=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        is_certified_producer_arranger=True,
        mixmaster_reference_price=Decimal('200.00'),
        mixmaster_price_min=Decimal('30.00'),
    )
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def user_stripe_ready(db, bound_factories):
    """Ingénieur avec Stripe Connect entièrement configuré.
    stripe_ready=True dans le serializer mix_engineer().
    Peut recevoir des virements de la plateforme."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(
        is_mix_engineer=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        mixmaster_reference_price=Decimal('100.00'),
        mixmaster_price_min=Decimal('10.00'),
        stripe_account_id='acct_test_stripe_ready',
        stripe_account_status='active',
        stripe_onboarding_complete=True,
    )
    yield u
    _teardown_user(db, u)
