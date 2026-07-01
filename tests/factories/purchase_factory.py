"""PurchaseFactory — construit des objets Purchase SQLAlchemy via factory-boy.

Montants par défaut : achat MP3 à 9.99€, commission 10%.
  platform_fee     = 9.99 × 10% = 1.00€
  composer_revenue = 9.99 × 90% = 8.99€
  contract_price   = 0€  (pas de clause supplémentaire)
  track_price      = 9.99€

Variations courantes :
  format_purchased='wav'   → purchase WAV (price_paid=19.99, etc.)
  format_purchased='stems' → purchase stems (price_paid=49.99, etc.)
  contract_price=5         → achat avec clause durée 3 ans
  stripe_transfer_id='tr_xxx' → virement compositeur effectué
"""

import uuid
from decimal import Decimal
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models import Purchase


class PurchaseFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Purchase
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    # Obligatoires — le test doit les fournir
    track_id = None
    buyer_id = None

    format_purchased = 'mp3'
    price_paid       = Decimal('9.99')
    buyer_name       = 'Test Buyer'

    # Répartition financière cohérente avec MP3 à 9.99€ (commission 10%)
    contract_price   = Decimal('0.00')
    track_price      = Decimal('9.99')
    platform_fee     = Decimal('1.00')
    composer_revenue = Decimal('8.99')

    # Stripe — payment intent unique par défaut, virement non effectué
    stripe_payment_intent_id = factory.LazyFunction(lambda: f'pi_test_{uuid.uuid4().hex[:16]}')
    stripe_transfer_id       = None

    # Contrat PDF — non généré par défaut
    contract_file = None
