"""
Factories pytest — couche 1 de la bibliothèque de données de référence.

Fournit une fixture `bound_factories` qui injecte la session SQLAlchemy
de test dans toutes les factories factory-boy. À utiliser en combinaison
avec les scénarios nommés définis dans tests/scenarios/.

Usage dans un test :
    def test_something(db, bound_factories):
        from tests.factories.user_factory import UserFactory
        user = UserFactory(subscription_plan='pro', is_beatmaker=True)
"""

import pytest


@pytest.fixture()
def bound_factories(db):
    """Injecte la session de test dans toutes les factories factory-boy."""
    from tests.factories.user_factory import UserFactory
    from tests.factories.track_factory import TrackFactory
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    from tests.factories.wallet_factory import WalletFactory, WalletTransactionFactory

    factories = [UserFactory, TrackFactory, MixMasterRequestFactory,
                 WalletFactory, WalletTransactionFactory]
    for cls in factories:
        cls._meta.sqlalchemy_session = db.session
    yield
    for cls in factories:
        cls._meta.sqlalchemy_session = None
