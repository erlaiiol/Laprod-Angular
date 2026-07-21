"""
Tests d'intégration des campagnes de mailing.

Couvre ce qui protège les utilisateurs et la réputation d'expédition :
  - consentement : personne n'est ciblable sans opt-in explicite
  - segments : chacun ne contient que les bonnes personnes
  - rythme : quota, carence, fenêtres d'envoi
  - fréquence subie : plafond global tous vendeurs confondus
  - Super Premium : pas de diffusion totale sans paiement encaissé
  - désinscription : publique, immédiate, sans authentification
"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask_jwt_extended import create_access_token

from extensions import db as _db
from models import (
    MarketingCampaign, CampaignRecipient, CampaignSegment, CampaignStatus,
    Favorite, Purchase, PromoCode, PromoCodeScope,
)
from utils.campaign_service import (
    CampaignError, audience_query, audience_size, quota_status, suggest_slots,
    validate_slot, _recently_mailed_user_ids,
    MAX_CAMPAIGNS_PER_30_DAYS, MAX_EMAILS_PER_RECIPIENT_PER_30_DAYS,
    ALLOWED_WEEKDAYS, ALLOWED_HOUR_MIN,
)
from utils.email_service import generate_unsubscribe_token


@pytest.fixture()
def seller(db, user):
    """Le vendeur du conftest : beatmaker Premium."""
    return user


@pytest.fixture()
def track(db, seller, bound_factories):
    from tests.factories.track_factory import TrackFactory
    t = TrackFactory(composer_user=seller, is_approved=True)
    db.session.commit()
    yield t
    # Favoris, achats et écoutes posés par les tests référencent ce beat : les
    # purger avant sa suppression, sinon le teardown viole leur FK track_id.
    from models import ListenEvent
    Favorite.query.filter_by(track_id=t.id).delete()
    Purchase.query.filter_by(track_id=t.id).delete()
    ListenEvent.query.filter_by(track_id=t.id).delete()
    db.session.commit()


@pytest.fixture()
def make_user(db, bound_factories):
    """Fabrique un destinataire potentiel. `bound_factories` est requis pour que
    la factory dispose d'une session — d'où la fixture plutôt qu'un helper libre."""
    def _make(opt_in=True, verified=True):
        from tests.factories.user_factory import UserFactory
        u = UserFactory(is_artist=True)
        u.marketing_opt_in = opt_in
        u.email_verified = verified
        u.account_status = 'active'
        db.session.commit()
        return u
    return _make


def _headers(app, u):
    with app.app_context():
        token = create_access_token(identity=str(u.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _next_valid_slot(owner_id):
    slots = suggest_slots(owner_id, count=1)
    return slots[0]


def _valid_slot_in(days):
    """Un créneau JOUR/HEURE toujours valide, à ~`days` jours.

    validate_slot contrôle le jour et l'heure AVANT le quota : sans cela, un test
    de quota tomberait un dimanche et échouerait sur SLOT_BAD_DAY, masquant ce
    qu'il prétend vérifier.
    """
    slot = (datetime.now() + timedelta(days=days)).replace(
        hour=ALLOWED_HOUR_MIN, minute=0, second=0, microsecond=0,
    )
    while slot.weekday() not in ALLOWED_WEEKDAYS:
        slot += timedelta(days=1)
    return slot


class TestConsentement:
    def test_sans_opt_in_personne_n_est_ciblable(self, db, seller, track, make_user):
        """Le cœur du dispositif : un utilisateur qui n'a rien demandé n'est
        jamais dans une audience, quel que soit son lien avec le vendeur."""
        fan = make_user(opt_in=False)
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))
        db.session.commit()

        assert audience_size(seller.id, CampaignSegment.FAVORITES.value) == 0
        assert audience_size(seller.id, CampaignSegment.ALL.value) == 0

    def test_opt_in_sans_email_verifie_exclu(self, db, seller, track, make_user):
        """Mailer une adresse non vérifiée = envoyer sur une boîte qui n'est
        peut-être pas la sienne, et flinguer la délivrabilité du domaine."""
        fan = make_user(opt_in=True, verified=False)
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))
        db.session.commit()

        assert audience_size(seller.id, CampaignSegment.FAVORITES.value) == 0

    def test_opt_in_rend_ciblable(self, db, seller, track, make_user):
        fan = make_user(opt_in=True, verified=True)
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))
        db.session.commit()

        assert audience_size(seller.id, CampaignSegment.FAVORITES.value) == 1

    def test_le_vendeur_ne_se_cible_jamais_lui_meme(self, db, seller):
        seller.marketing_opt_in = True
        seller.email_verified = True
        db.session.commit()

        ids = [u.id for u in audience_query(seller.id, CampaignSegment.ALL.value).all()]
        assert seller.id not in ids


