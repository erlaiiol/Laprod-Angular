"""
Scénarios de commandes mix/master nommés.

Chaque fixture couvre un état distinct du workflow MixMasterRequest et les
branches de calcul financier associées.

Calculs de référence (ref=100€, cleaning=35% → total=35€) :
  deposit_amount   = total × 30%  = 10.50€
  remaining_amount = total × 70%  = 24.50€
  platform_fee     = total × 10%  =  3.50€
  engineer_revenue = total × 90%  = 31.50€
  revision_transfer = total × 10% × 90% = 3.15€
  final_transfer (0 rev) = total × 70% × 90% = 22.05€
  final_transfer (1 rev) = (total × 60%) × 90% = 18.90€
  refund_amount    = total × 70%  = 24.50€

Toutes les fixtures dépendent de `user_mix_engineer_low_min` et `user_artist`
importés depuis tests.scenarios.users pour éviter la duplication.
"""

import datetime
from decimal import Decimal
import pytest

from tests.scenarios.users import user_mix_engineer_low_min, user_artist  # noqa: F401


def _teardown_order(db, order):
    """Supprime une commande mix/master proprement."""
    db.session.rollback()
    existing = db.session.get(type(order), order.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def order_awaiting(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande fraîche : statut awaiting_acceptance, aucun paiement capturé.
    Couvre : can_request_revision()=False, is_expired()=False,
    get_refund_amount()=24.50, stripe_payment_status='authorized'."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='awaiting_acceptance',
        stripe_payment_status='authorized',
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_accepted(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande acceptée par l'ingénieur : dépôt (30%) capturé.
    stripe_payment_status='partially_captured', stripe_deposit_transfer_id renseigné."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='accepted',
        stripe_payment_status='partially_captured',
        stripe_deposit_transfer_id='tr_deposit_test_accepted',
        accepted_at=datetime.datetime.now(datetime.timezone.utc),
        deadline=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_delivered(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande livrée en attente de validation : can_request_revision()=True (0 révisions utilisées).
    L'artiste peut demander jusqu'à 2 révisions."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='delivered',
        stripe_payment_status='partially_captured',
        stripe_deposit_transfer_id='tr_deposit_test_delivered',
        revision_count=0,
        accepted_at=now - datetime.timedelta(days=5),
        deadline=now + datetime.timedelta(days=2),
        delivered_at=now,
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_revision1(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Première révision en cours : revision_count=1, 10% déjà transféré.
    can_request_revision()=False (déjà en révision).
    get_final_transfer_amount() = (24.50 - 3.50) × 90% = 18.90€."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='revision1',
        stripe_payment_status='partially_captured',
        stripe_deposit_transfer_id='tr_deposit_test_rev1',
        revision_count=1,
        revision1_message='Le kick manque de punch, pouvez-vous le renforcer ?',
        revision1_requested_at=now - datetime.timedelta(hours=2),
        accepted_at=now - datetime.timedelta(days=4),
        deadline=now + datetime.timedelta(days=3),
        delivered_at=now - datetime.timedelta(hours=3),
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_revision2(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Deuxième révision en cours : revision_count=2, max atteint.
    can_request_revision()=False pour toujours (quota épuisé)."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='revision2',
        stripe_payment_status='partially_captured',
        stripe_deposit_transfer_id='tr_deposit_test_rev2',
        revision_count=2,
        revision1_message='Le kick manque de punch.',
        revision2_message='Les voix sont trop en avant.',
        revision1_requested_at=now - datetime.timedelta(days=2),
        revision2_requested_at=now - datetime.timedelta(hours=1),
        accepted_at=now - datetime.timedelta(days=5),
        deadline=now + datetime.timedelta(days=2),
        delivered_at=now - datetime.timedelta(hours=2),
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_completed(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande complétée sans révision : paiement final capturé.
    stripe_payment_status='fully_captured'.
    get_final_transfer_amount() = 24.50 × 90% = 22.05€."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='completed',
        stripe_payment_status='fully_captured',
        stripe_deposit_transfer_id='tr_deposit_completed',
        stripe_final_transfer_id='tr_final_completed',
        revision_count=0,
        accepted_at=now - datetime.timedelta(days=6),
        deadline=now - datetime.timedelta(days=1),
        delivered_at=now - datetime.timedelta(days=2),
        completed_at=now,
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_completed_after_rev1(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande complétée après 1 révision.
    get_final_transfer_amount() = (24.50 - 3.50) × 90% = 18.90€.
    Couvre la branche de calcul avec révision déduite du final."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='completed',
        stripe_payment_status='fully_captured',
        stripe_deposit_transfer_id='tr_deposit_comp_rev1',
        stripe_final_transfer_id='tr_final_comp_rev1',
        stripe_revision1_transfer_id='tr_rev1_comp',
        revision_count=1,
        revision1_message='Retouche légère sur la réverbe.',
        revision1_requested_at=now - datetime.timedelta(days=3),
        revision1_delivered_at=now - datetime.timedelta(days=1),
        accepted_at=now - datetime.timedelta(days=6),
        deadline=now - datetime.timedelta(days=1),
        delivered_at=now - datetime.timedelta(days=4),
        completed_at=now,
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_rejected(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande rejetée par l'ingénieur.
    get_refund_amount() = remaining_amount = 24.50€ (l'artiste est entièrement remboursé).
    stripe_payment_status='canceled'."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='rejected',
        stripe_payment_status='canceled',
        stripe_refund_id='re_rejected_test',
        revision_count=0,
        rejected_at=now,
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_expired(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande expirée : deadline dépassée, statut toujours 'accepted'.
    is_expired()=True → déclenche le flux de remboursement automatique."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    past = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='accepted',
        stripe_payment_status='partially_captured',
        stripe_deposit_transfer_id='tr_deposit_expired',
        revision_count=0,
        accepted_at=past - datetime.timedelta(days=7),
        deadline=past,
    )
    yield o
    _teardown_order(db, o)


@pytest.fixture()
def order_all_services(db, bound_factories, user_mix_engineer_low_min, user_artist):
    """Commande avec tous les services activés + stems séparés.
    Services : cleaning(35%) + effects(45%) + mastering(20%) + artistic(60%) + stems(20%)
    Pour ref=100€ : total = 100 × 180% = 180€
    deposit=54€, remaining=126€, platform_fee=18€, engineer_revenue=162€.
    Couvre calculate_service_price() à son maximum et price_max du serializer."""
    from tests.factories.mixmaster_factory import MixMasterRequestFactory
    now = datetime.datetime.now(datetime.timezone.utc)
    o = MixMasterRequestFactory(
        artist_id=user_artist.id,
        engineer_id=user_mix_engineer_low_min.id,
        status='accepted',
        stripe_payment_status='partially_captured',
        stripe_deposit_transfer_id='tr_deposit_all_services',
        # Tous les services activés
        service_cleaning=True,
        service_effects=True,
        service_mastering=True,
        service_artistic=True,
        has_separated_stems=True,
        # Financials pour total=180€
        total_price=Decimal('180.00'),
        deposit_amount=Decimal('54.00'),
        remaining_amount=Decimal('126.00'),
        platform_fee=Decimal('18.00'),
        engineer_revenue=Decimal('162.00'),
        accepted_at=now,
        deadline=now + datetime.timedelta(days=7),
    )
    yield o
    _teardown_order(db, o)
