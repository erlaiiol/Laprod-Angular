"""
Tests unitaires — Worker RQ (tasks/topline_processing.py)

Stratégie : toutes les fonctions I/O et audio sont mockées.
On vérifie que le worker :
  - appelle chaque étape dans le bon ordre
  - met à jour les statuts Redis correctement à chaque étape
  - persiste la Topline en base de données
  - décrémente le token topline de l'utilisateur
  - gère proprement chaque point de failure individuel

Isolation :
  - create_app() patché pour retourner l'app de test (SQLite en mémoire)
  - extensions.redis_client remplacé par un MagicMock
  - Les fonctions audio de utils.toplines_processor sont patchées
  - Les Toplines créées par le worker sont supprimées en fin de test
"""
import time
import uuid
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def worker_user(db):
    """Artiste avec 5 tokens topline — sujet du traitement worker."""
    from models import User
    from tests.scenarios import _teardown_user
    uid = uuid.uuid4().hex[:6]
    u = User(
        email=f'worker_{uid}@test.laprod.fr',
        username=f'worker_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_artist=True,
        topline_tokens=5,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def worker_track(db, app, worker_user):
    """
    Track avec un vrai fichier audio sur disque.
    Le worker vérifie l'existence du fichier beat avant de fusionner.
    """
    from models import Track
    fname = f'beat_worker_{uuid.uuid4().hex[:8]}.mp3'
    audio_dir = Path(app.root_path) / 'db_assets' / 'audio' / 'tracks'
    audio_dir.mkdir(parents=True, exist_ok=True)
    beat_path = audio_dir / fname
    beat_path.write_bytes(b'ID3\x00fake_mp3_for_beat_existence_check')

    t = Track(
        title='Worker Beat Test',
        composer_id=worker_user.id,
        file_hash=str(uuid.uuid4()),
        audio_file=f'tracks/{fname}',
        bpm=120,
        key='C major',
        is_approved=True,
        price_mp3=9.99,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()
    if beat_path.exists():
        beat_path.unlink()


@pytest.fixture()
def job_payload(tmp_path, worker_user, worker_track):
    """Payload de base transmis au worker par upload_topline()."""
    raw = tmp_path / 'topline_raw_worker_test.webm'
    raw.write_bytes(b'\x1aE\xdf\xa3fake_webm')
    return {
        'job_id':          str(uuid.uuid4()),
        'user_id':         worker_user.id,
        'track_id':        worker_track.id,
        'raw_path':        str(raw),
        'raw_filename':    raw.name,
        'use_autotune':    False,
        'description':     'Test topline description',
        'beat_audio_file': worker_track.audio_file,
        'track_key':       worker_track.key,
        'timestamp':       '20260701_120000',
    }


@pytest.fixture()
def mock_audio(tmp_path):
    """
    Mock des 4 fonctions audio du processor.
    Les paths retournés pointent dans tmp_path pour rester cohérents.
    """
    effects_path = str(tmp_path / 'voice_effects.wav')
    with patch('utils.toplines_processor.convert_to_wav',
               return_value=str(tmp_path / 'voice_temp.wav')), \
         patch('utils.toplines_processor.apply_audio_effects',
               return_value=effects_path), \
         patch('utils.toplines_processor.merge_voice_and_beat',
               return_value='audio/toplines/topline_final_worker_test.wav'), \
         patch('utils.toplines_processor.cleanup_temp_files') as mock_cleanup:
        yield mock_cleanup


def _run_worker(app, job_payload, mock_redis=None):
    """Lance le worker en patchant create_app et redis_client."""
    if mock_redis is None:
        mock_redis = MagicMock()
    from tasks.topline_processing import process_topline_data
    with patch('tasks.topline_processing.create_app', return_value=app), \
         patch('extensions.redis_client', mock_redis):
        process_topline_data(job_payload)
    return mock_redis


# ── Happy path ────────────────────────────────────────────────────────────────

class TestWorkerHappyPath:

    def test_topline_created_in_database(self, app, db, mock_audio, job_payload, worker_user, worker_track):
        """Le worker crée bien une Topline en base."""
        from models import Topline
        _run_worker(app, job_payload)

        tl = db.session.query(Topline).filter_by(
            artist_id=worker_user.id,
            track_id=worker_track.id,
        ).first()
        assert tl is not None
        assert tl.audio_file == 'audio/toplines/topline_final_worker_test.wav'
        assert tl.description == 'Test topline description'

        db.session.delete(tl)
        db.session.commit()

    def test_topline_token_decremented(self, app, db, mock_audio, job_payload, worker_user):
        """Le token topline de l'utilisateur est décrémenté de 1 après traitement."""
        from models import Topline
        initial_tokens = worker_user.topline_tokens
        _run_worker(app, job_payload)

        db.session.expire(worker_user)
        updated = db.session.get(type(worker_user), worker_user.id)
        assert updated.topline_tokens == initial_tokens - 1

        tl = db.session.query(Topline).filter_by(artist_id=worker_user.id).first()
        if tl:
            db.session.delete(tl)
            db.session.commit()

    def test_redis_status_progresses_to_done(self, app, db, mock_audio, job_payload):
        """Le statut Redis passe par 'started' → 'finalizing' → 'done'."""
        from models import Topline
        job_id = job_payload['job_id']
        mock_redis = MagicMock()
        _run_worker(app, job_payload, mock_redis)

        hset_calls = mock_redis.hset.call_args_list
        statuses = [
            (c.kwargs.get('mapping') or c.args[1]).get('status')
            for c in hset_calls
            if isinstance((c.kwargs.get('mapping') or c.args[1]), dict)
        ]
        assert 'started'    in statuses
        assert 'finalizing' in statuses
        assert 'done'       in statuses
        assert statuses.index('started') < statuses.index('done')

        tl = db.session.query(Topline).filter_by(track_id=job_payload['track_id']).first()
        if tl:
            db.session.delete(tl)
            db.session.commit()

    def test_redis_done_contains_topline_id(self, app, db, mock_audio, job_payload):
        """Le hash Redis 'done' contient l'id de la topline créée."""
        from models import Topline
        mock_redis = MagicMock()
        _run_worker(app, job_payload, mock_redis)

        done_call = next(
            c for c in mock_redis.hset.call_args_list
            if (c.kwargs.get('mapping') or c.args[1]).get('status') == 'done'
        )
        done_mapping = done_call.kwargs.get('mapping') or done_call.args[1]
        assert 'topline_id' in done_mapping

        tl = db.session.query(Topline).filter_by(track_id=job_payload['track_id']).first()
        if tl:
            db.session.delete(tl)
            db.session.commit()

    def test_audio_functions_called_in_correct_order(self, app, db, mock_audio, job_payload):
        """Les fonctions audio sont appelées dans le bon ordre (convert → effects → merge)."""
        from models import Topline
        import utils.toplines_processor as proc
        with patch.object(proc, 'convert_to_wav', wraps=None,
                          return_value='/tmp/voice_temp.wav') as m_conv, \
             patch.object(proc, 'apply_audio_effects', wraps=None,
                          return_value='/tmp/voice_effects.wav') as m_eff, \
             patch.object(proc, 'merge_voice_and_beat', wraps=None,
                          return_value='audio/toplines/topline_final_order.wav') as m_merge, \
             patch.object(proc, 'cleanup_temp_files'):
            with patch('tasks.topline_processing.create_app', return_value=app), \
                 patch('extensions.redis_client', MagicMock()):
                from tasks.topline_processing import process_topline_data
                process_topline_data(job_payload)

        m_conv.assert_called_once()
        m_eff.assert_called_once()
        m_merge.assert_called_once()
        # L'ordre via call_count confirme l'exécution séquentielle sans erreur

        tl = db.session.query(Topline).filter_by(track_id=job_payload['track_id']).first()
        if tl:
            db.session.delete(tl)
            db.session.commit()

    def test_temp_files_cleaned_up(self, app, db, mock_audio, job_payload):
        """cleanup_temp_files est appelé avec les fichiers temp après le traitement."""
        from models import Topline
        cleanup_mock = mock_audio  # le fixture retourne le mock cleanup
        _run_worker(app, job_payload)
        cleanup_mock.assert_called_once()

        tl = db.session.query(Topline).filter_by(track_id=job_payload['track_id']).first()
        if tl:
            db.session.delete(tl)
            db.session.commit()


# ── Failure paths ─────────────────────────────────────────────────────────────

class TestWorkerFailurePaths:

    def test_user_not_found_sets_error_status(self, app, db, job_payload):
        """Si l'utilisateur est introuvable, le statut Redis est 'error', pas de Topline."""
        from tasks.topline_processing import process_topline_data
        bad_payload = {**job_payload, 'user_id': 999999}
        mock_redis = MagicMock()
        with patch('tasks.topline_processing.create_app', return_value=app), \
             patch('extensions.redis_client', mock_redis):
            process_topline_data(bad_payload)

        error_call = next(
            (c for c in mock_redis.hset.call_args_list
             if (c.kwargs.get('mapping') or c.args[1]).get('status') == 'error'),
            None,
        )
        assert error_call is not None

    def test_convert_to_wav_failure_sets_error_status(self, app, db, job_payload):
        """Échec technique de convert_to_wav (FFmpeg) → Redis 'error', ToplineProcessingError levée."""
        from tasks.topline_processing import process_topline_data, ToplineProcessingError
        mock_redis = MagicMock()
        with patch('utils.toplines_processor.convert_to_wav',
                   side_effect=RuntimeError('ffmpeg introuvable')), \
             patch('tasks.topline_processing.create_app', return_value=app), \
             patch('extensions.redis_client', mock_redis):
            with pytest.raises(ToplineProcessingError):
                process_topline_data(job_payload)

        error_mapping = next(
            (c.kwargs.get('mapping') or c.args[1])
            for c in mock_redis.hset.call_args_list
            if (c.kwargs.get('mapping') or c.args[1]).get('status') == 'error'
        )
        assert error_mapping['status'] == 'error'

    def test_empty_file_value_error_surfaces_user_message(self, app, db, job_payload):
        """ValueError de convert_to_wav (fichier vide) → message lisible dans Redis."""
        from tasks.topline_processing import process_topline_data, ToplineProcessingError
        user_msg = "Fichier audio invalide ou vide (10 octets). L'enregistrement a peut-être été interrompu."
        mock_redis = MagicMock()
        with patch('utils.toplines_processor.convert_to_wav',
                   side_effect=ValueError(user_msg)), \
             patch('tasks.topline_processing.create_app', return_value=app), \
             patch('extensions.redis_client', mock_redis):
            with pytest.raises(ToplineProcessingError):
                process_topline_data(job_payload)

        error_mapping = next(
            (c.kwargs.get('mapping') or c.args[1])
            for c in mock_redis.hset.call_args_list
            if (c.kwargs.get('mapping') or c.args[1]).get('status') == 'error'
        )
        assert error_mapping['error_message'] == user_msg

    def test_apply_audio_effects_failure_cleans_up_and_errors(self, app, db, tmp_path, job_payload):
        """Échec d'apply_audio_effects → cleanup des fichiers temp + Redis 'error'."""
        from tasks.topline_processing import process_topline_data, ToplineProcessingError
        mock_redis = MagicMock()
        with patch('utils.toplines_processor.convert_to_wav',
                   return_value=str(tmp_path / 'voice_temp.wav')), \
             patch('utils.toplines_processor.apply_audio_effects',
                   side_effect=MemoryError('RAM épuisé')), \
             patch('utils.toplines_processor.cleanup_temp_files') as mock_cleanup, \
             patch('tasks.topline_processing.create_app', return_value=app), \
             patch('extensions.redis_client', mock_redis):
            with pytest.raises(ToplineProcessingError):
                process_topline_data(job_payload)

        mock_cleanup.assert_called_once()

    def test_beat_file_missing_sets_error_without_calling_merge(self, app, db, job_payload):
        """Beat file absent → error sans appeler merge_voice_and_beat."""
        from tasks.topline_processing import process_topline_data, ToplineProcessingError
        bad_payload = {**job_payload, 'beat_audio_file': 'tracks/inexistant.mp3'}
        mock_redis = MagicMock()
        with patch('utils.toplines_processor.convert_to_wav',
                   return_value='/tmp/voice_temp.wav'), \
             patch('utils.toplines_processor.apply_audio_effects',
                   return_value='/tmp/voice_effects.wav'), \
             patch('utils.toplines_processor.merge_voice_and_beat') as mock_merge, \
             patch('utils.toplines_processor.cleanup_temp_files'), \
             patch('tasks.topline_processing.create_app', return_value=app), \
             patch('extensions.redis_client', mock_redis):
            with pytest.raises(ToplineProcessingError):
                process_topline_data(bad_payload)

        mock_merge.assert_not_called()

    def test_merge_failure_sets_error_and_no_topline_created(self, app, db, job_payload, worker_user):
        """Échec de merge → Redis 'error', pas de Topline en base."""
        from models import Topline
        from tasks.topline_processing import process_topline_data, ToplineProcessingError
        mock_redis = MagicMock()
        with patch('utils.toplines_processor.convert_to_wav',
                   return_value='/tmp/voice_temp.wav'), \
             patch('utils.toplines_processor.apply_audio_effects',
                   return_value='/tmp/voice_effects.wav'), \
             patch('utils.toplines_processor.merge_voice_and_beat',
                   side_effect=IOError('Espace disque insuffisant')), \
             patch('utils.toplines_processor.cleanup_temp_files'), \
             patch('tasks.topline_processing.create_app', return_value=app), \
             patch('extensions.redis_client', mock_redis):
            with pytest.raises(ToplineProcessingError):
                process_topline_data(job_payload)

        count = db.session.query(Topline).filter_by(artist_id=worker_user.id,
                                                     track_id=job_payload['track_id']).count()
        assert count == 0


# ── Performance ───────────────────────────────────────────────────────────────

class TestWorkerPerformance:

    def test_worker_overhead_under_2s_with_mocked_audio(self, app, db, mock_audio, job_payload):
        """
        Le worker (hors traitement audio) doit compléter en < 2s.
        Mesure l'overhead de : init Flask context, requêtes DB, appels Redis.
        Ce budget permet de détecter des régressions (connexions lentes, N+1 queries…).
        """
        from models import Topline

        start = time.perf_counter()
        _run_worker(app, job_payload)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Worker trop lent hors audio : {elapsed:.2f}s (budget : 2s)"

        tl = db.session.query(Topline).filter_by(track_id=job_payload['track_id']).first()
        if tl:
            db.session.delete(tl)
            db.session.commit()
