"""
Tests d'intégration des codes promo (routes/promo_api.py + utils/promo_service.py).

Couvre ce qui protège l'argent et le vendeur :
  - gating Premium (autorisation côté serveur, pas seulement UI)
  - unicité par vendeur (deux vendeurs peuvent avoir le même code)
  - périmètre (on ne remise pas le beat d'un tiers)
  - limites (expiration, quota atomique, once_per_user)
  - cohérence brut / remise / net
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token

from models import PromoCode, PromoCodeScope, PromoCodeRedemption
from utils.promo_service import apply_to_track, PromoError


@pytest.fixture()
def buyer(db, bound_factories):
    from tests.factories.user_factory import UserFactory
    from tests.scenarios import _teardown_user
    u = UserFactory(is_artist=True)
    db.session.commit()
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def buyer_headers(app, buyer):
    with app.app_context():
        token = create_access_token(identity=str(buyer.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def track(db, user, bound_factories):
    """Beat appartenant à `user` (le vendeur Premium par défaut du conftest)."""
    from tests.factories.track_factory import TrackFactory
    t = TrackFactory(composer_user=user, is_approved=True, price_mp3=100)
    db.session.commit()
    return t


def _future(days=30):
    return (datetime.now() + timedelta(days=days)).isoformat()


def _create(client, headers, **overrides):
    # expires_at fait partie du payload par défaut : il est obligatoire depuis
    # qu'un code promo doit toujours avoir une fin.
    payload = {
        'code': 'SUMMER30', 'percent': 30, 'scope': 'track', 'applies_to_all': True,
        'expires_at': _future(),
    }
    payload.update(overrides)
    return client.post('/api/promo-codes', json=payload, headers=headers)


class TestPremiumGating:
    def test_creation_refusee_sans_premium(self, client, db, user, auth_headers):
        user.subscription_plan = 'amateur'
        user.premium_expires_at = datetime.now() - timedelta(days=1)
        db.session.commit()

        res = _create(client, auth_headers)
        assert res.status_code == 403
        assert res.get_json()['code'] == 'PREMIUM_REQUIRED'

    def test_creation_acceptee_avec_premium(self, client, user, auth_headers):
        res = _create(client, auth_headers)
        assert res.status_code == 201

    def test_creation_refusee_sans_role_vendeur(self, client, db, bound_factories):
        """Un Premium non-vendeur (ni beatmaker, ni mix engineer certifié) ne doit
        pas pouvoir créer de code promo, même avec un abonnement actif — sinon un
        simple interprète (is_artist) obtiendrait un outil réservé aux vendeurs."""
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user
        artist = UserFactory(is_artist=True, subscription_plan='pro')
        db.session.commit()
        try:
            token = create_access_token(identity=str(artist.id))
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

            res = _create(client, headers)
            assert res.status_code == 403
            assert res.get_json()['code'] == 'NOT_A_SELLER'
        finally:
            _teardown_user(db, artist)

    def test_creation_refusee_mix_engineer_non_certifie(self, client, db, bound_factories):
        """Un mix engineer auto-déclaré (is_mix_engineer) mais jamais certifié par
        un admin (is_mixmaster_engineer=False) ne doit pas pouvoir créer de code
        promo pour des prestations qu'il n'est pas habilité à vendre."""
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user
        pending = UserFactory(is_mix_engineer=True, subscription_plan='pro')
        db.session.commit()
        try:
            token = create_access_token(identity=str(pending.id))
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

            res = _create(client, headers)
            assert res.status_code == 403
            assert res.get_json()['code'] == 'NOT_A_SELLER'
        finally:
            _teardown_user(db, pending)

    def test_desactivation_reste_possible_sans_premium(self, client, db, user, auth_headers):
        """Un Premium expiré doit pouvoir couper un code encore actif sur son
        catalogue — sinon il subit des remises qu'il ne peut plus piloter."""
        promo_id = _create(client, auth_headers).get_json()['data']['promo_code']['id']

        user.premium_expires_at = datetime.now() - timedelta(days=1)
        db.session.commit()

        res = client.patch(f'/api/promo-codes/{promo_id}',
                           json={'is_active': False}, headers=auth_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['promo_code']['is_active'] is False

        # …mais pas modifier le fond du code.
        res = client.patch(f'/api/promo-codes/{promo_id}',
                           json={'percent': 70, 'applies_to_all': True}, headers=auth_headers)
        assert res.status_code == 403


class TestValidation:
    @pytest.mark.parametrize('code', ['ABC', 'A' * 16, 'SUM MER', 'SUM-30', ''])
    def test_codes_invalides_refuses(self, client, auth_headers, code):
        res = _create(client, auth_headers, code=code)
        assert res.status_code == 400

    @pytest.mark.parametrize('percent', [15, 99, 0, -10, 100])
    def test_remise_hors_bareme_refusee(self, client, auth_headers, percent):
        assert _create(client, auth_headers, percent=percent).status_code == 400

    def test_code_normalise_en_majuscules(self, client, auth_headers):
        res = _create(client, auth_headers, code='summer30')
        assert res.get_json()['data']['promo_code']['code'] == 'SUMMER30'

    def test_doublon_meme_vendeur_refuse(self, client, auth_headers):
        assert _create(client, auth_headers).status_code == 201
        assert _create(client, auth_headers).status_code == 400

    def test_expiration_passee_refusee(self, client, auth_headers):
        past = (datetime.now() - timedelta(days=1)).isoformat()
        assert _create(client, auth_headers, expires_at=past).status_code == 400

    @pytest.mark.parametrize('missing', [None, ''])
    def test_expiration_obligatoire(self, client, auth_headers, missing):
        """Sans échéance, une remise s'oublie et grignote les marges du vendeur
        pendant des mois : le champ est exigé à la création."""
        res = _create(client, auth_headers, expires_at=missing)
        assert res.status_code == 400
        assert 'expiration' in res.get_json()['feedback']['message'].lower()

    def test_beat_d_un_tiers_refuse(self, client, db, auth_headers, bound_factories):
        """Un id forgé ne doit pas rattacher le code au beat de quelqu'un d'autre."""
        from tests.factories.user_factory import UserFactory
        from tests.factories.track_factory import TrackFactory
        other = UserFactory(is_beatmaker=True)
        other_track = TrackFactory(composer_user=other)
        db.session.commit()

        res = _create(client, auth_headers,
                      applies_to_all=False, track_ids=[other_track.id])
        assert res.status_code == 400


class TestUniciteParVendeur:
    def test_deux_vendeurs_peuvent_avoir_le_meme_code(self, client, db, app, user,
                                                      auth_headers, bound_factories):
        """L'unicité est (owner_id, code), pas (code). Sans ça, le premier vendeur
        à réserver « SUMMER30 » le confisquerait à toute la marketplace."""
        from tests.factories.user_factory import UserFactory
        assert _create(client, auth_headers).status_code == 201

        other = UserFactory(is_beatmaker=True, subscription_plan='pro',
                            premium_expires_at=None)
        db.session.commit()
        with app.app_context():
            token = create_access_token(identity=str(other.id))
        other_headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

        assert _create(client, other_headers).status_code == 201

    def test_le_code_resolu_est_celui_du_vendeur_du_beat(self, db, user, track,
                                                         buyer, bound_factories):
        """Deux « SUMMER30 » coexistent : celui appliqué doit être celui du
        propriétaire du beat, jamais celui du voisin."""
        from tests.factories.user_factory import UserFactory
        other = UserFactory(is_beatmaker=True)
        db.session.add_all([
            PromoCode(owner_id=user.id, code='SUMMER30', percent=30,
                      scope=PromoCodeScope.TRACK.value, applies_to_all=True),
            PromoCode(owner_id=other.id, code='SUMMER30', percent=70,
                      scope=PromoCodeScope.TRACK.value, applies_to_all=True),
        ])
        db.session.commit()

        result = apply_to_track('SUMMER30', track, buyer.id, Decimal('100.00'))
        assert result['percent'] == 30            # celui du vendeur du beat
        assert result['net'] == Decimal('70.00')  # et pas 30.00


class TestApplication:
    def test_preview_coherent_brut_remise_net(self, client, db, user, track,
                                              auth_headers, buyer_headers):
        _create(client, auth_headers)
        res = client.post('/api/promo-codes/preview', json={
            'scope': 'track', 'code': 'SUMMER30', 'track_id': track.id,
            'format_type': 'mp3', 'duration_years': 0, 'territory': 'France',
        }, headers=buyer_headers)

        assert res.status_code == 200
        d = res.get_json()['data']
        assert round(d['gross'] - d['discount'], 2) == d['net']
        assert d['percent'] == 30

    def test_vendeur_ne_peut_pas_utiliser_son_propre_code(self, client, user, track,
                                                          auth_headers):
        _create(client, auth_headers)
        res = client.post('/api/promo-codes/preview', json={
            'scope': 'track', 'code': 'SUMMER30', 'track_id': track.id,
            'format_type': 'mp3', 'duration_years': 0, 'territory': 'France',
        }, headers=auth_headers)
        assert res.status_code == 400
        assert res.get_json()['code'] == 'PROMO_OWN_CODE'

    def test_beat_hors_perimetre_refuse(self, db, user, track, buyer):
        promo = PromoCode(owner_id=user.id, code='CIBLE30', percent=30,
                          scope=PromoCodeScope.TRACK.value, applies_to_all=False)
        db.session.add(promo)
        db.session.commit()  # aucun beat rattaché

        with pytest.raises(PromoError) as exc:
            apply_to_track('CIBLE30', track, buyer.id, Decimal('100.00'))
        assert exc.value.code == 'PROMO_NOT_APPLICABLE'

    def test_code_expire_refuse(self, db, user, track, buyer):
        db.session.add(PromoCode(
            owner_id=user.id, code='EXPIRE30', percent=30,
            scope=PromoCodeScope.TRACK.value, applies_to_all=True,
            expires_at=datetime.now() - timedelta(days=1),
        ))
        db.session.commit()

        with pytest.raises(PromoError) as exc:
            apply_to_track('EXPIRE30', track, buyer.id, Decimal('100.00'))
        assert exc.value.code == 'PROMO_EXPIRED'

    def test_remise_sous_le_minimum_stripe_refusee(self, db, user, track, buyer):
        """-70 % sur 0,99 € = 0,30 €, sous le plancher Stripe : mieux vaut refuser
        le code avec un message clair qu'une erreur Stripe opaque au checkout."""
        db.session.add(PromoCode(
            owner_id=user.id, code='BIGDROP70', percent=70,
            scope=PromoCodeScope.TRACK.value, applies_to_all=True,
        ))
        db.session.commit()

        with pytest.raises(PromoError) as exc:
            apply_to_track('BIGDROP70', track, buyer.id, Decimal('0.99'))
        assert exc.value.code == 'PROMO_AMOUNT_TOO_LOW'


class TestLimites:
    def test_quota_atomique_jamais_depasse(self, db, user, buyer):
        """try_consume() fait un UPDATE conditionnel : deux paiements concurrents
        sur la dernière utilisation ne peuvent pas passer tous les deux."""
        promo = PromoCode(owner_id=user.id, code='QUOTA10', percent=10,
                          scope=PromoCodeScope.TRACK.value, applies_to_all=True,
                          max_redemptions=2)
        db.session.add(promo)
        db.session.commit()

        assert promo.try_consume(buyer.id) is True
        db.session.refresh(promo)
        assert promo.try_consume(buyer.id) is True
        db.session.refresh(promo)
        assert promo.try_consume(buyer.id) is False   # quota atteint
        db.session.refresh(promo)

        assert promo.redemption_count == 2
        assert promo.is_exhausted is True

    def test_code_epuise_refuse(self, db, user, track, buyer):
        db.session.add(PromoCode(
            owner_id=user.id, code='EPUISE30', percent=30,
            scope=PromoCodeScope.TRACK.value, applies_to_all=True,
            max_redemptions=1, redemption_count=1,
        ))
        db.session.commit()

        with pytest.raises(PromoError) as exc:
            apply_to_track('EPUISE30', track, buyer.id, Decimal('100.00'))
        assert exc.value.code == 'PROMO_EXHAUSTED'

    def test_once_per_user(self, db, user, track, buyer):
        promo = PromoCode(owner_id=user.id, code='UNIQUE30', percent=30,
                          scope=PromoCodeScope.TRACK.value, applies_to_all=True,
                          once_per_user=True)
        db.session.add(promo)
        db.session.commit()

        # 1re utilisation : OK
        apply_to_track('UNIQUE30', track, buyer.id, Decimal('100.00'))

        db.session.add(PromoCodeRedemption(
            promo_code_id=promo.id, user_id=buyer.id,
            gross_amount=Decimal('100.00'), discount_amount=Decimal('30.00'),
            net_amount=Decimal('70.00'), percent_applied=30,
        ))
        db.session.commit()

        with pytest.raises(PromoError) as exc:
            apply_to_track('UNIQUE30', track, buyer.id, Decimal('100.00'))
        assert exc.value.code == 'PROMO_ALREADY_USED'

    def test_illimite_par_defaut(self, db, user, track, buyer):
        """Sans once_per_user, le même acheteur peut réutiliser le code à chaque
        commande tant qu'il est valide."""
        promo = PromoCode(owner_id=user.id, code='ILLIM30', percent=30,
                          scope=PromoCodeScope.TRACK.value, applies_to_all=True,
                          once_per_user=False)
        db.session.add(promo)
        db.session.flush()  # promo.id requis par la redemption ci-dessous
        db.session.add(PromoCodeRedemption(
            promo_code_id=promo.id, user_id=buyer.id,
            gross_amount=Decimal('100.00'), discount_amount=Decimal('30.00'),
            net_amount=Decimal('70.00'), percent_applied=30,
        ))
        db.session.commit()

        result = apply_to_track('ILLIM30', track, buyer.id, Decimal('100.00'))
        assert result['net'] == Decimal('70.00')


class TestSuppression:
    def test_code_utilise_est_desactive_pas_supprime(self, client, db, user,
                                                     buyer, auth_headers):
        """Les redemptions sont des pièces comptables liées à des paiements Stripe
        réels : les effacer casserait la réconciliation."""
        promo_id = _create(client, auth_headers).get_json()['data']['promo_code']['id']
        db.session.add(PromoCodeRedemption(
            promo_code_id=promo_id, user_id=buyer.id,
            gross_amount=Decimal('100.00'), discount_amount=Decimal('30.00'),
            net_amount=Decimal('70.00'), percent_applied=30,
        ))
        db.session.commit()

        res = client.delete(f'/api/promo-codes/{promo_id}', headers=auth_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['deleted'] is False

        promo = db.session.get(PromoCode, promo_id)
        assert promo is not None and promo.is_active is False

    def test_code_jamais_utilise_est_supprime(self, client, db, user, auth_headers):
        promo_id = _create(client, auth_headers).get_json()['data']['promo_code']['id']

        res = client.delete(f'/api/promo-codes/{promo_id}', headers=auth_headers)
        assert res.get_json()['data']['deleted'] is True
        assert db.session.get(PromoCode, promo_id) is None


class TestSecurite:
    def test_homoglyphe_unicode_refuse(self, client, auth_headers):
        """« SUMMЕR30 » (Е cyrillique) s'affiche exactement comme « SUMMER30 ».
        str.isalnum() l'acceptait : un vendeur pouvait forger le sosie du code
        d'un concurrent, ou piéger un acheteur qui recopie un code vu ailleurs."""
        res = _create(client, auth_headers, code='SUMMЕR30')
        assert res.status_code == 400
        assert res.get_json()['code'] == 'PROMO_CODE_INVALID'

    @pytest.mark.parametrize('code', ['CODE-30', 'CODE 30', 'CODE_30', 'CÔDE30', 'CODE😀'])
    def test_seuls_les_caracteres_ascii_alphanumeriques_passent(self, client, auth_headers, code):
        assert _create(client, auth_headers, code=code).status_code == 400

    def test_code_ascii_valide_accepte(self, client, auth_headers):
        assert _create(client, auth_headers, code='NOEL2026').status_code == 201
