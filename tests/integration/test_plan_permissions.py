"""
Tests d'AUTORISATION des paliers sur les routes réelles.

test_plans.py vérifie la matrice au niveau du modèle ; ici on vérifie que les
routes l'appliquent vraiment. Un `can_*` correct qu'aucune route n'interroge ne
protège rien : c'est exactement le trou qui existait sur les prix de droits.
"""
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_access_token

from models import User, UserContract
from utils import plans


@pytest.fixture()
def set_plan(db, user):
    """Positionne le palier du vendeur du conftest."""
    def _set(plan, active=True):
        user.subscription_plan = plan
        user.premium_expires_at = (
            datetime.now() + timedelta(days=10) if active
            else datetime.now() - timedelta(days=1)
        )
        db.session.commit()
        return user
    yield _set
    # Les contrats créés par les tests référencent l'utilisateur : les purger
    # avant que le teardown du conftest ne tente de nullifier user_contract.user_id.
    UserContract.query.filter_by(user_id=user.id).delete()
    db.session.commit()


class TestTarificationDesDroits:
    """Fixer le prix de ses droits = Premium et plus.

    C'était la faille : seul contract_price_exclusive était contrôlé, les NEUF
    autres champs de prix passaient sans aucune vérification — un compte gratuit
    pouvait déjà tarifer ses droits à la carte.
    """

    @pytest.mark.parametrize('field', [
        'contract_price_duration_10y',
        'contract_price_lifetime',
        'contract_price_mechanical',
        'contract_price_public_show',
        'contract_price_arrangement',
        'contract_price_territory_world',
    ])
    def test_compte_gratuit_ne_peut_pas_fixer_ses_prix(self, client, set_plan,
                                                       auth_headers, field):
        set_plan(plans.FREE)
        headers = {k: v for k, v in auth_headers.items() if k != 'Content-Type'}

        res = client.post('/api/tracks/post', data={'title': 'Test', field: '50'},
                          headers=headers, content_type='multipart/form-data')

        assert res.status_code == 403
        assert res.get_json()['code'] == 'PREMIUM_REQUIRED'

    def test_compte_gratuit_ne_peut_pas_proposer_l_exclusivite(self, client, set_plan,
                                                               auth_headers):
        set_plan(plans.FREE)
        headers = {k: v for k, v in auth_headers.items() if k != 'Content-Type'}

        res = client.post('/api/tracks/post',
                          data={'title': 'Test', 'contract_price_exclusive': '150'},
                          headers=headers, content_type='multipart/form-data')

        assert res.status_code == 403

    def test_abonnement_expire_perd_le_droit(self, client, set_plan, auth_headers):
        """Payer hier ne donne pas de droits aujourd'hui."""
        set_plan(plans.PRO_STRUCTURE, active=False)
        headers = {k: v for k, v in auth_headers.items() if k != 'Content-Type'}

        res = client.post('/api/tracks/post',
                          data={'title': 'Test', 'contract_price_exclusive': '150'},
                          headers=headers, content_type='multipart/form-data')

        assert res.status_code == 403


class TestContractBuilder:
    """Semi-Pro : 1 contrat/mois. Pro Structuré : illimité. Free/Premium : aucun accès."""

    def _create(self, client, headers):
        return client.post('/api/contract-builder/contracts',
                           json={'title': 'Cession', 'contract_type': 'cession'},
                           headers=headers)

    @pytest.mark.parametrize('plan', [plans.FREE, plans.PREMIUM])
    def test_free_et_premium_n_ont_pas_acces(self, client, set_plan, auth_headers, plan):
        set_plan(plan)
        res = self._create(client, auth_headers)
        assert res.status_code == 403

    def test_semi_pro_peut_creer_un_contrat(self, client, set_plan, auth_headers):
        set_plan(plans.SEMI_PRO)
        assert self._create(client, auth_headers).status_code in (200, 201)

    def test_semi_pro_bloque_au_deuxieme_contrat_du_mois(self, client, db, set_plan,
                                                         auth_headers):
        """Le quota est ce qui convertit un semi-pro devenu structure."""
        user = set_plan(plans.SEMI_PRO)

        first = self._create(client, auth_headers)
        assert first.status_code in (200, 201)

        second = self._create(client, auth_headers)
        assert second.status_code == 403
        assert second.get_json()['code'] == 'CONTRACT_QUOTA_REACHED'

    def test_pro_structure_est_illimite(self, client, set_plan, auth_headers):
        set_plan(plans.PRO_STRUCTURE)
        for _ in range(3):
            assert self._create(client, auth_headers).status_code in (200, 201)

    def test_le_quota_ne_compte_que_le_mois_en_cours(self, client, db, set_plan,
                                                     auth_headers):
        """Un contrat créé le mois dernier ne doit pas bloquer ce mois-ci."""
        user = set_plan(plans.SEMI_PRO)

        vieux = UserContract(user_id=user.id, title='Vieux', contract_type='cession')
        db.session.add(vieux)
        db.session.flush()
        vieux.created_at = datetime.now() - timedelta(days=45)
        db.session.commit()

        assert self._create(client, auth_headers).status_code in (200, 201)


class TestCapacitesExposees:
    """Le front lit les capacités du serveur ; il ne les redérive pas."""

    def test_me_expose_les_capacites(self, client, set_plan, auth_headers):
        set_plan(plans.SEMI_PRO)
        res = client.get('/api/premium/status', headers=auth_headers)

        caps = res.get_json()['data']['capabilities']
        assert caps['can_set_custom_prices']    is True
        assert caps['can_use_contract_builder'] is True
        assert caps['contract_quota']           == 1

    def test_me_expose_aussi_les_capacites(self, client, set_plan, auth_headers):
        """Gap corrigé : login/register/`/me` ne renvoyaient PAS `capabilities`,
        seul `/api/premium/status` (ou le profil public en vue propriétaire) le
        faisait — un guard front lu juste après connexion pouvait donc bloquer
        à tort un utilisateur qui avait pourtant le droit."""
        set_plan(plans.PREMIUM)
        res = client.get('/api/auth/me', headers=auth_headers)

        caps = res.get_json()['data']['user']['capabilities']
        assert caps['can_use_management_contract'] is True
        assert caps['can_view_royalties']           is True

    def test_grille_tarifaire_est_publique(self, client):
        """Cacher ses prix derrière un mur d'inscription est le contraire d'une
        relation de confiance : un visiteur doit pouvoir comparer avant de créer
        un compte."""
        res = client.get('/api/premium/plans')   # aucun header d'authentification

        assert res.status_code == 200
        keys = [p['key'] for p in res.get_json()['data']['plans']]
        assert keys == list(plans.PLAN_ORDER)
