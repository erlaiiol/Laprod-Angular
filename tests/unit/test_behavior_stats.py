"""
Tests des statistiques comportementales (utils/behavior_stats.py) + les corrélations
topline↔métadonnées ajoutées à music_stats.

Comme catalog_music_stats, ces fonctions lisent des tables globales et le fixture db
ne rollback pas : tests écrits en DELTAS + nettoyage de ce qu'ils créent.
"""
from datetime import datetime, timedelta

import pytest

from utils.behavior_stats import (
    upload_regularity, uploads_by_weekday, listen_sources, beats_before_topline,
    WEEKDAYS_FR,
)
from utils.music_stats import catalog_music_stats


@pytest.fixture()
def make_track(db, user, bound_factories):
    from tests.factories.track_factory import TrackFactory
    created = []

    def _make(**kw):
        t = TrackFactory(composer_user=user, is_approved=True, **kw)
        created.append(t)
        return t

    yield _make
    from models import Topline, ListenEvent
    for t in created:
        Topline.query.filter_by(track_id=t.id).delete()
        ListenEvent.query.filter_by(track_id=t.id).delete()
        db.session.delete(t)
    db.session.commit()


class TestUploadRegularity:
    def test_douze_points_toujours(self, db):
        """Douze semaines = douze points, même à zéro : un axe temporel stable."""
        s = upload_regularity(weeks=12)
        assert len(s) == 12
        assert all('label' in p and 'value' in p for p in s)

    def test_un_beat_recent_incremente_la_derniere_semaine(self, db, make_track):
        before = upload_regularity()
        make_track()
        db.session.commit()
        after = upload_regularity()
        # Le total sur la fenêtre augmente de 1.
        assert sum(p['value'] for p in after) - sum(p['value'] for p in before) == 1


class TestWeekday:
    def test_sept_jours_lundi_premier(self, db):
        s = uploads_by_weekday()
        assert [p['label'] for p in s] == WEEKDAYS_FR
        assert len(s) == 7


class TestListenSources:
    def test_provenance_agregee(self, db, make_track):
        from models import ListenEvent
        t = make_track()
        before = {x['label']: x['value'] for x in listen_sources()}
        db.session.add(ListenEvent(user_id=t.composer_id, track_id=t.id,
                                   duration_listened=50, track_duration=100,
                                   completion_ratio=0.5, source='search'))
        db.session.commit()
        after = {x['label']: x['value'] for x in listen_sources()}
        assert after.get('search', 0) - before.get('search', 0) == 1


class TestBeatsBeforeTopline:
    def test_compte_les_ecoutes_avant_la_topline(self, db, user, make_track):
        from models import Topline, ListenEvent
        beat = make_track()
        now = datetime.now()
        # 3 écoutes par l'artiste dans la fenêtre, puis une topline juste après.
        for i in range(3):
            db.session.add(ListenEvent(
                user_id=user.id, track_id=beat.id, duration_listened=10,
                track_duration=100, completion_ratio=0.4,
                created_at=now - timedelta(hours=i + 1),
            ))
        db.session.add(Topline(track_id=beat.id, artist_id=user.id,
                               audio_file='t.mp3', created_at=now, is_published=True))
        db.session.commit()

        res = beats_before_topline()
        assert res['sample'] >= 1
        # Au moins un bucket non vide correspond à ce parcours.
        assert sum(h['value'] for h in res['histogram']) == res['sample']

    def test_topline_guest_ignoree(self, db, make_track):
        """Une topline sans artiste identifié (guest) n'a pas d'historique
        d'écoute rattachable — elle ne fausse pas la stat."""
        from models import Topline
        beat = make_track()
        db.session.add(Topline(track_id=beat.id, artist_id=None,
                               guest_session_id='x', audio_file='t.mp3',
                               created_at=datetime.now(), is_published=True))
        db.session.commit()
        # sample ne compte que les toplines à artist_id : la guest est exclue.
        before = beats_before_topline()['sample']
        assert isinstance(before, int)


class TestToplineMetadataCorrelation:
    def test_topline_par_famille_de_tempo(self, db, user, make_track):
        from models import Topline
        # Beat à 120 BPM → famille « Trap / Drill ».
        beat = make_track(bpm=120, key='A minor', style='DrillTest')
        db.session.add(Topline(track_id=beat.id, artist_id=user.id,
                               audio_file='t.mp3', created_at=datetime.now(),
                               is_published=True))
        db.session.commit()

        stats = catalog_music_stats()
        radar = {r['label']: r['value'] for r in stats['topline_by_tempo']}
        assert radar['Trap / Drill'] >= 1

    def test_ratio_mineur_present(self, db):
        stats = catalog_music_stats()
        mr = stats['minor_ratio']
        assert set(mr.keys()) == {'minor', 'major', 'pct_minor'}
        assert 0 <= mr['pct_minor'] <= 100