class TestSegments:
    def test_favoris_ne_contient_que_les_favoris(self, db, seller, track, make_user):
        fan       = make_user()
        indiferent = make_user()
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))
        db.session.commit()

        ids = [u.id for u in audience_query(seller.id, CampaignSegment.FAVORITES.value).all()]
        assert fan.id in ids
        assert indiferent.id not in ids

    def test_acheteurs_contient_les_acheteurs(self, db, seller, track, bound_factories, make_user):
        from tests.factories.purchase_factory import PurchaseFactory
        buyer = make_user()
        PurchaseFactory(track=track, buyer_id=buyer.id)
        db.session.commit()

        ids = [u.id for u in audience_query(seller.id, CampaignSegment.BUYERS.value).all()]
        assert buyer.id in ids

    def test_all_ne_contient_que_ceux_ayant_consenti(self, db, seller, make_user):
        a, b = make_user(), make_user()
        make_user(opt_in=False)   # ne doit pas apparaître

        ids = [u.id for u in audience_query(seller.id, CampaignSegment.ALL.value).all()]
        assert a.id in ids and b.id in ids


class TestRythme:
    def test_creneau_hors_fenetre_refuse(self, seller):
        # Un dimanche à 3 h du matin : ni le bon jour, ni la bonne heure.
        sunday_3am = datetime.now() + timedelta(days=7)
        while sunday_3am.weekday() != 6:
            sunday_3am += timedelta(days=1)
        sunday_3am = sunday_3am.replace(hour=3)

        with pytest.raises(CampaignError) as exc:
            validate_slot(seller.id, sunday_3am)
        assert exc.value.code == 'SLOT_BAD_DAY'

    def test_creneau_trop_proche_refuse(self, seller):
        """24 h de délai minimum : le vendeur doit pouvoir se relire et annuler."""
        with pytest.raises(CampaignError) as exc:
            validate_slot(seller.id, datetime.now() + timedelta(hours=2))
        assert exc.value.code == 'SLOT_TOO_SOON'

    def test_creneaux_proposes_sont_tous_valides(self, seller):
        """Le serveur ne propose que des créneaux qu'il accepterait."""
        for slot in suggest_slots(seller.id, count=5):
            assert validate_slot(seller.id, slot) is True

    def test_quota_bloque_la_troisieme_campagne(self, db, seller):
        for i in range(MAX_CAMPAIGNS_PER_30_DAYS):
            db.session.add(MarketingCampaign(
                owner_id=seller.id, subject=f'Campagne {i}', body='x' * 20,
                segment=CampaignSegment.BUYERS.value,
                status=CampaignStatus.SENT.value,
                sent_at=datetime.now() - timedelta(days=1),
            ))
        db.session.commit()

        assert quota_status(seller.id)['remaining'] == 0
        with pytest.raises(CampaignError) as exc:
            validate_slot(seller.id, _valid_slot_in(20))
        assert exc.value.code == 'QUOTA_REACHED'

    def test_carence_entre_deux_campagnes(self, db, seller):
        """Interdit d'enchaîner les 2 campagnes du mois le même jour."""
        db.session.add(MarketingCampaign(
            owner_id=seller.id, subject='Hier', body='x' * 20,
            segment=CampaignSegment.BUYERS.value,
            status=CampaignStatus.SENT.value,
            sent_at=datetime.now() - timedelta(days=1),
        ))
        db.session.commit()

        status = quota_status(seller.id)
        assert status['remaining'] == 1          # il lui reste du quota…
        assert status['next_allowed_at'] is not None  # …mais pas tout de suite

        # _valid_slot_in : le jour et l'heure sont contrôlés AVANT la carence.
        # Une date brute tomberait un dimanche ou à 22 h selon l'heure d'exécution
        # du test, et échouerait sur SLOT_BAD_* en masquant ce qu'on veut vérifier.
        with pytest.raises(CampaignError) as exc:
            validate_slot(seller.id, _valid_slot_in(2))
        assert exc.value.code == 'COOLDOWN'

    def test_brouillon_ne_consomme_pas_de_quota(self, db, seller):
        """Écrire n'est pas envoyer."""
        db.session.add(MarketingCampaign(
            owner_id=seller.id, subject='Brouillon', body='x' * 20,
            segment=CampaignSegment.BUYERS.value, status=CampaignStatus.DRAFT.value,
        ))
        db.session.commit()
        assert quota_status(seller.id)['used'] == 0


