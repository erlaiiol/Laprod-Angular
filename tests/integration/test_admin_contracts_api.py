"""
Tests d'intégration — routes/admin_api.py : admin_create_contract

Couvre : POST /api/admin/contracts/create.

Ce endpoint n'avait aucune couverture de test avant sa migration vers le
builder partagé (utils/contract_data_builder.py) — ajouté à cette occasion
pour verrouiller le comportement attendu, notamment la génération PDF qui
n'existait pas auparavant sur ce chemin.
"""
from unittest.mock import patch

import pytest

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
def client_user(db, bound_factories):
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


class TestAdminCreateContract:

    def test_creates_contract_and_generates_pdf(self, client, db, admin_headers, track, client_user):
        with patch('utils.contract_data_builder.generate_contract_pdf') as mock_pdf:
            resp = client.post(
                '/api/admin/contracts/create',
                json={
                    'track_id': track.id,
                    'client_id': client_user.id,
                    'price': 250,
                    'is_exclusive': True,
                    'territory': 'France',
                    'duration': '5 ans',
                },
                headers=admin_headers,
            )

        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        contract_id = data['data']['contract_id']

        mock_pdf.assert_called_once()

        from models import Contract
        contract = db.session.get(Contract, contract_id)
        assert contract is not None
        assert contract.track_id == track.id
        assert contract.client_id == client_user.id
        assert contract.composer_id == track.composer_id
        assert contract.is_exclusive is True
        assert contract.territory == 'France'
        assert contract.price == 250
        assert contract.sacem_percentage_composer == 70
        assert contract.sacem_percentage_buyer == 30
        # Avant la migration vers le builder partagé, ce chemin ne générait
        # jamais de PDF ni ne posait contract_file — régression verrouillée ici.
        assert contract.contract_file is not None

        db.session.delete(contract)
        db.session.commit()

    def test_price_uses_decimal_pipeline_not_float(self, client, db, admin_headers, track, client_user):
        """
        Régression : le prix doit transiter par Decimal(str(x)), jamais par
        float(x) — même quand leur str() coïncide pour une valeur donnée, un
        float reste arithmétiquement incompatible avec le reste du pipeline
        argent de l'app (Purchase.price_paid etc. sont des Decimal ; mélanger
        float et Decimal lève TypeError dès la première opération commune).
        """
        with patch('utils.contract_data_builder.generate_contract_pdf') as mock_pdf:
            resp = client.post(
                '/api/admin/contracts/create',
                json={'track_id': track.id, 'client_id': client_user.id, 'price': 19.99},
                headers=admin_headers,
            )
        assert resp.status_code == 200

        pdf_data = mock_pdf.call_args.args[1]
        from decimal import Decimal as _Decimal
        assert isinstance(pdf_data['price'], _Decimal)
        assert pdf_data['price'] == _Decimal('19.99')

        contract_id = resp.get_json()['data']['contract_id']
        from models import Contract
        contract = db.session.get(Contract, contract_id)
        db.session.delete(contract)
        db.session.commit()

    def test_missing_required_fields_returns_error(self, client, admin_headers, track, client_user):
        resp = client.post(
            '/api/admin/contracts/create',
            json={'track_id': track.id},
            headers=admin_headers,
        )
        data = resp.get_json()
        assert data['success'] is False

    def test_orphaned_composer_returns_clean_error_not_500(self, client, db, admin_headers, track, client_user):
        """
        Régression : track.composer_user peut résoudre à None (FK orpheline) —
        avant correctif, build_contract_data plantait avec un AttributeError
        non intercepté (500) au lieu de renvoyer une erreur propre.
        """
        track.composer_id = 999_999_999
        db.session.commit()

        resp = client.post(
            '/api/admin/contracts/create',
            json={
                'track_id': track.id, 'client_id': client_user.id, 'price': 100,
            },
            headers=admin_headers,
        )
        assert resp.status_code != 500
        data = resp.get_json()
        assert data['success'] is False

    def test_consent_not_recorded_by_default(self, client, db, admin_headers, track, client_user):
        """Sans consentement explicite, consent_recorded_at doit rester nul (pas de fausse preuve)."""
        with patch('utils.contract_data_builder.generate_contract_pdf'):
            resp = client.post(
                '/api/admin/contracts/create',
                json={'track_id': track.id, 'client_id': client_user.id, 'price': 100},
                headers=admin_headers,
            )
        contract_id = resp.get_json()['data']['contract_id']

        from models import Contract
        contract = db.session.get(Contract, contract_id)
        assert contract.legal_terms_accepted is False
        assert contract.withdrawal_right_waived is False
        assert contract.consent_recorded_at is None

        db.session.delete(contract)
        db.session.commit()
