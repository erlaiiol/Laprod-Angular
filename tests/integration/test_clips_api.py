"""
Mode Clip — comptage des clips (docs/roadmap.md § Chantier 4, Passe 3).

Aucune vidéo n'est envoyée au serveur : seul l'événement « enregistré / partagé »
l'est. Plafond produit de 45 s revérifié côté serveur.
"""
import uuid

import pytest
from flask_jwt_extended import create_access_token

from models import SocialClipEvent


def _payload(tid, **over):
    body = {
        'track_id': tid, 'mode': 'playback', 'action': 'shared',
        'duration_s': 30, 'target': 'tiktok', 'clip_uid': str(uuid.uuid4()),
    }
    body.update(over)
    return body


@pytest.fixture()
def track(db, user, bound_factories):
    from tests.factories.track_factory import TrackFactory
    t = TrackFactory(composer_user=user, is_approved=True)
    db.session.commit()
    yield t
    SocialClipEvent.query.filter_by(track_id=t.id).delete()
    db.session.commit()


class TestRecordClipEvent:
    def test_utilisateur_connecte_enregistre_un_evenement(self, client, db, user, track, auth_headers):
        res = client.post('/api/clips/events', json=_payload(track.id), headers=auth_headers)
        assert res.status_code == 201
        ev = SocialClipEvent.query.filter_by(track_id=track.id).one()
        assert ev.user_id == user.id
        assert ev.action == 'shared'
        assert ev.target == 'tiktok'
        assert ev.duration_s == 30

    def test_refuse_un_compte_gratuit(self, client, db, user, track, auth_headers):
        user.subscription_plan = 'free'
        user.premium_expires_at = None
        db.session.commit()
        res = client.post('/api/clips/events', json=_payload(track.id), headers=auth_headers)
        assert res.status_code == 403
        assert res.get_json()['code'] == 'PREMIUM_REQUIRED'
        assert SocialClipEvent.query.filter_by(track_id=track.id).count() == 0

    def test_refuse_sans_connexion(self, client, track):
        res = client.post('/api/clips/events', json=_payload(track.id))
        assert res.status_code == 401
        assert SocialClipEvent.query.filter_by(track_id=track.id).count() == 0

    def test_refuse_un_clip_de_plus_de_45_secondes(self, client, track, auth_headers):
        res = client.post('/api/clips/events', json=_payload(track.id, duration_s=46), headers=auth_headers)
        assert res.status_code == 400
        assert res.get_json()['code'] == 'INVALID_CLIP_DURATION'

    @pytest.mark.parametrize('over', [
        {'mode': 'live'}, {'action': 'posted'}, {'clip_uid': 'x'}, {'duration_s': 'abc'}, {'track_id': None},
    ])
    def test_refuse_un_evenement_invalide(self, client, track, auth_headers, over):
        res = client.post('/api/clips/events', json=_payload(track.id, **over), headers=auth_headers)
        assert res.status_code == 400
        assert res.get_json()['code'] == 'INVALID_CLIP_EVENT'

    def test_beat_inexistant(self, client, auth_headers):
        res = client.post('/api/clips/events', json=_payload(99_999_999), headers=auth_headers)
        assert res.status_code == 404
        assert res.get_json()['code'] == 'TRACK_NOT_FOUND'

    def test_cible_inconnue_ramenee_a_share(self, client, track, auth_headers):
        client.post('/api/clips/events', json=_payload(track.id, target='myspace'), headers=auth_headers)
        assert SocialClipEvent.query.filter_by(track_id=track.id).one().target == 'share'

    def test_enregistrement_galerie_sans_cible(self, client, track, auth_headers):
        client.post('/api/clips/events', json=_payload(track.id, action='saved', target=None), headers=auth_headers)
        assert SocialClipEvent.query.filter_by(track_id=track.id).one().target is None


class TestClipCountInViewStats:
    def test_un_clip_enregistre_puis_partage_compte_une_fois(self, client, track, auth_headers):
        uid = str(uuid.uuid4())
        client.post('/api/clips/events', json=_payload(track.id, action='saved', clip_uid=uid), headers=auth_headers)
        client.post('/api/clips/events', json=_payload(track.id, action='shared', clip_uid=uid), headers=auth_headers)
        client.post('/api/clips/events', json=_payload(track.id), headers=auth_headers)

        res = client.get('/api/tracks/my/view-stats', headers=auth_headers)
        stat = next(s for s in res.get_json()['data']['stats'] if s['track_id'] == track.id)
        assert stat['clips'] == 2

    def test_les_clips_d_un_autre_beatmaker_ne_sont_pas_visibles(self, app, client, db, track, auth_headers, bound_factories):
        from tests.factories.user_factory import UserFactory
        from tests.scenarios import _teardown_user
        other = UserFactory(is_beatmaker=True)
        db.session.commit()
        with app.app_context():
            token = create_access_token(identity=str(other.id))
        client.post('/api/clips/events', json=_payload(track.id), headers=auth_headers)
        res = client.get('/api/tracks/my/view-stats', headers={'Authorization': f'Bearer {token}'})
        ids = [s['track_id'] for s in res.get_json()['data']['stats']]
        assert track.id not in ids
        _teardown_user(db, other)


def test_suppression_du_compte_supprime_ses_evenements(app, client, db, track, bound_factories):
    """R9 : la cascade passe par la collection (SQLite ne force pas les FK en test)."""
    from tests.factories.user_factory import UserFactory
    fan = UserFactory()
    db.session.commit()
    db.session.add(SocialClipEvent(track_id=track.id, user_id=fan.id, clip_uid=str(uuid.uuid4()),
                                   mode='rec', action='saved', duration_s=12))
    db.session.commit()
    fan_id = fan.id
    db.session.delete(fan)
    db.session.commit()
    assert SocialClipEvent.query.filter_by(user_id=fan_id).count() == 0


def test_csrf_exempt_est_le_premier_decorateur():
    """R7 : vérifié sur le source, les tests désactivent le CSRF."""
    import inspect
    import routes.clips_api as mod
    src = inspect.getsource(mod)
    route_idx = src.index("@clips_api_bp.route('/events'")
    after = src[route_idx:].splitlines()
    assert after[1].strip().startswith('@csrf.exempt')
