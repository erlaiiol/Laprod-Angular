"""
Tests d'intégration — routes/roster_api.py

Le lien roster (invite/accept/decline/revoke) est libre à tous les paliers :
seul le rôle self-déclaré (is_producer côté invitant, is_artist/is_beatmaker
côté invité) conditionne l'accès, jamais le plan d'abonnement.
"""
import uuid

import pytest
from flask_jwt_extended import create_access_token

from models import Notification, RosterLink, RosterLinkStatus, User
from tests.factories.user_factory import UserFactory
from tests.scenarios import _teardown_user


# ── Fixtures locales ─────────────────────────────────────────────────────────────

def _headers_for(app, u):
    with app.app_context():
        token = create_access_token(identity=str(u.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def producer(db, app, bound_factories):
    u = UserFactory(is_producer=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def artist(db, app, bound_factories):
    u = UserFactory(is_artist=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def other_producer(db, app, bound_factories):
    u = UserFactory(is_producer=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


def _invite(client, headers, identifier):
    return client.post('/api/roster/invite', json={'identifier': identifier}, headers=headers)


class TestInvite:
    def test_producteur_peut_inviter_un_artiste_sur_free(self, client, producer, artist):
        """Le lien roster n'est gaté par aucun palier — un producteur FREE peut
        inviter un artiste."""
        prod_user, prod_headers = producer
        art_user, _ = artist

        res = _invite(client, prod_headers, art_user.username)

        assert res.status_code == 201
        body = res.get_json()
        assert body['data']['link']['status'] == 'invited'
        assert body['data']['link']['role'] == 'producer'
        assert body['data']['link']['counterpart']['id'] == art_user.id

    def test_non_producteur_ne_peut_pas_inviter(self, client, artist, other_producer):
        art_user, art_headers = artist
        other_prod_user, _ = other_producer

        res = _invite(client, art_headers, other_prod_user.username)
        assert res.status_code == 403

    def test_cible_sans_role_artiste_ni_beatmaker_refusee(self, client, producer, other_producer):
        prod_user, prod_headers = producer
        target, _ = other_producer  # producteur pur, ni artiste ni beatmaker

        res = _invite(client, prod_headers, target.username)
        assert res.status_code == 400

    def test_auto_invitation_refusee(self, client, producer):
        prod_user, prod_headers = producer
        res = _invite(client, prod_headers, prod_user.username)
        assert res.status_code == 400

    def test_identifiant_inconnu(self, client, producer):
        prod_user, prod_headers = producer
        res = _invite(client, prod_headers, f'inconnu_{uuid.uuid4().hex[:8]}')
        assert res.status_code == 404

    def test_invitation_notifie_l_artiste(self, client, db, producer, artist):
        prod_user, prod_headers = producer
        art_user, _ = artist

        _invite(client, prod_headers, art_user.username)

        notif = db.session.query(Notification).filter_by(
            user_id=art_user.id, type='roster_invite'
        ).first()
        assert notif is not None

    def test_double_invitation_alors_qu_un_lien_est_deja_en_attente(self, client, producer, artist):
        prod_user, prod_headers = producer
        art_user, _ = artist

        assert _invite(client, prod_headers, art_user.username).status_code == 201
        assert _invite(client, prod_headers, art_user.username).status_code == 409


class TestAcceptDecline:
    def _invited_link(self, client, db, producer, artist):
        prod_user, prod_headers = producer
        art_user, art_headers = artist
        res = _invite(client, prod_headers, art_user.username)
        link_id = res.get_json()['data']['link']['id']
        return link_id, prod_user, prod_headers, art_user, art_headers

    def test_acceptation_par_le_mauvais_user_refusee(self, client, db, producer, artist, other_producer):
        link_id, *_ = self._invited_link(client, db, producer, artist)
        _, wrong_headers = other_producer

        res = client.post(f'/api/roster/{link_id}/accept', headers=wrong_headers)
        assert res.status_code == 403

    def test_acceptation_active_le_lien_et_notifie_le_producteur(self, client, db, producer, artist):
        link_id, prod_user, _, art_user, art_headers = self._invited_link(client, db, producer, artist)

        res = client.post(f'/api/roster/{link_id}/accept', headers=art_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['link']['status'] == 'active'

        link = db.session.get(RosterLink, link_id)
        assert link.status == RosterLinkStatus.active
        assert link.responded_at is not None

        notif = db.session.query(Notification).filter_by(
            user_id=prod_user.id, type='roster_accepted'
        ).first()
        assert notif is not None

    def test_declin_marque_le_lien_decline(self, client, db, producer, artist):
        link_id, prod_user, _, art_user, art_headers = self._invited_link(client, db, producer, artist)

        res = client.post(f'/api/roster/{link_id}/decline', headers=art_headers)
        assert res.status_code == 200

        link = db.session.get(RosterLink, link_id)
        assert link.status == RosterLinkStatus.declined

    def test_acceptation_deux_fois_refusee(self, client, db, producer, artist):
        link_id, *_, art_headers = self._invited_link(client, db, producer, artist)
        client.post(f'/api/roster/{link_id}/accept', headers=art_headers)

        res = client.post(f'/api/roster/{link_id}/accept', headers=art_headers)
        assert res.status_code == 409


class TestRevoke:
    def _invited_link(self, client, db, producer, artist):
        prod_user, prod_headers = producer
        art_user, art_headers = artist
        res = _invite(client, prod_headers, art_user.username)
        link_id = res.get_json()['data']['link']['id']
        return link_id, prod_user, prod_headers, art_user, art_headers

    def test_revocation_d_une_invitation_en_attente(self, client, db, producer, artist):
        link_id, prod_user, prod_headers, art_user, _ = self._invited_link(client, db, producer, artist)

        res = client.post(f'/api/roster/{link_id}/revoke', headers=prod_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['link']['status'] == 'revoked'

    def test_quitter_un_lien_actif_le_marque_ended(self, client, db, producer, artist):
        link_id, prod_user, prod_headers, art_user, art_headers = self._invited_link(client, db, producer, artist)
        client.post(f'/api/roster/{link_id}/accept', headers=art_headers)

        res = client.post(f'/api/roster/{link_id}/revoke', headers=art_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['link']['status'] == 'ended'

    def test_tiers_ne_peut_pas_revoquer(self, client, db, producer, artist, other_producer):
        link_id, *_ = self._invited_link(client, db, producer, artist)
        _, wrong_headers = other_producer

        res = client.post(f'/api/roster/{link_id}/revoke', headers=wrong_headers)
        assert res.status_code == 403

    def test_reinvitation_apres_revocation_reutilise_la_meme_ligne(self, client, db, producer, artist):
        link_id, prod_user, prod_headers, art_user, _ = self._invited_link(client, db, producer, artist)
        client.post(f'/api/roster/{link_id}/revoke', headers=prod_headers)

        res = _invite(client, prod_headers, art_user.username)
        assert res.status_code == 201
        assert res.get_json()['data']['link']['id'] == link_id

        rows = db.session.query(RosterLink).filter_by(
            producer_id=prod_user.id, artist_id=art_user.id
        ).all()
        assert len(rows) == 1


class TestMine:
    def test_mine_retourne_les_deux_vues(self, client, db, producer, artist):
        prod_user, prod_headers = producer
        art_user, art_headers = artist
        _invite(client, prod_headers, art_user.username)

        res_prod = client.get('/api/roster/mine', headers=prod_headers)
        assert res_prod.status_code == 200
        data = res_prod.get_json()['data']
        assert len(data['as_producer']) == 1
        assert data['as_artist'] == []

        res_art = client.get('/api/roster/mine', headers=art_headers)
        data_art = res_art.get_json()['data']
        assert len(data_art['as_artist']) == 1
        assert data_art['as_producer'] == []


class TestSearchArtist:
    def test_recherche_reservee_au_producteur(self, client, artist):
        _, art_headers = artist
        res = client.get('/api/roster/search-artist?q=te', headers=art_headers)
        assert res.status_code == 403

    def test_recherche_retourne_les_artistes_correspondants(self, client, db, producer, artist):
        prod_user, prod_headers = producer
        art_user, _ = artist

        res = client.get(f'/api/roster/search-artist?q={art_user.username[:6]}', headers=prod_headers)
        assert res.status_code == 200
        usernames = [u['username'] for u in res.get_json()['data']['users']]
        assert art_user.username in usernames
