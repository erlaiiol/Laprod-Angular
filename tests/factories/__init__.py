"""
Factories pytest — couche 1 de la bibliothèque de données de référence.

Fournit une fixture `bound_factories` qui injecte la session SQLAlchemy
de test dans toutes les factories factory-boy. À utiliser en combinaison
avec les scénarios nommés définis dans tests/scenarios/.

Catalogue des factories disponibles :
  UserFactory              → utilisateurs avec tous les rôles et états
  TrackFactory             → beats approuvés ou en attente, avec ou sans fichiers
  MixMasterRequestFactory  → commandes mix/master (service cleaning par défaut)
  WalletFactory            → portefeuilles vides ou pré-alimentés
  WalletTransactionFactory → transactions (credit_beat_sale par défaut)
  PurchaseFactory          → achats de beats (MP3 par défaut)
  ToplineFactory           → toplines vocales déposées sur un beat

Usage dans un test :
    def test_something(db, bound_factories):
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        user  = UserFactory(subscription_plan='pro', is_beatmaker=True)
        track = TrackFactory(composer_id=user.id, is_approved=False)
"""

import pytest


@pytest.fixture()
def bound_factories(db):
    """Injecte la session de test dans toutes les factories factory-boy."""
    from tests.factories.user_factory import UserFactory
    from tests.factories.track_factory import TrackFactory
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    from tests.factories.wallet_factory import WalletFactory, WalletTransactionFactory
    from tests.factories.purchase_factory import PurchaseFactory
    from tests.factories.topline_factory import ToplineFactory

    factories = [UserFactory, TrackFactory, MixMasterRequestFactory,
                 WalletFactory, WalletTransactionFactory,
                 PurchaseFactory, ToplineFactory]
    for cls in factories:
        cls._meta.sqlalchemy_session = db.session
    yield
    for cls in factories:
        cls._meta.sqlalchemy_session = None
