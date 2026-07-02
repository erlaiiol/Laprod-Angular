"""
Tests unitaires — record_playlist_browse() dans recommendation_service.py
"""
from unittest.mock import MagicMock, patch, call
from datetime import datetime


def _make_track(track_id: int, key='C major', style='Trap', bpm=128):
    t = MagicMock()
    t.id = track_id
    t.key = key
    t.style = style
    t.bpm = bpm
    t.tags = []
    t.composer_id = 1
    t.duration = 120
    return t


class TestRecordPlaylistBrowse:

    def test_skips_when_fewer_than_3_tracks(self):
        """Avec moins de 3 tracks, aucun ListenEvent ne doit être créé."""
        from utils.recommendation_service import record_playlist_browse

        tracks = [_make_track(i) for i in range(2)]

        with patch('utils.recommendation_service.db') as mock_db, \
             patch('utils.recommendation_service.ListenEvent') as MockListenEvent:
            mock_db.session.query.return_value.filter.return_value.all.return_value = []
            record_playlist_browse(user_id=1, beatmaker_id=2, tracks=tracks)
            mock_db.session.add_all.assert_not_called()

    def test_creates_listen_events_for_new_tracks(self):
        """Avec 3+ tracks non encore écoutés, crée des ListenEvent synthétiques."""
        from utils.recommendation_service import record_playlist_browse

        tracks = [_make_track(i) for i in range(1, 5)]

        with patch('utils.recommendation_service.db') as mock_db, \
             patch('utils.recommendation_service.ListenEvent') as MockListenEvent:
            # Simuler : aucun ListenEvent existant dans les 24h
            mock_db.session.query.return_value.filter.return_value.all.return_value = []
            MockListenEvent.side_effect = lambda **kw: MagicMock(**kw)

            record_playlist_browse(user_id=1, beatmaker_id=2, tracks=tracks)

            assert mock_db.session.add_all.called
            added = mock_db.session.add_all.call_args[0][0]
            assert len(added) == 4

    def test_skips_tracks_already_listened_recently(self):
        """Les tracks déjà présents dans les 24h ne génèrent pas de doublon."""
        from utils.recommendation_service import record_playlist_browse

        tracks = [_make_track(i) for i in range(1, 4)]

        with patch('utils.recommendation_service.db') as mock_db, \
             patch('utils.recommendation_service.ListenEvent') as MockListenEvent:
            # Simuler : tracks 1 et 2 déjà écoutés dans les 24h
            mock_db.session.query.return_value.filter.return_value.all.return_value = [(1,), (2,)]
            MockListenEvent.side_effect = lambda **kw: MagicMock(**kw)

            record_playlist_browse(user_id=1, beatmaker_id=2, tracks=tracks)

            assert mock_db.session.add_all.called
            added = mock_db.session.add_all.call_args[0][0]
            # Seul le track 3 doit être ajouté
            assert len(added) == 1

    def test_does_not_commit_when_no_new_events(self):
        """Si tous les tracks sont déjà dans l'historique, pas de commit."""
        from utils.recommendation_service import record_playlist_browse

        tracks = [_make_track(1), _make_track(2), _make_track(3)]

        with patch('utils.recommendation_service.db') as mock_db:
            mock_db.session.query.return_value.filter.return_value.all.return_value = [
                (1,), (2,), (3,)
            ]
            record_playlist_browse(user_id=1, beatmaker_id=2, tracks=tracks)
            mock_db.session.add_all.assert_not_called()
            mock_db.session.commit.assert_not_called()

    def test_listen_events_use_passive_completion_ratio(self):
        """Les ListenEvent synthétiques doivent avoir completion_ratio=0.2."""
        from utils.recommendation_service import record_playlist_browse

        tracks = [_make_track(i) for i in range(1, 4)]
        created_events = []

        with patch('utils.recommendation_service.db') as mock_db, \
             patch('utils.recommendation_service.ListenEvent') as MockListenEvent:
            mock_db.session.query.return_value.filter.return_value.all.return_value = []

            def capture(**kw):
                m = MagicMock(**kw)
                created_events.append(kw)
                return m
            MockListenEvent.side_effect = capture

            record_playlist_browse(user_id=42, beatmaker_id=7, tracks=tracks)

        for ev in created_events:
            assert ev['completion_ratio'] == 0.2
            assert ev['user_id'] == 42