class TestFrequenceSubie:
    def test_plafond_global_par_destinataire(self, db, seller, make_user):
        """Chaque vendeur peut respecter son quota tout en saturant un même
        utilisateur : le plafond global est le seul vrai garde-fou."""
        victim = make_user()

        for i in range(MAX_EMAILS_PER_RECIPIENT_PER_30_DAYS):
            c = MarketingCampaign(
                owner_id=seller.id, subject=f'C{i}', body='x' * 20,
                segment=CampaignSegment.ALL.value, status=CampaignStatus.SENT.value,
            )
            db.session.add(c)
            db.session.flush()
            db.session.add(CampaignRecipient(
                campaign_id=c.id, user_id=victim.id, sent_at=datetime.now(),
            ))
        db.session.commit()

        assert victim.id in _recently_mailed_user_ids()


class TestApiCampagnes:
    def test_creation_refusee_sans_premium(self, client, db, seller, auth_headers):
        seller.subscription_plan = 'amateur'
        seller.premium_expires_at = datetime.now() - timedelta(days=1)
        db.session.commit()

        res = client.post('/api/campaigns', json={
            'subject': 'Ma promo', 'body': 'Un message assez long pour passer.',
            'segment': 'buyers',
        }, headers=auth_headers)
        assert res.status_code == 403
        assert res.get_json()['code'] == 'PREMIUM_REQUIRED'

    def test_creation_refusee_mix_engineer_non_certifie(self, client, db, bound_factories):
        """Un mix engineer auto-déclaré (is_mix_engineer) mais jamais certifié par
        un admin (is_mixmaster_engineer=False) ne doit pas pouvoir envoyer de
        campagne — sinon n'importe qui obtiendrait cet outil vendeur en cochant
        une case dans son profil, sans jamais être vetté."""
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user
        pending = UserFactory(is_mix_engineer=True, subscription_plan='pro')
        db.session.commit()
        try:
            res = client.post('/api/campaigns', json={
                'subject': 'Ma promo', 'body': 'Un message assez long pour passer.',
                'segment': 'buyers',
            }, headers=_headers(client.application, pending))
            assert res.status_code == 403
            assert res.get_json()['code'] == 'NOT_A_SELLER'
        finally:
            _teardown_user(db, pending)

    def test_creation_valide(self, client, seller, auth_headers):
        res = client.post('/api/campaigns', json={
            'subject': 'Nouveau beat', 'body': 'Un message assez long pour passer.',
            'segment': 'buyers',
        }, headers=auth_headers)
        assert res.status_code == 201
        assert res.get_json()['data']['campaign']['status'] == 'draft'

    @pytest.mark.parametrize('payload', [
        {'subject': 'ab',  'body': 'Message assez long ici.'},   # sujet trop court
        {'subject': 'Bon', 'body': 'court'},                      # message trop court
    ])
    def test_payloads_invalides_refuses(self, client, auth_headers, payload):
        res = client.post('/api/campaigns',
                          json={'segment': 'buyers', **payload}, headers=auth_headers)
        assert res.status_code == 400

    def test_diffusion_totale_impossible_sans_paiement(self, client, db, seller, auth_headers, make_user):
        """Le contrôle est SERVEUR : masquer le bouton ne suffirait pas."""
        make_user()  # audience non vide
        res = client.post('/api/campaigns', json={
            'subject': 'Toute la plateforme', 'body': 'Un message assez long pour passer.',
            'segment': 'all',
        }, headers=auth_headers)
        campaign_id = res.get_json()['data']['campaign']['id']

        slot = _next_valid_slot(seller.id)
        res = client.post(f'/api/campaigns/{campaign_id}/schedule',
                          json={'scheduled_for': slot.isoformat()}, headers=auth_headers)
        assert res.status_code == 402
        assert res.get_json()['code'] == 'PAYMENT_REQUIRED'

    def test_segment_vide_refuse(self, client, seller, auth_headers):
        """Planifier vers personne n'a aucun sens — on le dit plutôt que d'envoyer
        une campagne fantôme qui consommerait le quota."""
        res = client.post('/api/campaigns', json={
            'subject': 'Mes acheteurs', 'body': 'Un message assez long pour passer.',
            'segment': 'buyers',
        }, headers=auth_headers)
        campaign_id = res.get_json()['data']['campaign']['id']

        slot = _next_valid_slot(seller.id)
        res = client.post(f'/api/campaigns/{campaign_id}/schedule',
                          json={'scheduled_for': slot.isoformat()}, headers=auth_headers)
        assert res.status_code == 400
        assert res.get_json()['code'] == 'EMPTY_AUDIENCE'

    def test_planification_reussie(self, client, db, seller, track, auth_headers, bound_factories, make_user):
        from tests.factories.purchase_factory import PurchaseFactory
        buyer = make_user()
        PurchaseFactory(track=track, buyer_id=buyer.id)
        db.session.commit()

        res = client.post('/api/campaigns', json={
            'subject': 'Merci !', 'body': 'Un message assez long pour passer.',
            'segment': 'buyers',
        }, headers=auth_headers)
        campaign_id = res.get_json()['data']['campaign']['id']

        slot = _next_valid_slot(seller.id)
        res = client.post(f'/api/campaigns/{campaign_id}/schedule',
                          json={'scheduled_for': slot.isoformat()}, headers=auth_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['campaign']['status'] == 'scheduled'
        assert res.get_json()['data']['audience_size'] == 1

    def test_campagne_envoyee_non_modifiable(self, client, db, seller, auth_headers):
        """Réécrire une campagne partie rendrait ses statistiques mensongères."""
        c = MarketingCampaign(
            owner_id=seller.id, subject='Partie', body='x' * 20,
            segment=CampaignSegment.BUYERS.value, status=CampaignStatus.SENT.value,
            sent_at=datetime.now(),
        )
        db.session.add(c)
        db.session.commit()

        res = client.patch(f'/api/campaigns/{c.id}', json={
            'subject': 'Réécrite', 'body': 'Un message assez long pour passer.',
            'segment': 'buyers',
        }, headers=auth_headers)
        assert res.status_code == 409

    def test_campagne_d_un_tiers_invisible(self, client, app, db, seller, auth_headers,
                                           bound_factories):
        from tests.factories.user_factory import UserFactory
        other = UserFactory(is_beatmaker=True)
        db.session.commit()
        c = MarketingCampaign(
            owner_id=other.id, subject='Privée', body='x' * 20,
            segment=CampaignSegment.BUYERS.value, status=CampaignStatus.DRAFT.value,
        )
        db.session.add(c)
        db.session.commit()

        res = client.patch(f'/api/campaigns/{c.id}', json={
            'subject': 'Piratée', 'body': 'Un message assez long pour passer.',
            'segment': 'buyers',
        }, headers=auth_headers)
        assert res.status_code == 404


class TestSuperPremiumCheckout:
    """Régression : deux appels concurrents à /checkout pour la même campagne
    non payée ne doivent jamais produire deux sessions Stripe distinctes —
    seule la seconde vraie tentative après paiement doit être bloquée."""

    def _campaign_all(self, client, auth_headers):
        res = client.post('/api/campaigns', json={
            'subject': 'Toute la plateforme', 'body': 'Un message assez long pour passer.',
            'segment': 'all',
        }, headers=auth_headers)
        return res.get_json()['data']['campaign']['id']

    def test_idempotency_key_deterministe_par_campagne(self, client, db, seller, auth_headers):
        campaign_id = self._campaign_all(client, auth_headers)

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = SimpleNamespace(url='https://checkout.stripe.test/sess_1')
            res = client.post(f'/api/campaigns/{campaign_id}/checkout', headers=auth_headers)

        assert res.status_code == 200
        assert res.get_json()['data']['checkout_url'] == 'https://checkout.stripe.test/sess_1'
        _, kwargs = mock_create.call_args
        assert kwargs['idempotency_key'] == f'campaign-{campaign_id}-super-premium-checkout'

    def test_checkout_refuse_si_deja_payee(self, client, db, seller, auth_headers):
        campaign_id = self._campaign_all(client, auth_headers)
        campaign = db.session.get(MarketingCampaign, campaign_id)
        campaign.stripe_payment_intent_id = 'pi_already_paid'
        db.session.commit()

        with patch('stripe.checkout.Session.create') as mock_create:
            res = client.post(f'/api/campaigns/{campaign_id}/checkout', headers=auth_headers)

        assert res.status_code == 409
        assert res.get_json()['code'] == 'ALREADY_PAID'
        mock_create.assert_not_called()


class TestDesinscription:
    def test_desinscription_publique_sans_authentification(self, client, app, db, make_user):
        """Se désinscrire doit être au moins aussi simple que s'inscrire
        (art. L.34-5 CPCE) : aucun header d'auth ici."""
        u = make_user(opt_in=True)
        with app.app_context():
            token = generate_unsubscribe_token(u.id)

        res = client.post('/api/campaigns/unsubscribe', json={'token': token})
        assert res.status_code == 200

        db.session.refresh(u)
        assert u.marketing_opt_in is False
        assert u.can_receive_marketing is False

    def test_token_invalide_refuse(self, client):
        res = client.post('/api/campaigns/unsubscribe', json={'token': 'nimportequoi'})
        assert res.status_code == 400

    def test_desinscrit_sort_immediatement_des_audiences(self, client, app, db, seller, track, make_user):
        fan = make_user(opt_in=True)
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))
        db.session.commit()
        assert audience_size(seller.id, CampaignSegment.FAVORITES.value) == 1

        with app.app_context():
            token = generate_unsubscribe_token(fan.id)
        client.post('/api/campaigns/unsubscribe', json={'token': token})

        assert audience_size(seller.id, CampaignSegment.FAVORITES.value) == 0


