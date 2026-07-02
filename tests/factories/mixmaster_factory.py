"""MixMasterRequestFactory — construit des commandes mix/master via factory-boy.

Les montants financiers par défaut correspondent à :
  service_cleaning=True, ref=100€, min=10€
  total = 100 × 35% = 35.00€
  deposit  = 35 × 30% = 10.50€
  remaining = 35 × 70% = 24.50€
  platform_fee = 35 × 10% = 3.50€
  engineer_revenue = 35 × 90% = 31.50€
"""

import uuid
from decimal import Decimal
import factory
from factory.alchemy import SQLAlchemyModelFactory
from models import MixMasterRequest


class MixMasterRequestFactory(SQLAlchemyModelFactory):
    class Meta:
        model = MixMasterRequest
        sqlalchemy_session = None
        sqlalchemy_session_persistence = 'commit'

    # artist_id et engineer_id sont obligatoires
    artist_id   = None
    engineer_id = None

    title         = factory.Sequence(lambda n: f'Mix Order {n}')
    status        = 'awaiting_acceptance'
    original_file = factory.LazyFunction(lambda: f'stems/order_{uuid.uuid4().hex[:8]}.zip')
    reference_file = None

    # Services — seul cleaning activé par défaut (le plus simple)
    service_cleaning   = True
    service_effects    = False
    service_artistic   = False
    service_mastering  = False
    has_separated_stems = False

    # Montants financiers cohérents avec cleaning=35%, ref=100€
    total_price      = Decimal('35.00')
    deposit_amount   = Decimal('10.50')
    remaining_amount = Decimal('24.50')
    platform_fee     = Decimal('3.50')
    engineer_revenue = Decimal('31.50')

    # Stripe — état initial : autorisé mais pas encore capturé
    stripe_payment_intent_id = factory.LazyFunction(lambda: f'pi_test_{uuid.uuid4().hex[:16]}')
    stripe_payment_status    = 'authorized'

    # Transferts Stripe — non effectués par défaut
    stripe_deposit_transfer_id  = None
    stripe_final_transfer_id    = None
    stripe_refund_id            = None

    # Révisions
    revision_count    = 0
    revision1_message = None
    revision2_message = None
