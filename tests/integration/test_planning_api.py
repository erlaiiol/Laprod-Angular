"""
Tests d'intégration — routes/planning_api.py

Le rétroplanning est libre à tous les paliers, comme le roster : seule
l'appartenance au RosterLink actif conditionne l'accès aux événements.
"""
import uuid

import pytest
from flask_jwt_extended import create_access_token
from icalendar import Calendar

from models import PlanningEvent, PlanningEventStatus, RosterLink, RosterLinkStatus, User
from tests.factories.user_factory import UserFactory
from tests.scenarios import _teardown_user


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
def other_user(db, app, bound_factories):
    u = UserFactory(is_producer=True, subscription_plan='free')
    db.session.commit()
    yield u, _headers_for(app, u)
    _teardown_user(db, u)


@pytest.fixture()
def active_link(db, producer, artist):
    prod_user, _ = producer
    art_user, _ = artist
    link = RosterLink(
        producer_id=prod_user.id, artist_id=art_user.id,
        invited_by_id=prod_user.id, status=RosterLinkStatus.active,
    )
    db.session.add(link)
    db.session.commit()
    yield link
    db.session.rollback()
    db.session.query(PlanningEvent).filter_by(roster_link_id=link.id).delete()
    db.session.query(RosterLink).filter_by(id=link.id).delete()
    db.session.commit()


def _create_event(client, headers, link_id, **overrides):
    payload = {
        'title': 'Session studio',
        'start_at': '2026-08-01T14:00:00',
        'event_type': 'recording_session',
        **overrides,
    }
    return client.post(f'/api/planning/roster/{link_id}/events', json=payload, headers=headers)


class TestCreateEvent:
    def test_membre_du_lien_peut_creer(self, client, db, producer, active_link):
        _, prod_headers = producer
        res = _create_event(client, prod_headers, active_link.id)
        assert res.status_code == 201
        body = res.get_json()['data']['event']
        assert body['title'] == 'Session studio'
        assert body['event_type'] == 'recording_session'
        assert body['status'] == 'proposed'

    def test_tiers_ne_peut_pas_creer(self, client, active_link, other_user):
        _, other_headers = other_user
        res = _create_event(client, other_headers, active_link.id)
        assert res.status_code == 404

    def test_titre_obligatoire(self, client, producer, active_link):
        _, prod_headers = producer
        res = _create_event(client, prod_headers, active_link.id, title='')
        assert res.status_code == 400

    def test_fin_avant_debut_refusee(self, client, producer, active_link):
        _, prod_headers = producer
        res = _create_event(
            client, prod_headers, active_link.id,
            start_at='2026-08-01T14:00:00', end_at='2026-08-01T10:00:00',
        )
        assert res.status_code == 400

    def test_lien_non_actif_refuse(self, client, db, producer, artist):
        prod_user, prod_headers = producer
        art_user, _ = artist
        link = RosterLink(
            producer_id=prod_user.id, artist_id=art_user.id,
            invited_by_id=prod_user.id, status=RosterLinkStatus.invited,
        )
        db.session.add(link)
        db.session.commit()

        res = _create_event(client, prod_headers, link.id)
        assert res.status_code == 404

        db.session.delete(link)
        db.session.commit()

    def test_creation_notifie_l_autre_partie(self, client, db, producer, artist, active_link):
        from models import Notification
        _, prod_headers = producer
        art_user, _ = artist

        _create_event(client, prod_headers, active_link.id)

        notif = db.session.query(Notification).filter_by(
            user_id=art_user.id, type='planning_event_created'
        ).first()
        assert notif is not None


class TestListAndMine:
    def test_liste_les_evenements_du_lien(self, client, producer, active_link):
        _, prod_headers = producer
        _create_event(client, prod_headers, active_link.id)
        _create_event(client, prod_headers, active_link.id, title='Concert')

        res = client.get(f'/api/planning/roster/{active_link.id}/events', headers=prod_headers)
        assert res.status_code == 200
        assert len(res.get_json()['data']['events']) == 2

    def test_mine_agrege_tous_les_liens(self, client, producer, artist, active_link):
        _, prod_headers = producer
        _, art_headers = artist
        _create_event(client, prod_headers, active_link.id)

        res = client.get('/api/planning/mine', headers=art_headers)
        assert res.status_code == 200
        assert len(res.get_json()['data']['events']) == 1


class TestConfirmCancelDelete:
    def _created_event(self, client, producer, active_link):
        _, prod_headers = producer
        res = _create_event(client, prod_headers, active_link.id)
        return res.get_json()['data']['event']['id']

    def test_confirmation_par_l_autre_partie(self, client, db, producer, artist, active_link):
        event_id = self._created_event(client, producer, active_link)
        _, art_headers = artist

        res = client.post(f'/api/planning/events/{event_id}/confirm', headers=art_headers)
        assert res.status_code == 200

        event = db.session.get(PlanningEvent, event_id)
        assert event.status == PlanningEventStatus.confirmed

    def test_annulation_par_membre_du_lien(self, client, db, producer, active_link):
        event_id = self._created_event(client, producer, active_link)
        _, prod_headers = producer

        res = client.post(f'/api/planning/events/{event_id}/cancel', headers=prod_headers)
        assert res.status_code == 200
        assert db.session.get(PlanningEvent, event_id).status == PlanningEventStatus.cancelled

    def test_suppression_par_le_createur(self, client, db, producer, active_link):
        event_id = self._created_event(client, producer, active_link)
        _, prod_headers = producer

        res = client.delete(f'/api/planning/events/{event_id}', headers=prod_headers)
        assert res.status_code == 200
        assert db.session.get(PlanningEvent, event_id) is None

    def test_suppression_par_non_createur_refusee_si_pas_annule(self, client, producer, artist, active_link):
        event_id = self._created_event(client, producer, active_link)
        _, art_headers = artist

        res = client.delete(f'/api/planning/events/{event_id}', headers=art_headers)
        assert res.status_code == 403


class TestIcsExport:
    def test_export_ics_valide(self, client, producer, active_link):
        _, prod_headers = producer
        res = _create_event(client, prod_headers, active_link.id)
        event_id = res.get_json()['data']['event']['id']

        res = client.get(f'/api/planning/events/{event_id}/ics', headers=prod_headers)
        assert res.status_code == 200
        assert res.content_type.startswith('text/calendar')

        cal = Calendar.from_ical(res.data)
        vevents = list(cal.walk('VEVENT'))
        assert len(vevents) == 1
        assert str(vevents[0]['summary']) == 'Session studio'

    def test_flux_public_mauvais_token(self, client):
        res = client.get('/api/planning/feed/token-inexistant.ics')
        assert res.status_code == 404

    def test_flux_public_bon_token(self, client, db, producer, active_link):
        prod_user, prod_headers = producer
        _create_event(client, prod_headers, active_link.id)

        res = client.post('/api/planning/ical-token/regenerate', headers=prod_headers)
        assert res.status_code == 200
        feed_path = res.get_json()['data']['feed_path']

        feed_res = client.get(feed_path)
        assert feed_res.status_code == 200
        assert feed_res.content_type.startswith('text/calendar')

        cal = Calendar.from_ical(feed_res.data)
        assert len(list(cal.walk('VEVENT'))) == 1

        prod_user.ical_feed_token = None
        db.session.commit()