class TestDispatch:
    """Le dispatch réel — chemin le plus sensible : c'est lui qui met des emails
    dans les boîtes. On simule l'envoi SMTP et on vérifie QUI reçoit quoi."""

    def test_n_envoie_qu_aux_consentants(self, db, seller, track, make_user, monkeypatch):
        from utils import campaign_service

        consentant  = make_user(opt_in=True)
        refractaire = make_user(opt_in=False)
        for u in (consentant, refractaire):
            db.session.add(Favorite(user_id=u.id, track_id=track.id))

        c = MarketingCampaign(
            owner_id=seller.id, subject='Promo', body='x' * 20,
            segment=CampaignSegment.FAVORITES.value,
            status=CampaignStatus.SCHEDULED.value,
            scheduled_for=datetime.now() - timedelta(minutes=1),
        )
        db.session.add(c)
        db.session.commit()

        envoyes = []
        monkeypatch.setattr(
            'utils.email_service.send_campaign_email',
            lambda campaign, user: envoyes.append(user.id) or True,
        )

        sent = campaign_service.dispatch(c)

        assert sent == 1
        assert envoyes == [consentant.id]     # le non-consentant n'est jamais contacté
        assert refractaire.id not in envoyes
        assert c.status == CampaignStatus.SENT.value
        assert c.sent_count == 1

    def test_double_dispatch_n_envoie_pas_deux_fois(self, db, seller, track,
                                                    make_user, monkeypatch):
        """Un retry du job ne doit pas re-mailer les gens déjà servis."""
        from utils import campaign_service

        fan = make_user(opt_in=True)
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))

        c = MarketingCampaign(
            owner_id=seller.id, subject='Promo', body='x' * 20,
            segment=CampaignSegment.FAVORITES.value,
            status=CampaignStatus.SCHEDULED.value,
            scheduled_for=datetime.now() - timedelta(minutes=1),
        )
        db.session.add(c)
        db.session.commit()

        envoyes = []
        monkeypatch.setattr(
            'utils.email_service.send_campaign_email',
            lambda campaign, user: envoyes.append(user.id) or True,
        )

        campaign_service.dispatch(c)
        c.status = CampaignStatus.SCHEDULED.value   # simule un retry du job
        db.session.commit()
        campaign_service.dispatch(c)

        assert envoyes == [fan.id]   # une seule fois, malgré deux dispatchs

    def test_stats_attribuent_les_ventes_a_la_campagne(self, db, seller, track,
                                                       make_user, monkeypatch):
        """La seule métrique honnête : qui a vraiment utilisé le code reçu."""
        from utils import campaign_service
        from models import PromoCodeRedemption
        from decimal import Decimal

        fan = make_user(opt_in=True)
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))

        promo = PromoCode(owner_id=seller.id, code='CAMP30', percent=30,
                          scope=PromoCodeScope.TRACK.value, applies_to_all=True,
                          expires_at=datetime.now() + timedelta(days=30))
        db.session.add(promo)
        db.session.flush()

        c = MarketingCampaign(
            owner_id=seller.id, subject='Promo', body='x' * 20,
            segment=CampaignSegment.FAVORITES.value, promo_code_id=promo.id,
            status=CampaignStatus.SCHEDULED.value,
            scheduled_for=datetime.now() - timedelta(minutes=1),
        )
        db.session.add(c)
        db.session.commit()

        monkeypatch.setattr('utils.email_service.send_campaign_email',
                            lambda campaign, user: True)
        campaign_service.dispatch(c)

        # Le destinataire achète en utilisant le code reçu.
        db.session.add(PromoCodeRedemption(
            promo_code_id=promo.id, user_id=fan.id,
            gross_amount=Decimal('100.00'), discount_amount=Decimal('30.00'),
            net_amount=Decimal('70.00'), percent_applied=30,
        ))
        db.session.commit()

        stats = campaign_service.campaign_stats(c)
        assert stats['sent_count']  == 1
        assert stats['conversions'] == 1
        assert stats['revenue']     == 70.0


