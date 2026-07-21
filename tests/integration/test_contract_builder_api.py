"""
Tests d'intégration — routes/contract_builder_api.py

Toutes les routes requièrent un utilisateur authentifié via JWT et récupèrent
le user par son ID JWT, sauf GET /template qui est public (aucune donnée
utilisateur, consultable pour la démo /contract-builder/demo côté front).
"""

import json
import pytest


# ── GET /api/contract-builder/template ────────────────────────────────────────

class TestTemplate:

    def test_template_is_public(self, client):
        """Public depuis l'ajout de la démo /contract-builder/demo : aucune donnée
        utilisateur dans le template, consultable sans authentification."""
        resp = client.get('/api/contract-builder/template')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        assert 'groups' in data['data']

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

    def test_non_pro_owner_cannot_update_contract(self, client, auth_headers, user, db):
        """Le propriétaire perd le droit d'édition dès qu'il n'est plus Pro (ex: downgrade
        après création du brouillon) — vérifié à chaque appel, pas seulement à la création."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Brouillon créé pendant l\'abonnement Pro',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        user.subscription_plan = 'free'
        db.session.commit()

        resp = client.put(
            f'/api/contract-builder/contracts/{contract.id}',
            json={'title': 'Tentative après downgrade', 'parties': [], 'values': []},
            headers=auth_headers,
        )
        assert resp.status_code == 403

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
        assert detail['can_edit'] is True  # user (fixture) est Pro

        db.session.delete(contract)
        db.session.commit()

    def test_can_edit_false_for_non_pro_owner(self, client, auth_headers, user, db):
        """Un propriétaire non-Pro garde l'accès en lecture à son brouillon (ex: après
        downgrade) mais can_edit doit refléter qu'il ne peut plus le modifier — c'est ce
        flag que le front utilise pour verrouiller l'UI (pas un simple statut local)."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Brouillon après downgrade',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        user.subscription_plan = 'free'
        db.session.commit()

        resp = client.get(
            f'/api/contract-builder/contracts/{contract.id}',
            headers=auth_headers,
        )
        assert resp.status_code == 200  # toujours consultable
        detail = json.loads(resp.data)['data']['contract']
        assert detail['can_edit'] is False

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


# ── POST /api/contract-builder/contracts/<id>/generate ────────────────────────

class TestGenerateContract:

    def test_non_pro_owner_cannot_generate_pdf(self, client, auth_headers, user, db):
        """Comme pour update : la génération PDF revérifie is_pro à chaque appel,
        pas seulement à la création du brouillon."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Brouillon prêt à générer',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        user.subscription_plan = 'free'
        db.session.commit()

        resp = client.post(
            f'/api/contract-builder/contracts/{contract.id}/generate',
            headers=auth_headers,
        )
        assert resp.status_code == 403

        db.session.delete(contract)
        db.session.commit()

    def test_other_user_cannot_generate_pdf(self, client, admin_headers, user, db):
        """Un autre utilisateur ne peut pas générer le PDF du contrat d'autrui."""
        from models import UserContract, UserContractStatus

        contract = UserContract(
            user_id=user.id,
            title='Contrat privé',
            status=UserContractStatus.draft,
        )
        db.session.add(contract)
        db.session.commit()

        resp = client.post(
            f'/api/contract-builder/contracts/{contract.id}/generate',
            headers=admin_headers,
        )
        assert resp.status_code in (403, 404)

        db.session.delete(contract)
        db.session.commit()


# ── Contrat de management (add-on Premium+ sur un RosterLink) ────────────────────

class TestManagementContract:
    """Le contrat de management a son propre seuil (Premium+, can_use_management_
    contract) — plus bas que le reste du contract builder (Semi-Pro+, contract_quota),
    et n'est pas soumis au quota mensuel."""

    def _create(self, client, headers, **overrides):
        payload = {'title': 'Mandat de management', 'contract_type': 'management', **overrides}
        return client.post('/api/contract-builder/contracts', json=payload, headers=headers)

    def test_free_ne_peut_pas_creer_de_contrat_de_management(self, client, auth_headers, user, db):
        user.subscription_plan = 'free'
        db.session.commit()

        resp = self._create(client, auth_headers)
        assert resp.status_code == 403

    def test_premium_peut_creer_un_contrat_de_management(self, client, auth_headers, user, db):
        """Premium n'a normalement PAS accès au contract builder générique
        (contract_quota == 0), mais DOIT avoir accès au contrat de management :
        c'est précisément le seuil qui distingue les deux."""
        from models import UserContract

        user.subscription_plan = 'premium'
        db.session.commit()

        resp = self._create(client, auth_headers)
        assert resp.status_code == 201
        data = json.loads(resp.data)
        contract_id = data['data']['contract']['id']
        assert data['data']['contract']['contract_type'] == 'management'

        db.session.delete(db.session.get(UserContract, contract_id))
        db.session.commit()

    def test_pas_de_quota_mensuel_sur_le_management(self, client, auth_headers, user, db):
        """Semi-Pro n'a qu'1 contrat/mois sur le contract builder générique ; le
        management n'est pas concerné par ce quota."""
        from models import UserContract

        user.subscription_plan = 'semi_pro'
        db.session.commit()

        created = []
        for _ in range(2):
            resp = self._create(client, auth_headers)
            assert resp.status_code == 201
            created.append(json.loads(resp.data)['data']['contract']['id'])

        for cid in created:
            db.session.delete(db.session.get(UserContract, cid))
        db.session.commit()

    def test_linked_user_id_est_persiste_sur_une_partie(self, client, auth_headers, user, db):
        from models import UserContract, UserContractParty

        user.subscription_plan = 'premium'
        db.session.commit()

        resp = self._create(client, auth_headers)
        contract_id = json.loads(resp.data)['data']['contract']['id']

        update_resp = client.put(
            f'/api/contract-builder/contracts/{contract_id}',
            json={
                'parties': [
                    {'party_type': 'physical', 'role': 'Manager', 'sort_order': 0},
                    {'party_type': 'physical', 'role': 'Artiste', 'sort_order': 1, 'linked_user_id': user.id},
                ],
                'values': [],
            },
            headers=auth_headers,
        )
        assert update_resp.status_code == 200
        parties = json.loads(update_resp.data)['data']['contract']['parties']
        artiste_party = next(p for p in parties if p['role'] == 'Artiste')
        assert artiste_party['linked_user_id'] == user.id

        db.session.delete(db.session.get(UserContract, contract_id))
        db.session.commit()


