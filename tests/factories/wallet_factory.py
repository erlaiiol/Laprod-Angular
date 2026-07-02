"""WalletFactory + WalletTransactionFactory — factory-boy pour les objets financiers.

WalletFactory :
  balance_available=0, balance_pending=0 par défaut.
  Surcharger pour tester des états spécifiques :
    WalletFactory(user_id=u.id, balance_available=Decimal('50.00'))

WalletTransactionFactory :
  type='credit_beat_sale' (MP3 à 9.99€) par défaut.
  Toutes les valeurs de `type` supportées par le modèle :
    'credit_beat_sale'         → vente MP3/WAV/stems (90% du prix)
    'credit_mixmaster_deposit' → acompte commande mix/master (30%)
    'credit_mixmaster_final'   → solde final commande mix/master (70% - révisions)
    'withdrawal'               → retrait vers compte bancaire
    'expiration'               → fonds expirés (non retirés après délai)

  Toutes les valeurs de `status` supportées :
    'pending'     → en attente de disponibilité (délai de 7 jours pour ventes beats)
    'available'   → fonds disponibles pour retrait
    'transferred' → virement Stripe effectué
    'expired'     → fonds non retirés après délai d'expiration
"""

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

    wallet_id    = None   # obligatoire
    type         = 'credit_beat_sale'
    amount       = Decimal('8.99')   # 90% de 9.99€ (prix MP3 standard)
    status       = 'pending'
    description  = 'Vente MP3 — Test Beat Standard'
    available_at = factory.LazyFunction(
        lambda: datetime.datetime.now() + datetime.timedelta(days=7)
    )
    stripe_transfer_id   = None
    purchase_id          = None  # lié à un Purchase si type=credit_beat_sale
    mixmaster_request_id = None  # lié à une commande si type=credit_mixmaster_*
