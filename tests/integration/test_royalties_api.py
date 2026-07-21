"""
Tests d'intégration — routes/royalties_api.py

Consulter la cap-table d'un titre est libre pour toute partie prenante
légitime ; seule la gestion (ajouter/modifier/retirer, ou confirmer pour un
tiers) est réservée à can_view_royalties (Premium+), pour le compositeur ou
son producteur.
"""
import pytest
from flask_jwt_extended import create_access_token

from models import RosterLink, RosterLinkStatus, Track, TrackSplit
from tests.factories.track_factory import TrackFactory
from tests.factories.user_factory import UserFactory
from tests.scenarios import _teardown_user


def _headers_for(app, u):
    with app.app_context():
        token = create_access_token(identity=str(u.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def composer(db, app, bound_factories):
    u = UserFactory(is_beatmaker=True, subscription_plan='premium')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def free_composer(db, app, bound_factories):
    u = UserFactory(is_beatmaker=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def collaborator(db, app, bound_factories):
    u = UserFactory(is_beatmaker=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def outsider(db, app, bound_factories):
    u = UserFactory(subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def track(db, composer, bound_factories):
    composer_user, _ = composer
    t = TrackFactory(composer_id=composer_user.id, is_approved=True)
    db.session.commit()
    yield t
    db.session.rollback()
    db.session.query(TrackSplit).filter_by(track_id=t.id).delete()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


def _add(client, headers, track_id, **overrides):
    payload = {'role': 'beatmaker', 'percentage': 20, 'external_name': 'Collabo', **overrides}
    return client.post(f'/api/royalties/tracks/{track_id}/splits', json=payload, headers=headers)


class TestAddSplit:
    def test_compositeur_premium_peut_ajouter_une_part(self, client, composer, track):
        _, headers = composer
        res = _add(client, headers, track.id)
        assert res.status_code == 201
        body = res.get_json()['data']['split']
        assert body['percentage'] == 20.0
        assert body['role'] == 'beatmaker'
        assert body['status'] == 'declared'

    def test_compositeur_free_ne_peut_pas_ajouter(self, client, free_composer, db, bound_factories):
        composer_user, headers = free_composer
        t = TrackFactory(composer_id=composer_user.id, is_approved=True)
        db.session.commit()

        res = _add(client, headers, t.id)
        assert res.status_code == 403

        db.session.delete(t)
        db.session.commit()

    def test_tiers_ne_peut_pas_ajouter(self, client, outsider, track):
        _, headers = outsider
        res = _add(client, headers, track.id)
        assert res.status_code == 403

    def test_producteur_lie_peut_ajouter(self, client, app, db, composer, track, bound_factories):
        composer_user, _ = composer
        producer = UserFactory(is_producer=True, subscription_plan='premium')
        db.session.commit()
        link = RosterLink(
            producer_id=producer.id, artist_id=composer_user.id,
            invited_by_id=producer.id, status=RosterLinkStatus.active,
        )
        db.session.add(link)
        db.session.commit()
        prod_headers = _headers_for(app, producer)

        res = _add(client, prod_headers, track.id)
        assert res.status_code == 201

        db.session.delete(link)
        db.session.commit()
        _teardown_user(db, producer)

    def test_depassement_de_100_pourcent_refuse(self, client, composer, track):
        _, headers = composer
        assert _add(client, headers, track.id, percentage=70).status_code == 201
        res = _add(client, headers, track.id, percentage=40)
        assert res.status_code == 409

    def test_pourcentage_invalide_refuse(self, client, composer, track):
        _, headers = composer
        res = _add(client, headers, track.id, percentage=0)
        assert res.status_code == 400
        res = _add(client, headers, track.id, percentage=150)
        assert res.status_code == 400

    def test_lien_vers_un_compte_reprend_son_username(self, client, composer, collaborator, track):
        _, headers = composer
        collab_user, _ = collaborator
        res = _add(client, headers, track.id, user_id=collab_user.id, external_name='')
        assert res.status_code == 201
        body = res.get_json()['data']['split']
        assert body['user']['id'] == collab_user.id
        assert body['external_name'] == collab_user.username


class TestListSplits:
    def test_compositeur_voit_sa_cap_table(self, client, composer, track):
        _, headers = composer
        _add(client, headers, track.id)

        res = client.get(f'/api/royalties/tracks/{track.id}/splits', headers=headers)
        assert res.status_code == 200
        data = res.get_json()['data']
        assert len(data['splits']) == 1
        assert data['total_percentage'] == 20.0
        assert data['can_manage'] is True

    def test_partie_prenante_voit_sans_etre_premium(self, client, composer, collaborator, track):
        """Le bénéficiaire d'une part peut la consulter même sans palier payant —
        même philosophie que le roster : celui qui reçoit ne paie pas pour voir."""
        _, headers = composer
        collab_user, collab_headers = collaborator
        _add(client, headers, track.id, user_id=collab_user.id, external_name='')

        res = client.get(f'/api/royalties/tracks/{track.id}/splits', headers=collab_headers)
        assert res.status_code == 200
        assert res.get_json()['data']['can_manage'] is False

    def test_tiers_non_lie_ne_voit_pas(self, client, outsider, track):
        _, headers = outsider
        res = client.get(f'/api/royalties/tracks/{track.id}/splits', headers=headers)
        assert res.status_code == 403


class TestConfirmSplit:
    def test_le_titulaire_confirme_sa_propre_part_sans_etre_premium(self, client, composer, collaborator, track):
        _, headers = composer
        collab_user, collab_headers = collaborator
        res = _add(client, headers, track.id, user_id=collab_user.id, external_name='')
        split_id = res.get_json()['data']['split']['id']

        confirm_res = client.post(f'/api/royalties/splits/{split_id}/confirm', headers=collab_headers)
        assert confirm_res.status_code == 200
        assert confirm_res.get_json()['data']['split']['status'] == 'confirmed'

    def test_un_tiers_non_concerne_ne_peut_pas_confirmer(self, client, composer, outsider, track):
        _, headers = composer
        _, outsider_headers = outsider
        res = _add(client, headers, track.id)
        split_id = res.get_json()['data']['split']['id']

        confirm_res = client.post(f'/api/royalties/splits/{split_id}/confirm', headers=outsider_headers)
        assert confirm_res.status_code == 403


class TestUpdateAndDeleteSplit:
    def test_compositeur_peut_modifier_le_pourcentage(self, client, composer, track):
        _, headers = composer
        res = _add(client, headers, track.id, percentage=20)
        split_id = res.get_json()['data']['split']['id']

        update_res = client.put(
            f'/api/royalties/splits/{split_id}', json={'percentage': 35}, headers=headers,
        )
        assert update_res.status_code == 200
        assert update_res.get_json()['data']['split']['percentage'] == 35.0

    def test_modification_qui_depasse_100_refusee(self, client, composer, track):
        _, headers = composer
        first = _add(client, headers, track.id, percentage=60)
        _add(client, headers, track.id, percentage=30)
        split_id = first.get_json()['data']['split']['id']

        update_res = client.put(
            f'/api/royalties/splits/{split_id}', json={'percentage': 80}, headers=headers,
        )
        assert update_res.status_code == 409

    def test_compositeur_peut_retirer_une_part(self, client, db, composer, track):
        _, headers = composer
        res = _add(client, headers, track.id)
        split_id = res.get_json()['data']['split']['id']

        delete_res = client.delete(f'/api/royalties/splits/{split_id}', headers=headers)
        assert delete_res.status_code == 200
        assert db.session.get(TrackSplit, split_id) is None

    def test_tiers_ne_peut_pas_retirer(self, client, composer, outsider, track):
        _, headers = composer
        _, outsider_headers = outsider
        res = _add(client, headers, track.id)
        split_id = res.get_json()['data']['split']['id']

        delete_res = client.delete(f'/api/royalties/splits/{split_id}', headers=outsider_headers)
        assert delete_res.status_code == 403