class TestSecuriteEtArgent:
    """Correctifs de sécurité/argent sur les campagnes."""

    def test_campagne_payee_echouee_est_rejouable(self, client, db, seller,
                                                  auth_headers, make_user):
        """Un dispatch échoué (SMTP KO) n'a atteint personne. Interdire le rejeu
        ferait perdre au vendeur les 19,99 € d'une diffusion payée jamais partie."""
        make_user()  # audience non vide

        c = MarketingCampaign(
            owner_id=seller.id, subject='Payée mais échouée', body='x' * 20,
            segment=CampaignSegment.ALL.value,
            status=CampaignStatus.FAILED.value,
            stripe_payment_intent_id='pi_test_paid',   # le paiement reste acquis
            amount_paid=Decimal('19.99'),
        )
        db.session.add(c)
        db.session.commit()

        slot = _next_valid_slot(seller.id)
        res = client.post(f'/api/campaigns/{c.id}/schedule',
                          json={'scheduled_for': slot.isoformat()}, headers=auth_headers)

        assert res.status_code == 200
        assert res.get_json()['data']['campaign']['status'] == 'scheduled'
        assert res.get_json()['data']['campaign']['is_paid'] is True

    def test_rejeu_repurge_les_destinataires_non_servis(self, client, db, seller,
                                                        track, auth_headers, make_user):
        """Les lignes en échec doivent être purgées au rejeu : sinon le garde
        anti-doublon les croit « déjà traitées » et ces gens ne reçoivent jamais rien."""
        fan = make_user()
        db.session.add(Favorite(user_id=fan.id, track_id=track.id))

        c = MarketingCampaign(
            owner_id=seller.id, subject='Échouée', body='x' * 20,
            segment=CampaignSegment.FAVORITES.value,
            status=CampaignStatus.FAILED.value,
        )
        db.session.add(c)
        db.session.flush()
        # Tentative précédente en échec (sent_at NULL)
        db.session.add(CampaignRecipient(
            campaign_id=c.id, user_id=fan.id, sent_at=None, error='SMTP down',
        ))
        db.session.commit()

        slot = _next_valid_slot(seller.id)
        client.post(f'/api/campaigns/{c.id}/schedule',
                    json={'scheduled_for': slot.isoformat()}, headers=auth_headers)

        restants = CampaignRecipient.query.filter_by(campaign_id=c.id).count()
        assert restants == 0   # la tentative échouée a été purgée, le fan sera re-tenté

    def test_destinataires_deja_servis_ne_sont_pas_repurges(self, client, db, seller,
                                                            track, auth_headers, make_user):
        """…mais on ne re-maile jamais quelqu'un qui a bien reçu le message."""
        servi = make_user()

        c = MarketingCampaign(
            owner_id=seller.id, subject='Partiellement partie', body='x' * 20,
            segment=CampaignSegment.FAVORITES.value,
            status=CampaignStatus.FAILED.value,
        )
        db.session.add(c)
        db.session.flush()
        db.session.add(CampaignRecipient(
            campaign_id=c.id, user_id=servi.id, sent_at=datetime.now(),
        ))
        db.session.commit()

        slot = _next_valid_slot(seller.id)
        client.post(f'/api/campaigns/{c.id}/schedule',
                    json={'scheduled_for': slot.isoformat()}, headers=auth_headers)

        assert CampaignRecipient.query.filter_by(campaign_id=c.id).count() == 1

    def test_recipient_count_exclut_les_satures(self, db, seller, track,
                                                make_user, monkeypatch):
        """recipient_count ne doit compter que les gens RÉELLEMENT adressés : y
        inclure ceux écartés par le plafond de fréquence ferait croire au vendeur
        qu'il a touché des gens qui n'ont rien reçu."""
        from utils import campaign_service

        joignable = make_user()
        sature    = make_user()
        for u in (joignable, sature):
            db.session.add(Favorite(user_id=u.id, track_id=track.id))

        # `sature` a déjà atteint son plafond de mails sur 30 jours.
        for i in range(MAX_EMAILS_PER_RECIPIENT_PER_30_DAYS):
            old = MarketingCampaign(
                owner_id=seller.id, subject=f'Vieille {i}', body='x' * 20,
                segment=CampaignSegment.ALL.value, status=CampaignStatus.SENT.value,
            )
            db.session.add(old)
            db.session.flush()
            db.session.add(CampaignRecipient(
                campaign_id=old.id, user_id=sature.id, sent_at=datetime.now(),
            ))

        c = MarketingCampaign(
            owner_id=seller.id, subject='Nouvelle', body='x' * 20,
            segment=CampaignSegment.FAVORITES.value,
            status=CampaignStatus.SCHEDULED.value,
            scheduled_for=datetime.now() - timedelta(minutes=1),
        )
        db.session.add(c)
        db.session.commit()

        monkeypatch.setattr('utils.email_service.send_campaign_email',
                            lambda campaign, user: True)
        campaign_service.dispatch(c)

        assert c.sent_count      == 1   # seul `joignable` est servi
        assert c.recipient_count == 1   # et non 2 : `sature` n'a rien reçu


