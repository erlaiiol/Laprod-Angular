"""
Tests des statistiques de vues (beatmaker + ingénieur mix/master).

Règle produit : les VUES TOTALES sont gratuites pour tous ; les VISITEURS UNIQUES
sont réservés au Premium. Le gating est vérifié côté serveur (l'unique n'est ni
calculé ni renvoyé aux comptes gratuits).
"""
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_access_token

from models import TrackView, EngineerView


def _headers(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _set_premium(db, user, active=True):
    user.subscription_plan = 'pro' if active else 'free'
    user.premium_expires_at = (datetime.now() + timedelta(days=10)) if active else None
    db.session.commit()


@pytest.fixture()
def engineer(db, bound_factories):
    from tests.factories.user_factory import UserFactory
    from tests.scenarios import _teardown_user
    u = UserFactory(is_mix_engineer=True, is_mixmaster_engineer=True)
    db.session.commit()
    yield u
    EngineerView.query.filter_by(engineer_id=u.id).delete()
    db.session.commit()
    _teardown_user(db, u)


# ── Beatmaker : /api/tracks/my/view-stats ─────────────────────────────────────

class TestBeatmakerViewStats:
    @pytest.fixture()
    def track(self, db, user, bound_factories):
        from tests.factories.track_factory import TrackFactory
        t = TrackFactory(composer_user=user, is_approved=True)
        db.session.commit()
        yield t
        TrackView.query.filter_by(track_id=t.id).delete()
        db.session.commit()

    def _seed_views(self, db, track):
        # 3 vues, 2 IP distinctes → total 3, unique 2.
        for ip in ('aaa', 'aaa', 'bbb'):
            db.session.add(TrackView(track_id=track.id, ip_hash=ip, source='detail'))
        db.session.commit()

    def test_premium_voit_le_total_et_l_unique(self, client, db, user, track, auth_headers):
        _set_premium(db, user, active=True)
        self._seed_views(db, track)

        res = client.get('/api/tracks/my/view-stats', headers=auth_headers)
        assert res.status_code == 200
        body = res.get_json()['data']
        assert body['unique_locked'] is False
        stat = next(s for s in body['stats'] if s['track_id'] == track.id)
        assert stat['total_views'] == 3
        assert stat['unique_views'] == 2

    def test_gratuit_voit_le_total_mais_pas_l_unique(self, client, db, user, track, auth_headers):
        _set_premium(db, user, active=False)
        self._seed_views(db, track)

        res = client.get('/api/tracks/my/view-stats', headers=auth_headers)
        body = res.get_json()['data']
        assert body['unique_locked'] is True
        stat = next(s for s in body['stats'] if s['track_id'] == track.id)
        assert stat['total_views'] == 3          # total toujours visible
        assert stat['unique_views'] is None      # unique masqué serveur


# ── Ingénieur : enregistrement des vues ───────────────────────────────────────

class TestEngineerViewRecording:
    def test_enregistre_une_vue(self, client, db, engineer):
        assert EngineerView.query.filter_by(engineer_id=engineer.id).count() == 0
        res = client.post(f'/api/mixmaster/engineers/{engineer.id}/view')
        assert res.status_code == 200
        assert EngineerView.query.filter_by(engineer_id=engineer.id).count() == 1

    def test_deduplication_24h(self, client, db, engineer):
        """Deux vues de la même IP en 24h ne comptent que pour une."""
        client.post(f'/api/mixmaster/engineers/{engineer.id}/view')
        client.post(f'/api/mixmaster/engineers/{engineer.id}/view')
        assert EngineerView.query.filter_by(engineer_id=engineer.id).count() == 1

    def test_ingenieur_ne_compte_pas_sa_propre_vue(self, client, app, db, engineer):
        res = client.post(f'/api/mixmaster/engineers/{engineer.id}/view',
                          headers=_headers(app, engineer))
        assert res.status_code == 200
        assert EngineerView.query.filter_by(engineer_id=engineer.id).count() == 0

    def test_id_non_ingenieur_404(self, client, db, user):
        # `user` est beatmaker, pas ingénieur mix/master.
        res = client.post(f'/api/mixmaster/engineers/{user.id}/view')
        assert res.status_code == 404


# ── Ingénieur : /api/mixmaster/my/view-stats ──────────────────────────────────

class TestEngineerViewStats:
    def _seed(self, db, engineer):
        for ip in ('aaa', 'aaa', 'bbb', 'ccc'):   # total 4, unique 3
            db.session.add(EngineerView(engineer_id=engineer.id, ip_hash=ip))
        db.session.commit()

    def test_premium_voit_total_et_unique(self, client, app, db, engineer):
        _set_premium(db, engineer, active=True)
        self._seed(db, engineer)
        res = client.get('/api/mixmaster/my/view-stats', headers=_headers(app, engineer))
        body = res.get_json()['data']
        assert body['total_views'] == 4
        assert body['unique_views'] == 3
        assert body['unique_locked'] is False

    def test_gratuit_total_seul(self, client, app, db, engineer):
        _set_premium(db, engineer, active=False)
        self._seed(db, engineer)
        res = client.get('/api/mixmaster/my/view-stats', headers=_headers(app, engineer))
        body = res.get_json()['data']
        assert body['total_views'] == 4
        assert body['unique_views'] is None
        assert body['unique_locked'] is True
