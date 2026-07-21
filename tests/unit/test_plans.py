"""
Tests des paliers d'abonnement (utils/plans.py + capacités User).

Ces tests sont une matrice d'AUTORISATION : chaque assertion fausse est une
fonctionnalité payante donnée gratuitement, ou une fonctionnalité payée refusée.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from models import User
from utils import plans


def _user(plan, active=True):
    """Utilisateur porteur d'un palier, abonnement actif ou expiré."""
    expires = datetime.now() + timedelta(days=10) if active else datetime.now() - timedelta(days=1)
    return User(subscription_plan=plan, premium_expires_at=expires)


class TestNormalisation:
    def test_anciens_identifiants_migres(self):
        """Des lignes en base, des métadonnées Stripe et des JWT portent encore
        'amateur'/'pro'. Les ignorer rétrograderait silencieusement des abonnés."""
        assert plans.normalize('amateur') == plans.PREMIUM
        assert plans.normalize('pro')     == plans.PRO_STRUCTURE

    @pytest.mark.parametrize('bogus', ['', None, 'nimportequoi', 'PRO', 'pro_structuree'])
    def test_valeur_inconnue_retombe_sur_free(self, bogus):
        """Défense en profondeur : une valeur inattendue ne doit JAMAIS accorder
        des droits — elle retombe au palier le plus restrictif."""
        assert plans.normalize(bogus) == plans.FREE

    def test_rang_croissant(self):
        assert plans.plan_rank(plans.FREE) < plans.plan_rank(plans.PREMIUM)
        assert plans.plan_rank(plans.PREMIUM) < plans.plan_rank(plans.SEMI_PRO)
        assert plans.plan_rank(plans.SEMI_PRO) < plans.plan_rank(plans.PRO_STRUCTURE)


class TestGrilleTarifaire:
    def test_prix(self):
        assert plans.price_of(plans.FREE)          == Decimal('0')
        assert plans.price_of(plans.PREMIUM)       == Decimal('4.99')
        assert plans.price_of(plans.SEMI_PRO)      == Decimal('12.99')
        assert plans.price_of(plans.PRO_STRUCTURE) == Decimal('49.99')

    def test_prix_sont_des_decimal(self):
        """Un prix en float finirait par produire un montant Stripe faux."""
        for key in plans.PLAN_ORDER:
            assert isinstance(plans.price_of(key), Decimal)

    def test_catalogue_public_ordonne(self):
        keys = [p['key'] for p in plans.public_catalog()]
        assert keys == list(plans.PLAN_ORDER)


class TestMatriceDesCapacites:
    """La matrice d'autorisation, palier par palier."""

    @pytest.mark.parametrize('plan, custom_prices, exclusive, builder, mastering, quota', [
        (plans.FREE,          False, False, False, False, 0),
        (plans.PREMIUM,       True,  True,  False, False, 0),
        (plans.SEMI_PRO,      True,  True,  True,  True,  1),
        (plans.PRO_STRUCTURE, True,  True,  True,  True,  None),   # None = illimité
    ])
    def test_capacites(self, plan, custom_prices, exclusive, builder, mastering, quota):
        u = _user(plan)
        assert u.can_set_custom_prices    is custom_prices
        assert u.can_offer_exclusive      is exclusive
        assert u.can_use_contract_builder is builder
        assert u.can_do_mastering         is mastering
        assert u.contract_quota           == quota

    def test_semi_pro_a_le_badge_mastering(self):
        """Le « badge Mastering Pro » s'obtient par l'abonnement Semi-Pro, sans
        passer par la validation d'échantillon admin."""
        assert _user(plans.SEMI_PRO).can_do_mastering is True
        assert _user(plans.PREMIUM).can_do_mastering is False

    def test_certification_admin_donne_le_mastering_sans_abonnement(self):
        """…et l'autre voie reste ouverte : un certifié par l'admin garde son
        droit même sans payer."""
        u = _user(plans.FREE)
        u.is_certified_master_engineer = True
        assert u.can_do_mastering is True

    def test_seul_pro_structure_est_is_pro(self):
        assert _user(plans.PRO_STRUCTURE).is_pro is True
        assert _user(plans.SEMI_PRO).is_pro      is False

    @pytest.mark.parametrize('plan, management_contract, royalties', [
        (plans.FREE,          False, False),
        (plans.PREMIUM,       True,  True),
        (plans.SEMI_PRO,      True,  True),
        (plans.PRO_STRUCTURE, True,  True),
    ])
    def test_contrat_de_management_et_royalties_des_premium(self, plan, management_contract, royalties):
        """Le lien roster et le rétroplanning restent libres à tous les paliers
        (pas de capacité dédiée) — seule la formalisation par contrat et la
        consultation des royalties chiffrées sont réservées à Premium+."""
        u = _user(plan)
        assert u.can_use_management_contract is management_contract
        assert u.can_view_royalties          is royalties