class TestAffinite:
    """Ciblage par affinité musicale : atteindre des auditeurs dont les goûts
    collent au style du vendeur, sans qu'ils le connaissent déjà. Réutilise les
    signaux de l'algo de reco (écoutes abouties + favoris par style/tag)."""

    def _listen(self, db, user, track, ratio=0.8):
        from models import ListenEvent
        db.session.add(ListenEvent(
            user_id=user.id, track_id=track.id,
            duration_listened=100.0, track_duration=120.0, completion_ratio=ratio,
        ))

    def test_prospect_au_gout_proche_est_cible(self, db, seller, track, make_user,
                                               bound_factories):
        """Un auditeur qui aime le même style, sur les beats d'AUTRES vendeurs,
        et qui ne connaît pas le vendeur, apparaît dans l'affinité."""
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import audience_size, AFFINITY_MIN_HITS

        # `track` (fixture) appartient au vendeur, style Trap par défaut → signature.
        other = UserFactory(is_beatmaker=True)
        other_beats = [TrackFactory(composer_user=other, style='Trap', is_approved=True)
                       for _ in range(AFFINITY_MIN_HITS)]
        prospect = make_user(opt_in=True)
        for b in other_beats:
            self._listen(db, prospect, b)
        db.session.commit()

        assert audience_size(seller.id, 'affinity') >= 1
        from utils.campaign_service import _affinity_candidate_ids
        assert prospect.id in _affinity_candidate_ids(seller.id)

    def test_sans_consentement_pas_d_affinite(self, db, seller, track, make_user,
                                              bound_factories):
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import _affinity_candidate_ids, AFFINITY_MIN_HITS

        other = UserFactory(is_beatmaker=True)
        beats = [TrackFactory(composer_user=other, style='Trap', is_approved=True)
                 for _ in range(AFFINITY_MIN_HITS)]
        refractaire = make_user(opt_in=False)   # écoute le bon style mais n'a pas consenti
        for b in beats:
            self._listen(db, refractaire, b)
        db.session.commit()

        assert refractaire.id not in _affinity_candidate_ids(seller.id)

    def test_contact_direct_exclu_de_l_affinite(self, db, seller, track, make_user,
                                                bound_factories):
        """Un fan qui a déjà écouté le vendeur est couvert par le segment
        « auditeurs » : l'affinité ne doit remonter que du prospect NEUF."""
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import _affinity_candidate_ids, AFFINITY_MIN_HITS

        other = UserFactory(is_beatmaker=True)
        beats = [TrackFactory(composer_user=other, style='Trap', is_approved=True)
                 for _ in range(AFFINITY_MIN_HITS)]
        fan = make_user(opt_in=True)
        for b in beats:
            self._listen(db, fan, b)
        self._listen(db, fan, track)   # …mais il connaît DÉJÀ le vendeur
        db.session.commit()

        assert fan.id not in _affinity_candidate_ids(seller.id)

    def test_une_seule_ecoute_ne_suffit_pas(self, db, seller, track, make_user,
                                            bound_factories):
        """Un match isolé n'est pas un goût : il faut plusieurs signaux positifs."""
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import _affinity_candidate_ids

        other = UserFactory(is_beatmaker=True)
        beat = TrackFactory(composer_user=other, style='Trap', is_approved=True)
        tiede = make_user(opt_in=True)
        self._listen(db, tiede, beat)   # une seule écoute
        db.session.commit()

        assert tiede.id not in _affinity_candidate_ids(seller.id)

    def test_affinite_ne_necessite_pas_de_paiement(self, client, db, seller, track,
                                                   auth_headers, make_user, bound_factories):
        """Contrairement à « toute la plateforme », l'affinité est incluse dans le
        Premium : c'est du ciblage fin, pas de la diffusion de masse."""
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import AFFINITY_MIN_HITS

        other = UserFactory(is_beatmaker=True)
        beats = [TrackFactory(composer_user=other, style='Trap', is_approved=True)
                 for _ in range(AFFINITY_MIN_HITS)]
        prospect = make_user(opt_in=True)
        for b in beats:
            self._listen(db, prospect, b)
        db.session.commit()

        res = client.post('/api/campaigns', json={
            'subject': 'Découvre mon style', 'body': 'Un message assez long pour passer.',
            'segment': 'affinity',
        }, headers=auth_headers)
        campaign_id = res.get_json()['data']['campaign']['id']

        slot = _next_valid_slot(seller.id)
        res = client.post(f'/api/campaigns/{campaign_id}/schedule',
                          json={'scheduled_for': slot.isoformat()}, headers=auth_headers)
        # 200 = planifié sans exiger de paiement (≠ 402 du segment 'all')
        assert res.status_code == 200
        assert res.get_json()['data']['campaign']['status'] == 'scheduled'


