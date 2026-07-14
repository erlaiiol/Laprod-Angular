"""
Tests unitaires — utils/contract_data_builder.py

Couvre les correctifs identifiés lors de la relecture croisée du 12/07/2026 :
  - le prix affiché au PDF ne doit pas être tronqué en entier (seule la
    colonne Contract.price, un Integer, doit l'être) ;
  - consent_recorded_at ne doit être posé que si un consentement réel a été
    recueilli, jamais de façon inconditionnelle ;
  - create_contract_and_pdf() ne doit pas empoisonner la transaction
    englobante quand la création du Contract échoue (SAVEPOINT).
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

import pytest

from utils.contract_data_builder import (
    build_contract_data,
    contract_kwargs_from_data,
    create_contract_and_pdf,
)
from tests.factories.track_factory import TrackFactory
from tests.factories.user_factory import UserFactory


@pytest.fixture()
def composer(db, bound_factories):
    u = UserFactory(is_beatmaker=True)
    yield u
    existing = db.session.get(type(u), u.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


@pytest.fixture()
def buyer(db, bound_factories):
    u = UserFactory()
    yield u
    existing = db.session.get(type(u), u.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


@pytest.fixture()
def track(db, bound_factories, composer):
    t = TrackFactory(composer_id=composer.id)
    yield t
    existing = db.session.get(type(t), t.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


def _base_kwargs(track, composer, buyer, **overrides):
    kwargs = dict(
        track=track, composer_user=composer, client_user=buyer,
        is_exclusive=False, start_date='01/01/2026', end_date='31/12/2028',
        duration_text='3 ans', territory='France',
        mechanical_reproduction=False, public_show=False, arrangement=False,
        price=Decimal('14.99'),
    )
    kwargs.update(overrides)
    return kwargs


class TestPricePrecision:

    def test_pdf_data_keeps_exact_price(self, track, composer, buyer):
        data = build_contract_data(**_base_kwargs(track, composer, buyer, price=Decimal('14.99')))
        assert data['price'] == Decimal('14.99')

    def test_contract_kwargs_truncates_price_to_int(self, track, composer, buyer):
        data = build_contract_data(**_base_kwargs(track, composer, buyer, price=Decimal('14.99')))
        kwargs = contract_kwargs_from_data(data)
        assert kwargs['price'] == 14
        assert isinstance(kwargs['price'], int)


class TestConsentRecordedAt:

    def test_none_when_no_consent_given(self, track, composer, buyer):
        data = build_contract_data(**_base_kwargs(
            track, composer, buyer,
            legal_terms_accepted=False, withdrawal_right_waived=False,
        ))
        assert data['consent_recorded_at'] is None

    def test_set_when_legal_terms_accepted(self, track, composer, buyer):
        data = build_contract_data(**_base_kwargs(
            track, composer, buyer,
            legal_terms_accepted=True, withdrawal_right_waived=False,
        ))
        assert data['consent_recorded_at'] is not None

    def test_set_when_withdrawal_waived(self, track, composer, buyer):
        data = build_contract_data(**_base_kwargs(
            track, composer, buyer,
            legal_terms_accepted=False, withdrawal_right_waived=True,
        ))
        assert data['consent_recorded_at'] is not None


class TestCreateContractAndPdfTransactionSafety:

    def test_contract_creation_failure_does_not_poison_outer_transaction(
        self, db, track, composer, buyer, tmp_path,
    ):
        """
        Si la construction du Contract échoue (ex : contrainte violée), la
        transaction englobante doit rester utilisable — un Purchase déjà
        flush() avant l'appel ne doit pas être perdu ni provoquer une
        InFailedSqlTransaction sur l'écriture suivante.
        """
        from models import Purchase

        purchase = Purchase(
            track_id=track.id, buyer_id=buyer.id, format_purchased='mp3',
            price_paid=Decimal('14.99'), buyer_name=buyer.username,
            contract_price=0, track_price=Decimal('14.99'),
            platform_fee=Decimal('1.50'), composer_revenue=Decimal('13.49'),
            stripe_payment_intent_id=f'pi_test_{track.id}_{buyer.id}',
            license_status='active',
        )
        db.session.add(purchase)
        db.session.flush()

        contract_data = build_contract_data(**_base_kwargs(track, composer, buyer))
        # percentage hors bornes (0-85, cf. CheckConstraint ck_contract_percentage_valid)
        # force l'échec de l'INSERT du Contract.
        contract_data['percentage'] = 999

        result = create_contract_and_pdf(
            contract_data=contract_data,
            contracts_dir=tmp_path,
            filename_prefix='contract_test_failure',
            purchase=purchase,
        )
        assert result is None

        # La transaction englobante doit rester utilisable : le Purchase
        # flush() avant l'appel doit toujours être visible et committable.
        purchase.license_status = 'active'
        db.session.commit()

        refreshed = db.session.get(Purchase, purchase.id)
        assert refreshed is not None

        db.session.delete(refreshed)
        db.session.commit()

    def test_success_path_creates_contract_and_pdf(self, db, track, composer, buyer, tmp_path):
        contract_data = build_contract_data(**_base_kwargs(track, composer, buyer))
        with patch('utils.contract_data_builder.generate_contract_pdf') as mock_pdf:
            contract = create_contract_and_pdf(
                contract_data=contract_data,
                contracts_dir=tmp_path,
                filename_prefix='contract_test_success',
            )
        assert contract is not None
        assert contract.contract_file is not None
        mock_pdf.assert_called_once()
        db.session.delete(contract)
        db.session.commit()