class TestExpiration:
    """Un abonnement expiré ne donne AUCUN droit : payer hier ne donne pas de
    droits aujourd'hui. C'est le test qui empêche la fuite la plus coûteuse."""

    @pytest.mark.parametrize('plan', plans.PAID_PLANS)
    def test_abonnement_expire_retombe_a_free(self, plan):
        u = _user(plan, active=False)
        assert u.is_premium_active        is False
        assert u.can_set_custom_prices    is False
        assert u.can_offer_exclusive      is False
        assert u.can_use_contract_builder is False
        assert u.is_pro                   is False
        assert u.contract_quota           == 0

    def test_expiration_nulle_vaut_illimite(self):
        """premium_expires_at = None : abonnement sans échéance (accordé admin)."""
        u = User(subscription_plan=plans.SEMI_PRO, premium_expires_at=None)
        assert u.is_premium_active is True
        assert u.can_use_contract_builder is True


class TestQuotasDeTokens:
    """Les plafonds viennent de plans.py — pas de valeur recopiée dans models.py.
    Les attendus sont DÉRIVÉS de plans.py pour ne jamais rediverger au prochain
    ajustement de la grille."""

    @pytest.mark.parametrize('plan', plans.PLAN_ORDER)
    def test_apply_premium_tokens_monte_au_plafond(self, plan):
        p = plans.get(plan)
        u = _user(plan)
        u.upload_track_tokens = 0
        u.topline_tokens = 0
        u.apply_premium_tokens()
        assert u.upload_track_tokens == p.upload_cap
        assert u.topline_tokens      == p.topline_cap

    def test_semi_pro_a_des_toplines_quasi_illimitees(self):
        """Le palier de celui qui chante : 200 toplines/semaine, il n'en abusera pas."""
        assert plans.get(plans.SEMI_PRO).topline_cap == 200
        assert plans.get(plans.FREE).topline_cap == 5


class TestCadenceUpload:
    """Le quota d'upload est une CADENCE quotidienne, pas un plafond de catalogue.
    Le catalogue en ligne est illimité à tous les paliers."""

    @pytest.mark.parametrize('plan, per_day', [
        (plans.FREE,          1),
        (plans.PREMIUM,       2),
        (plans.SEMI_PRO,      10),
        (plans.PRO_STRUCTURE, 10),   # mêmes uploads que Semi-Pro : sa valeur, c'est le juridique
    ])
    def test_cadence_quotidienne_par_palier(self, plan, per_day):
        assert plans.get(plan).uploads_per_day == per_day

    def test_la_cadence_est_croissante_free_vers_semi_pro(self):
        """Débutant occasionnel → habitué → pro : le débit augmente avec le palier."""
        assert (plans.get(plans.FREE).uploads_per_day
                < plans.get(plans.PREMIUM).uploads_per_day
                < plans.get(plans.SEMI_PRO).uploads_per_day)

    def test_catalogue_illimite_a_tous_les_paliers(self):
        """La clarté que réclamait l'utilisateur : aucun plafond de beats en ligne."""
        for offer in plans.public_catalog():
            assert offer['catalogue_limit'] is None

    def test_user_expose_sa_cadence(self):
        u = _user(plans.SEMI_PRO)
        assert u.uploads_per_day == plans.get(plans.SEMI_PRO).uploads_per_day
        expired = _user(plans.SEMI_PRO, active=False)
        assert expired.uploads_per_day == plans.get(plans.FREE).uploads_per_day


class TestArgumentaire:
    """La grille est un document commercial : ces tests empêchent qu'un palier
    parte en production sans dire à qui il s'adresse ni pourquoi il vaut son prix."""

    @pytest.mark.parametrize('key', plans.PLAN_ORDER)
    def test_chaque_palier_a_une_typologie_et_un_argument(self, key):
        p = plans.get(key)
        assert p.audience  and len(p.audience) > 40,  f'{key}: typologie manquante'
        assert p.highlight and len(p.highlight) > 40, f'{key}: argument manquant'
        assert p.tagline,  f'{key}: accroche manquante'
        assert p.features, f'{key}: aucune fonctionnalité listée'

    def test_catalogue_public_expose_typologie_et_argument(self):
        """Le front les affiche : s'ils disparaissent du DTO, les cartes se vident."""
        for offer in plans.public_catalog():
            assert offer['audience']
            assert offer['highlight']

    def test_l_argument_du_pro_structure_porte_le_ratio(self):
        """L'argument massue d'une structure n'est pas une fonctionnalité, c'est le
        retour sur investissement : un contrat de juriste coûte 500 à 2 000 €."""
        assert '500' in plans.get(plans.PRO_STRUCTURE).highlight

    def test_l_argument_premium_porte_la_commission_sur_le_net(self):
        """Le vrai argument du Premium : la remise du vendeur n'est jamais taxée."""
        assert '10 %' in plans.get(plans.PREMIUM).highlight


