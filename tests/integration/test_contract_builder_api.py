"""
Tests d'intégration — routes/contract_builder_api.py

Requiert un utilisateur authentifié via JWT.
Les routes utilisent @jwt_required() et récupèrent le user par son ID JWT.
"""

import json
import pytest


# ── GET /api/contract-builder/template ────────────────────────────────────────

class TestTemplate:

    def test_template_requires_authentication(self, client):
        resp = client.get('/api/contract-builder/template')
        assert resp.status_code == 401

    def test_authenticated_user_gets_template(self, client, auth_headers, db):
        """La réponse doit contenir une liste de groupes (même vide sans seed)."""
        resp = client.get('/api/contract-builder/template', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        assert 'groups' in data['data']
        assert isinstance(data['data']['groups'], list)

    def test_template_with_seeded_groups(self, client, auth_headers, db):
        """Avec des groupes/clauses en DB, ils doivent apparaître dans la réponse."""
        from models import ContractClauseGroup, ContractClause, ClauseTypeEnum

        group = ContractClauseGroup(
            name='Test Group',
            sort_order=1,
            is_active=True,
        )
        db.session.add(group)
        db.session.flush()

        clause = ContractClause(
            group_id=group.id,
            name='Test Clause',
            clause_type=ClauseTypeEnum.text,
            sort_order=1,
            is_required=False,
            is_enabled_by_default=True,
            is_active=True,
        )
        db.session.add(clause)
        db.session.commit()

        resp = client.get('/api/contract-builder/template', headers=auth_headers)
        data = json.loads(resp.data)
        assert data['success'] is True
        groups = data['data']['groups']
        assert any(g['name'] == 'Test Group' for g in groups)

        # Cleanup
        db.session.delete(clause)
        db.session.delete(group)
        db.session.commit()


# ── POST /api/contract-builder/contracts ──────────────────────────────────────

class TestCreateContract:

    def test_requires_authentication(self, client):
        resp = client.post('/api/contract-builder/contracts', json={})
        assert resp.status_code == 401

    def test_creates_draft_contract(self, client, auth_headers, user, db):
        """Un contrat brouillon doit être créé avec les données minimales."""
        payload = {
            'title': 'Contrat test unitaire',
            'parties': [],
            'values': [],
        }
        resp = client.post(
            '/api/contract-builder/contracts',
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201)
        data = json.loads(resp.data)
        assert data['success'] is True
        contract_id = data['data']['contract']['id']
        assert contract_id > 0

        # Cleanup
        from models import UserContract
        contract = db.session.get(UserContract, contract_id)
        if contract:
            db.session.delete(contract)
            db.session.commit()


# ── GET /api/contract-builder/contracts ───────────────────────────────────────

class TestListContracts:

    def test_requires_authentication(self, client):
        resp = client.get('/api/contract-builder/contracts')
        assert resp.status_code == 401

    def test_returns_only_own_contracts(self, client, auth_headers, db, user, admin_user, admin_headers):
        """Un utilisateur ne doit voir que ses propres contrats."""
        from models import UserContract, UserContractStatus

        own_contract = UserContract(
            user_id=user.id,
            title='Mon contrat',
            status=UserContractStatus.draft,
        )
        other_contract = UserContract(
            user_id=admin_user.id,
            title='Contrat de quelqu\'un d\'autre',
            status=UserContractStatus.draft,
        )
        db.session.add_all([own_contract, other_contract])
        db.session.commit()

        resp = client.get('/api/contract-builder/contracts', headers=auth_headers)
        data = json.loads(resp.data)
        assert resp.status_code == 200
        contracts = data['data']['contracts']
        ids = [c['id'] for c in contracts]
        assert own_contract.id in ids
        assert other_contract.id not in ids

        db.session.delete(own_contract)
        db.session.delete(other_contract)
        db.session.commit()


# ── PUT /api/contract-builder/contracts/<id> ──────────────────────────────────

class TestUpdateContract:

    def test_owner_can_update_contract(self, client, auth_headers, user, db):
        """Le propriétaire peut modifier son contrat."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Brouillon initial',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        db.session.commit()

        resp = client.put(
            f'/api/contract-builder/contracts/{contract.id}',
            json={'title': 'Titre modifié', 'parties': [], 'values': []},
            headers=auth_headers,
        )
        assert resp.status_code == 200

        db.session.delete(contract)
        db.session.commit()

    def test_other_user_cannot_update_contract(self, client, admin_headers, user, db):
        """Un autre utilisateur ne peut pas modifier le contrat d'autrui."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Contrat privé',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        db.session.commit()

        resp = client.put(
            f'/api/contract-builder/contracts/{contract.id}',
            json={'title': 'Tentative de modification', 'parties': [], 'values': []},
            headers=admin_headers,
        )
        assert resp.status_code in (403, 404)

        db.session.delete(contract)
        db.session.commit()


# ── GET /api/contract-builder/contracts/<id> ──────────────────────────────────

class TestGetContractDetail:

    def test_requires_authentication(self, client):
        resp = client.get('/api/contract-builder/contracts/1')
        assert resp.status_code == 401

    def test_owner_gets_contract_detail(self, client, auth_headers, user, db):
        """Le propriétaire obtient les détails complets du contrat."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Détail contrat test',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        db.session.commit()

        resp = client.get(
            f'/api/contract-builder/contracts/{contract.id}',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        detail = data['data']['contract']
        assert detail['id'] == contract.id
        assert detail['title'] == 'Détail contrat test'
        assert 'parties' in detail
        assert 'values' in detail

        db.session.delete(contract)
        db.session.commit()

    def test_other_user_cannot_access_detail(self, client, admin_headers, user, db):
        """Un autre utilisateur (même admin) ne peut pas lire le contrat d'autrui."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Contrat privé détail',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        db.session.commit()

        resp = client.get(
            f'/api/contract-builder/contracts/{contract.id}',
            headers=admin_headers,
        )
        assert resp.status_code in (403, 404)

        db.session.delete(contract)
        db.session.commit()