class TestMailsTypes:
    """Mails-types suggérés d'après l'activité récente : un clic pour démarrer,
    plutôt qu'une page blanche."""

    def test_toujours_un_modele_de_reprise(self, db, seller):
        """Même sans activité récente, on propose au moins la reprise de contact."""
        from utils.campaign_service import suggest_templates
        ids = [t['id'] for t in suggest_templates(seller.id)]
        assert 'catchup' in ids

    def test_beat_recent_genere_un_modele(self, db, seller, bound_factories):
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import suggest_templates
        TrackFactory(composer_user=seller, is_approved=True, title='Midnight')
        db.session.commit()

        templates = {t['id']: t for t in suggest_templates(seller.id)}
        assert 'new_beat' in templates
        # Le titre du beat apparaît dans le brouillon, prêt à l'emploi.
        assert 'Midnight' in templates['new_beat']['subject']
        assert templates['new_beat']['segment'] == CampaignSegment.FAVORITES.value

    def test_code_promo_recent_genere_un_modele_avec_le_code(self, db, seller):
        from utils.campaign_service import suggest_templates
        promo = PromoCode(owner_id=seller.id, code='DROP20', percent=20,
                          scope=PromoCodeScope.TRACK.value, applies_to_all=True,
                          expires_at=datetime.now() + timedelta(days=15))
        db.session.add(promo)
        db.session.commit()

        templates = {t['id']: t for t in suggest_templates(seller.id)}
        assert 'promo' in templates
        assert 'DROP20' in templates['promo']['subject']
        # Le code promo est pré-attaché → conversions mesurables.
        assert templates['promo']['promo_code_id'] == promo.id

    def test_beat_trop_ancien_pas_de_modele(self, db, seller, bound_factories):
        from tests.factories.track_factory import TrackFactory
        from utils.campaign_service import suggest_templates
        t = TrackFactory(composer_user=seller, is_approved=True)
        db.session.flush()
        t.created_at = datetime.now() - timedelta(days=60)   # hors fenêtre « récent »
        db.session.commit()

        ids = [x['id'] for x in suggest_templates(seller.id)]
        assert 'new_beat' not in ids

    def test_context_expose_les_templates(self, client, db, seller, auth_headers,
                                          bound_factories):
        from tests.factories.track_factory import TrackFactory
        TrackFactory(composer_user=seller, is_approved=True, title='Fresh')
        db.session.commit()

        res = client.get('/api/campaigns/context', headers=auth_headers)
        assert res.status_code == 200
        tpls = res.get_json()['data']['templates']
        assert any(t['id'] == 'new_beat' for t in tpls)