class TestRegistreDeLangue:
    """Le registre n'est pas cosmétique : il signale à quel type de client on parle.

    Ces tests empêchent qu'un palier parte en prod avec un texte qui tutoie une
    SMAC, ou qui vouvoie un ado dans sa chambre.
    """

    @pytest.mark.parametrize('key', [plans.FREE, plans.PREMIUM, plans.SEMI_PRO])
    def test_les_paliers_particuliers_tutoient(self, key):
        assert plans.get(key).tone == plans.TONE_TU

    def test_le_palier_structure_vouvoie(self):
        """SMAC, festival, label : on ne tutoie pas une organisation qui
        contractualise ses intervenants — c'est déjà le registre du Contract
        Builder, leur outil."""
        assert plans.get(plans.PRO_STRUCTURE).tone == plans.TONE_VOUS

    @pytest.mark.parametrize('key', [plans.FREE, plans.PREMIUM, plans.SEMI_PRO])
    def test_le_texte_des_paliers_tu_ne_vouvoie_jamais(self, key):
        """Un « vous » qui traîne dans un texte au tutoiement se lit comme une
        faute, pas comme une nuance."""
        p = plans.get(key)
        texte = ' '.join([p.tagline, p.audience, p.highlight, *p.features]).lower()
        for interdit in (' vous ', ' votre ', ' vos '):
            assert interdit not in f' {texte} ', f'{key}: « {interdit.strip()} » trouvé'

    def test_le_texte_du_palier_structure_ne_tutoie_jamais(self):
        p = plans.get(plans.PRO_STRUCTURE)
        texte = ' '.join([p.tagline, p.audience, p.highlight, *p.features]).lower()
        for interdit in (' tu ', ' ton ', ' tes ', ' toi '):
            assert interdit not in f' {texte} ', f'pro_structure: « {interdit.strip()} » trouvé'

    def test_le_ton_est_expose_au_front(self):
        """Le front s'en sert pour ajuster les libellés de boutons."""
        tones = {o['key']: o['tone'] for o in plans.public_catalog()}
        assert tones[plans.SEMI_PRO]      == plans.TONE_TU
        assert tones[plans.PRO_STRUCTURE] == plans.TONE_VOUS


class TestTableauComparatif:
    """Le tableau à coches est servi au front : une case cochée doit correspondre
    à ce que l'API autorise réellement, sinon on ment au client."""

    def test_structure(self):
        m = plans.comparison_matrix()
        assert [c['key'] for c in m['columns']] == list(plans.PLAN_ORDER)
        assert m['groups'] and all(g['rows'] for g in m['groups'])

    def test_ligne_contract_builder_reflete_le_quota(self):
        m = plans.comparison_matrix()
        row = next(r for g in m['groups'] for r in g['rows'] if r['label'] == 'Contract Builder')
        cells = {plans.PLAN_ORDER[i]: row['cells'][i] for i in range(len(plans.PLAN_ORDER))}
        assert cells[plans.FREE]['kind'] == 'no'
        assert cells[plans.PREMIUM]['kind'] == 'no'
        assert cells[plans.SEMI_PRO]['text'] == '1 / mois'
        assert cells[plans.PRO_STRUCTURE]['text'] == 'Illimité'

    def test_catalogue_illimite_partout_dans_le_tableau(self):
        m = plans.comparison_matrix()
        row = next(r for g in m['groups'] for r in g['rows']
                   if r['label'] == 'Beats en ligne au total')
        assert all(c['text'] == 'Illimité' for c in row['cells'])

    def test_cases_cochees_correspondent_aux_capacites(self):
        """Pour chaque ligne oui/non, la coche doit matcher la capacité du User."""
        from models import User
        from datetime import datetime, timedelta
        m = plans.comparison_matrix()

        # Map libellé de ligne → attribut de capacité correspondant.
        bool_rows = {
            'Fixer le prix de chacun de tes droits':          'can_set_custom_prices',
            'Proposer tes beats en exclusivité':              'can_offer_exclusive',
            'Badge Mastering Pro':                            'can_do_mastering',
            'Contrat de management + royalties chiffrées':    'can_use_management_contract',
        }
        for g in m['groups']:
            for row in g['rows']:
                attr = bool_rows.get(row['label'])
                if not attr:
                    continue
                for i, key in enumerate(plans.PLAN_ORDER):
                    u = User(subscription_plan=key,
                             premium_expires_at=datetime.now() + timedelta(days=5))
                    checked = row['cells'][i]['kind'] == 'yes'
                    assert checked == getattr(u, attr), f'{row["label"]} / {key}'
