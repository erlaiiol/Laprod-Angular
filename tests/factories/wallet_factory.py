"""WalletFactory + WalletTransactionFactory — factory-boy pour les objets financiers."""

import datetime
from decimal import Decimal
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models import Wallet, WalletTransaction


class WalletFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Wallet
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    user_id           = None  # obligatoire
    balance_available = Decimal('0.00')
    balance_pending   = Decimal('0.00')


class WalletTransactionFactory(SQLAlchemyModelFactory):
    class Meta:
        model = WalletTransaction
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    wallet_id    = None  # obligatoire
    type         = 'credit_beat_sale'
    amount       = Decimal('8.99')   # 90% de 9.99€ (prix MP3 standard)
    status       = 'pending'
    description  = 'Vente MP3 — Test Beat Standard'
    available_at = factory.LazyFunction(
        lambda: datetime.datetime.now() + datetime.timedelta(days=7)
    )
    stripe_transfer_id = None