# ── POST /api/roster/<id>/attach-contract ─────────────────────────────────────────

class TestAttachManagementContract:

    def _make_roster_link(self, db, producer, artist):
        from models import RosterLink, RosterLinkStatus
        link = RosterLink(
            producer_id=producer.id, artist_id=artist.id,
            invited_by_id=producer.id, status=RosterLinkStatus.active,
        )
        db.session.add(link)
        db.session.commit()
        return link

    def test_attache_un_contrat_de_management_au_lien(self, client, db, app, bound_factories):
        from flask_jwt_extended import create_access_token
        from models import RosterLink, UserContract
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user

        producer = UserFactory(is_producer=True, subscription_plan='premium')
        artist   = UserFactory(is_artist=True, subscription_plan='free')
        db.session.commit()
        with app.app_context():
            headers = {'Authorization': f'Bearer {create_access_token(identity=str(producer.id))}',
                       'Content-Type': 'application/json'}

        link = self._make_roster_link(db, producer, artist)
        contract = UserContract(user_id=producer.id, title='Mandat', contract_type='management')
        db.session.add(contract)
        db.session.commit()

        resp = client.post(
            f'/api/roster/{link.id}/attach-contract',
            json={'contract_id': contract.id},
            headers=headers,
        )
        assert resp.status_code == 200
        assert json.loads(resp.data)['data']['link']['has_management_contract'] is True
        assert db.session.get(RosterLink, link.id).management_contract_id == contract.id

        db.session.delete(contract)
        db.session.delete(link)
        db.session.commit()
        _teardown_user(db, artist)
        _teardown_user(db, producer)

    def test_refuse_un_contrat_qui_n_est_pas_de_type_management(self, client, db, app, bound_factories):
        from flask_jwt_extended import create_access_token
        from models import UserContract
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user

        producer = UserFactory(is_producer=True, subscription_plan='premium')
        artist   = UserFactory(is_artist=True, subscription_plan='free')
        db.session.commit()
        with app.app_context():
            headers = {'Authorization': f'Bearer {create_access_token(identity=str(producer.id))}',
                       'Content-Type': 'application/json'}

        link = self._make_roster_link(db, producer, artist)
        contract = UserContract(user_id=producer.id, title='Cession', contract_type='exploitation')
        db.session.add(contract)
        db.session.commit()

        resp = client.post(
            f'/api/roster/{link.id}/attach-contract',
            json={'contract_id': contract.id},
            headers=headers,
        )
        assert resp.status_code == 400

        db.session.delete(contract)
        db.session.delete(link)
        db.session.commit()
        _teardown_user(db, artist)
        _teardown_user(db, producer)

    def test_l_artiste_ne_peut_pas_attacher_le_contrat(self, client, db, app, bound_factories):
        from flask_jwt_extended import create_access_token
        from models import UserContract
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user

        producer = UserFactory(is_producer=True, subscription_plan='premium')
        artist   = UserFactory(is_artist=True, subscription_plan='premium')
        db.session.commit()
        with app.app_context():
            headers = {'Authorization': f'Bearer {create_access_token(identity=str(artist.id))}',
                       'Content-Type': 'application/json'}

        link = self._make_roster_link(db, producer, artist)
        contract = UserContract(user_id=producer.id, title='Mandat', contract_type='management')
        db.session.add(contract)
        db.session.commit()

        resp = client.post(
            f'/api/roster/{link.id}/attach-contract',
            json={'contract_id': contract.id},
            headers=headers,
        )
        assert resp.status_code == 403

        db.session.delete(contract)
        db.session.delete(link)
        db.session.commit()
        _teardown_user(db, artist)
        _teardown_user(db, producer)
