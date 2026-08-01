"""
Tests d'intégration — routes/structure_api.py

Le profil Structure (identité légale B2B) est réservé au palier Pro Structuré
(current_user.is_pro) et mono-owner en v1 : une seule Structure par utilisateur.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token

from models import (
    ContractTemplateTypeEnum, PartyTypeEnum, PremiumPayment, Purchase, Structure,
    UserContract, UserContractParty,
)
from tests.factories.user_factory import UserFactory
from tests.factories.purchase_factory import PurchaseFactory
from tests.factories.track_factory import TrackFactory
from tests.scenarios import _teardown_user


# ── Fixtures locales ─────────────────────────────────────────────────────────────

def _headers_for(app, u):
    with app.app_context():
        token = create_access_token(identity=str(u.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _teardown_structure_owner(db, u):
    """Structure, PremiumPayment (user_id) et Purchase (buyer_id) n'ont pas de
    cascade sur User (par design, cf. models.py) — il faut les retirer
    explicitement avant de supprimer l'utilisateur, sinon la contrainte FK
    bloque en Postgres (SQLite ne la fait pas respecter en test)."""
    db.session.query(PremiumPayment).filter_by(user_id=u.id).delete()
    db.session.query(Purchase).filter_by(buyer_id=u.id).delete()
    db.session.query(Structure).filter_by(owner_id=u.id).delete()
    db.session.commit()
    _teardown_user(db, u)


@pytest.fixture()
def pro_owner(db, app, bound_factories):
    """Producteur Pro Structuré — peut créer une Structure."""
    u = UserFactory(is_producer=True, subscription_plan='pro',
                     premium_expires_at=None, premium_source='stripe')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_structure_owner(db, u)


@pytest.fixture()
def other_pro_owner(db, app, bound_factories):
    """Second producteur Pro Structuré — pour les tests de refus par tiers."""
    u = UserFactory(is_producer=True, subscription_plan='pro',
                     premium_expires_at=None, premium_source='stripe')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_structure_owner(db, u)


@pytest.fixture()
def free_owner(db, app, bound_factories):
    """Producteur plan gratuit — ne peut pas créer de Structure."""
    u = UserFactory(is_producer=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def premium_owner(db, app, bound_factories):
    """Producteur Premium (sous Pro Structuré) — ne peut pas créer de Structure."""
    u = UserFactory(is_producer=True, subscription_plan='amateur',
                     premium_expires_at=None, premium_source='stripe')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


def _create(client, headers, **overrides):
    payload = {'name': 'Salle Test SMAC'}
    payload.update(overrides)
    return client.post('/api/structures', json=payload, headers=headers)


# ── TestCreateStructure ──────────────────────────────────────────────────────────

class TestCreateStructure:
    def test_creation_reussie_en_pro_structure(self, client, pro_owner):
        user, headers = pro_owner

        res = _create(client, headers, siret='12345678900012', legal_form='SAS')
        assert res.status_code == 201
        body = res.get_json()['data']['structure']
        assert body['name'] == 'Salle Test SMAC'
        assert body['siret'] == '12345678900012'
        assert body['owner_id'] == user.id

    def test_refus_sur_plan_gratuit(self, client, free_owner):
        _, headers = free_owner
        res = _create(client, headers)
        assert res.status_code == 403

    def test_refus_sur_plan_premium(self, client, premium_owner):
        _, headers = premium_owner
        res = _create(client, headers)
        assert res.status_code == 403

    def test_refus_si_deja_existante(self, client, pro_owner):
        _, headers = pro_owner
        assert _create(client, headers).status_code == 201
        res = _create(client, headers)
        assert res.status_code == 409

    def test_nom_requis(self, client, pro_owner):
        _, headers = pro_owner
        res = client.post('/api/structures', json={'siret': '123'}, headers=headers)
        assert res.status_code == 400


# ── TestMine ─────────────────────────────────────────────────────────────────────

class TestMine:
    def test_mine_retourne_null_sans_structure(self, client, pro_owner):
        _, headers = pro_owner
        res = client.get('/api/structures/mine', headers=headers)
        assert res.status_code == 200
        assert res.get_json()['data']['structure'] is None

    def test_mine_retourne_la_structure(self, client, pro_owner):
        _, headers = pro_owner
        _create(client, headers)
        res = client.get('/api/structures/mine', headers=headers)
        assert res.get_json()['data']['structure']['name'] == 'Salle Test SMAC'


# ── TestUpdateStructure ──────────────────────────────────────────────────────────

class TestUpdateStructure:
    def test_mise_a_jour_par_le_owner(self, client, pro_owner):
        _, headers = pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.put(f'/api/structures/{structure_id}', json={'name': 'Nouveau nom'}, headers=headers)
        assert res.status_code == 200
        assert res.get_json()['data']['structure']['name'] == 'Nouveau nom'

    def test_refus_par_un_tiers(self, client, pro_owner, other_pro_owner):
        _, headers = pro_owner
        _, other_headers = other_pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.put(f'/api/structures/{structure_id}', json={'name': 'Hack'}, headers=other_headers)
        assert res.status_code == 403

    def test_structure_introuvable(self, client, pro_owner):
        _, headers = pro_owner
        res = client.put('/api/structures/999999', json={'name': 'X'}, headers=headers)
        assert res.status_code == 404


# ── TestDeleteStructure ───────────────────────────────────────────────────────────

class TestDeleteStructure:
    def test_suppression_par_le_owner(self, client, db, pro_owner):
        user, headers = pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.delete(f'/api/structures/{structure_id}', headers=headers)
        assert res.status_code == 200
        assert db.session.get(Structure, structure_id) is None

    def test_refus_par_un_tiers(self, client, pro_owner, other_pro_owner):
        _, headers = pro_owner
        _, other_headers = other_pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.delete(f'/api/structures/{structure_id}', headers=other_headers)
        assert res.status_code == 403

    def test_suppression_detache_les_parties_de_contrat_sans_cascade(self, client, db, pro_owner):
        """Un contrat déjà généré est un instantané légal : il doit survivre à la
        suppression de la Structure, seul le lien de pré-remplissage disparaît."""
        user, headers = pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        contract = UserContract(user_id=user.id, title='Contrat test',
                                 contract_type=ContractTemplateTypeEnum.management)
        db.session.add(contract)
        db.session.flush()
        party = UserContractParty(contract_id=contract.id, role='Structure',
                                   party_type=PartyTypeEnum.company,
                                   company_name='Salle Test SMAC',
                                   linked_structure_id=structure_id)
        db.session.add(party)
        db.session.commit()

        res = client.delete(f'/api/structures/{structure_id}', headers=headers)
        assert res.status_code == 200

        db.session.refresh(party)
        assert party.linked_structure_id is None
        assert db.session.get(UserContract, contract.id) is not None

        # UserContract.user_id est NOT NULL sans cascade : la retirer avant que
        # le fixture ne supprime le owner (le party suit par cascade du contrat).
        db.session.delete(contract)
        db.session.commit()


# ── TestExport ────────────────────────────────────────────────────────────────────

class TestExport:
    def test_export_csv_inclut_abonnement_et_achats(self, client, db, pro_owner):
        user, headers = pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        payment = PremiumPayment(
            user_id=user.id, plan='pro_structure', amount_paid=Decimal('49.99'),
            duration_days=30, is_renewal=False,
        )
        db.session.add(payment)

        seller = UserFactory(is_beatmaker=True)
        track = TrackFactory(composer_id=seller.id)
        db.session.flush()
        purchase = PurchaseFactory(track_id=track.id, buyer_id=user.id)
        db.session.commit()

        res = client.get(f'/api/structures/{structure_id}/export?format=csv', headers=headers)
        assert res.status_code == 200
        assert res.mimetype == 'text/csv'
        csv_text = res.data.decode('utf-8-sig')
        assert 'LaProd+ pro_structure' in csv_text
        assert track.title in csv_text
        assert 'TOTAL' in csv_text

        # Purchase.track_id est NOT NULL sans cascade : la retirer avant de
        # supprimer le compositeur (dont la suppression cascade sur son Track).
        db.session.delete(purchase)
        db.session.commit()
        _teardown_user(db, seller)

    def test_export_pdf_renvoie_un_pdf(self, client, pro_owner):
        _, headers = pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.get(f'/api/structures/{structure_id}/export?format=pdf', headers=headers)
        assert res.status_code == 200
        assert res.mimetype == 'application/pdf'

    def test_format_invalide_refuse(self, client, pro_owner):
        _, headers = pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.get(f'/api/structures/{structure_id}/export?format=xml', headers=headers)
        assert res.status_code == 400

    def test_refus_par_un_tiers(self, client, pro_owner, other_pro_owner):
        _, headers = pro_owner
        _, other_headers = other_pro_owner
        structure_id = _create(client, headers).get_json()['data']['structure']['id']

        res = client.get(f'/api/structures/{structure_id}/export', headers=other_headers)
        assert res.status_code == 403
