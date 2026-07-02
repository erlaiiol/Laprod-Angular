"""
Tests unitaires — tasks/track_processing.py

Couvre process_track_data() dans tous les modes :
  - MP3 seul           → preview watermarqué, Track créé en DB
  - WAV seul           → conversion WAV→MP3, Track créé
  - MP3 + WAV          → preview depuis MP3, les deux colonnes remplis
  - Stems seuls        → extraction *_current.*, conversion WAV→MP3, Track créé
  - Stems seuls, extraction échoue → Redis 'error', pas de Track
  - Aucun audio dispo  → Redis 'error', ToplineProcessingError
  - Image auto-générée vs copiée
  - Failure DB         → rollback, Redis 'error'
  - User introuvable   → return silencieux, Redis 'error'

Isolation :
  - create_app() patchée pour utiliser l'app de test SQLite en mémoire
  - extensions.redis_client remplacé par MagicMock
  - apply_watermark_and_trim / convert_to_mp3 / extract_primary_from_stems mockés
  - generate_track_image mockée
"""
import uuid
import pytest
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch, call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_worker(app, payload, mock_redis=None):
    """Lance process_track_data en patchant create_app et redis_client."""
    if mock_redis is None:
        mock_redis = MagicMock()
    from tasks.track_processing import process_track_data
    with patch('tasks.track_processing.create_app', return_value=app), \
         patch('extensions.redis_client', mock_redis):
        process_track_data(payload)
    return mock_redis


def _redis_statuses(mock_redis) -> list:
    """Extrait la liste ordonnée des statuts Redis émis."""
    return [
        (c.kwargs.get('mapping') or (c.args[1] if len(c.args) > 1 else {})).get('status')
        for c in mock_redis.hset.call_args_list
        if isinstance((c.kwargs.get('mapping') or (c.args[1] if len(c.args) > 1 else {})), dict)
    ]


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def worker_user(db):
    """Beatmaker avec 10 tokens upload."""
    from models import User
    from tests.scenarios import _teardown_user
    u = User(
        email=f'worker_track_{uuid.uuid4().hex[:6]}@test.laprod.fr',
        username=f'worker_track_{uuid.uuid4().hex[:6]}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_beatmaker=True,
        subscription_plan='pro',
        upload_track_tokens=10,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    _teardown_user(db, u)


@pytest.fixture()
def base_payload(tmp_path, worker_user):
    """Payload minimal — aucun fichier audio défini (sera complété par chaque test)."""
    jid = str(uuid.uuid4())
    preview_path = tmp_path / 'preview.mp3'
    preview_path.write_bytes(b'\xff\xfb' + b'\x00' * 100)

    return {
        'job_id':                    jid,
        'user_id':                   worker_user.id,
        'safe_title':                'TestBeat',
        'unique_id':                 'abc12345',
        'title':                     'Test Beat',
        'bpm':                       120,
        'key':                       'C major',
        'style':                     'Trap',
        'price_mp3':                 9.99,
        'price_wav':                 19.99,
        'price_stems':               49.99,
        'sacem_percentage_composer': 50,
        'file_hash':                 uuid.uuid4().hex,
        'mp3_disk_path':             None,
        'mp3_filename':              None,
        'wav_disk_path':             None,
        'wav_filename':              None,
        'stems_disk_path':           None,
        'stems_filename':            None,
        'preview_disk_path':         str(preview_path),
        'preview_filename':          'preview.mp3',
        'image_filename':            None,
        'image_disk_path':           None,
        'tag_ids':                   [],
        'artist_ids':                [],
        'playlist_ids':              [],
    }


@pytest.fixture()
def mock_audio_fns():
    """Mocke les fonctions audio du processing (pas de vrai I/O son)."""
    with patch('tasks.track_processing.apply_watermark_and_trim'), \
         patch('tasks.track_processing.convert_to_mp3', return_value=True), \
         patch('tasks.track_processing.extract_primary_from_stems') as mock_ext, \
         patch('tasks.track_processing.generate_track_image'), \
         patch('tasks.track_processing.shutil.copy'):
        yield mock_ext


def _cleanup_tracks(db, job_id=None, title=None):
    """Supprime les tracks créés par le worker après chaque test."""
    from models import Track
    if job_id:
        # Les tracks créés par le worker ne stockent pas job_id directement
        pass
    if title:
        for t in db.session.query(Track).filter_by(title=title).all():
            db.session.delete(t)
        db.session.commit()


# ── Mode MP3 seul ─────────────────────────────────────────────────────────────

class TestWorkerMp3Only:

    def test_track_created_with_mp3_filename(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Mode MP3 seul → Track.file_mp3 renseigné, Track en DB."""
        from models import Track
        mp3 = tmp_path / 'TestBeat_abc12345_full.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)

        _run_worker(app, base_payload)

        track = db.session.query(Track).filter_by(title='Test Beat').first()
        assert track is not None
        assert track.file_mp3 == mp3.name
        db.session.delete(track)
        db.session.commit()

    def test_redis_progresses_started_to_done(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Les statuts Redis passent par started → finalizing → done."""
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)

        mock_redis = _run_worker(app, base_payload)
        statuses = _redis_statuses(mock_redis)

        assert 'started'    in statuses
        assert 'finalizing' in statuses
        assert 'done'       in statuses
        assert statuses.index('started') < statuses.index('done')

        from models import Track
        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_redis_done_contains_track_id(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Redis 'done' contient l'id du track créé."""
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)

        mock_redis = _run_worker(app, base_payload)
        done = next(
            (c.kwargs.get('mapping') or c.args[1])
            for c in mock_redis.hset.call_args_list
            if (c.kwargs.get('mapping') or c.args[1]).get('status') == 'done'
        )
        assert 'track_id' in done

        from models import Track
        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_upload_token_decremented(self, app, db, mock_audio_fns, base_payload, tmp_path, worker_user):
        """L'upload décrémente le compteur de tokens du beatmaker."""
        from models import Track, User
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)
        initial_tokens = worker_user.upload_track_tokens

        _run_worker(app, base_payload)

        db.session.expire(worker_user)
        updated = db.session.get(User, worker_user.id)
        assert updated.upload_track_tokens == initial_tokens - 1

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_watermark_called_with_mp3_as_source(self, app, db, base_payload, tmp_path):
        """apply_watermark_and_trim est appelé avec le MP3 comme source."""
        from models import Track
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)

        with patch('tasks.track_processing.apply_watermark_and_trim') as mock_wm, \
             patch('tasks.track_processing.convert_to_mp3', return_value=True), \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_wm.assert_called_once()
        call_kwargs = mock_wm.call_args.kwargs
        assert call_kwargs.get('input_path') == str(mp3)

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()


# ── Mode WAV seul ─────────────────────────────────────────────────────────────

class TestWorkerWavOnly:

    def test_convert_to_mp3_called(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Mode WAV seul → convert_to_mp3 est appelé."""
        from models import Track
        wav = tmp_path / 'TestBeat_abc12345_full.wav'
        wav.write_bytes(b'RIFF' + b'\x00' * 500)
        mp3_path = tmp_path / 'TestBeat_abc12345_full.mp3'
        mp3_path.write_bytes(b'\xff\xfb' + b'\x00' * 100)  # créé par convert_to_mp3 simulé
        base_payload.update(wav_disk_path=str(wav), wav_filename=wav.name)

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True) as mock_conv, \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_conv.assert_called_once()
        args = mock_conv.call_args
        assert str(wav) in str(args)

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_track_created_with_wav_filename(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Track.file_wav renseigné après traitement WAV seul."""
        from models import Track
        wav = tmp_path / 'TestBeat_abc12345_full.wav'
        wav.write_bytes(b'RIFF' + b'\x00' * 500)
        base_payload.update(wav_disk_path=str(wav), wav_filename=wav.name)

        _run_worker(app, base_payload)

        track = db.session.query(Track).filter_by(title='Test Beat').first()
        assert track is not None
        assert track.file_wav == wav.name

        db.session.delete(track)
        db.session.commit()


# ── Mode MP3 + WAV ────────────────────────────────────────────────────────────

class TestWorkerMp3AndWav:

    def test_both_filenames_stored_in_track(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Track.file_mp3 ET Track.file_wav renseignés quand les deux sont fournis."""
        from models import Track
        mp3 = tmp_path / 'beat_full.mp3'
        wav = tmp_path / 'beat_full.wav'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        wav.write_bytes(b'RIFF' + b'\x00' * 500)
        base_payload.update(
            mp3_disk_path=str(mp3), mp3_filename=mp3.name,
            wav_disk_path=str(wav), wav_filename=wav.name,
        )

        _run_worker(app, base_payload)

        track = db.session.query(Track).filter_by(title='Test Beat').first()
        assert track.file_mp3 == mp3.name
        assert track.file_wav == wav.name

        db.session.delete(track)
        db.session.commit()

    def test_convert_not_called_when_mp3_present(self, app, db, base_payload, tmp_path):
        """convert_to_mp3 n'est PAS appelé quand un MP3 est déjà disponible."""
        from models import Track
        mp3 = tmp_path / 'beat.mp3'
        wav = tmp_path / 'beat.wav'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        wav.write_bytes(b'RIFF' + b'\x00' * 500)
        base_payload.update(
            mp3_disk_path=str(mp3), mp3_filename=mp3.name,
            wav_disk_path=str(wav), wav_filename=wav.name,
        )

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3') as mock_conv, \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_conv.assert_not_called()

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()


# ── Mode stems seuls ──────────────────────────────────────────────────────────

class TestWorkerStemsOnly:

    def test_extract_primary_called_for_stems_only(self, app, db, base_payload, tmp_path):
        """extract_primary_from_stems est appelé quand seul stems_disk_path est fourni."""
        from models import Track
        stems = tmp_path / 'stems.zip'
        stems.write_bytes(b'PK' + b'\x00' * 100)
        extracted_wav = tmp_path / 'TestBeat_abc12345_full.wav'
        extracted_wav.write_bytes(b'RIFF' + b'\x00' * 500)
        base_payload.update(stems_disk_path=str(stems), stems_filename='stems.zip')

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True), \
             patch('tasks.track_processing.extract_primary_from_stems',
                   return_value=(extracted_wav, extracted_wav.name, '.wav')) as mock_ext, \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_ext.assert_called_once()
        args = mock_ext.call_args.args
        assert str(stems) == str(args[0])

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_wav_to_mp3_conversion_after_stems_extraction(self, app, db, base_payload, tmp_path):
        """Après extraction WAV depuis stems, convert_to_mp3 est appelé."""
        from models import Track
        stems = tmp_path / 'stems.zip'
        stems.write_bytes(b'PK' + b'\x00' * 100)
        extracted_wav = tmp_path / 'TestBeat_abc12345_full.wav'
        extracted_wav.write_bytes(b'RIFF' + b'\x00' * 500)
        base_payload.update(stems_disk_path=str(stems), stems_filename='stems.zip')

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True) as mock_conv, \
             patch('tasks.track_processing.extract_primary_from_stems',
                   return_value=(extracted_wav, extracted_wav.name, '.wav')), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_conv.assert_called_once()

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_mp3_stem_skips_wav_conversion(self, app, db, base_payload, tmp_path):
        """Si le stems extrait est un MP3, convert_to_mp3 n'est pas appelé."""
        from models import Track
        stems = tmp_path / 'stems.zip'
        stems.write_bytes(b'PK' + b'\x00' * 100)
        extracted_mp3 = tmp_path / 'TestBeat_abc12345_full.mp3'
        extracted_mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(stems_disk_path=str(stems), stems_filename='stems.zip')

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3') as mock_conv, \
             patch('tasks.track_processing.extract_primary_from_stems',
                   return_value=(extracted_mp3, extracted_mp3.name, '.mp3')), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_conv.assert_not_called()

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_stems_extraction_failure_sets_redis_error(self, app, db, base_payload, tmp_path):
        """Échec d'extraction stems → Redis 'error', pas de Track créé."""
        from models import Track
        stems = tmp_path / 'stems.zip'
        stems.write_bytes(b'PK' + b'\x00' * 100)
        base_payload.update(stems_disk_path=str(stems), stems_filename='stems.zip')

        mock_redis = MagicMock()
        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True), \
             patch('tasks.track_processing.extract_primary_from_stems',
                   return_value=(None, None, None)), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            try:
                _run_worker(app, base_payload, mock_redis)
            except Exception:
                pass

        statuses = _redis_statuses(mock_redis)
        assert 'error' in statuses

        count = db.session.query(Track).filter_by(title='Test Beat').count()
        assert count == 0


# ── Chemins d'erreur ──────────────────────────────────────────────────────────

class TestWorkerFailurePaths:

    def test_user_not_found_sets_error_no_raise(self, app, db, base_payload):
        """User introuvable → Redis 'error' + return silencieux (pas d'exception)."""
        bad_payload = {**base_payload, 'user_id': 999999}
        mock_redis = MagicMock()
        _run_worker(app, bad_payload, mock_redis)  # ne doit pas lever
        statuses = _redis_statuses(mock_redis)
        assert 'error' in statuses

    def test_no_audio_after_processing_sets_error(self, app, db, base_payload, tmp_path):
        """Si aucun audio disponible après toutes les étapes → Redis 'error'."""
        # Payload sans mp3/wav/stems → pas de source audio primaire
        from tasks.track_processing import TrackProcessingError
        mock_redis = MagicMock()
        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=False), \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'):
            with pytest.raises(TrackProcessingError):
                _run_worker(app, base_payload, mock_redis)

        statuses = _redis_statuses(mock_redis)
        assert 'error' in statuses

    def test_db_failure_rolls_back_and_sets_error(self, app, db, base_payload, tmp_path):
        """Erreur DB lors du commit → rollback + Redis 'error' + exception levée."""
        from models import Track
        from tasks.track_processing import TrackProcessingError
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)

        mock_redis = MagicMock()
        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True), \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image'), \
             patch('tasks.track_processing.shutil.copy'), \
             patch('tasks.track_processing.db.session.commit',
                   side_effect=Exception('Simulated DB failure')):
            with pytest.raises((TrackProcessingError, Exception)):
                _run_worker(app, base_payload, mock_redis)

        statuses = _redis_statuses(mock_redis)
        assert 'error' in statuses

    def test_image_auto_generated_when_no_image(self, app, db, base_payload, tmp_path):
        """Sans image uploadée, generate_track_image est appelée."""
        from models import Track
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name,
                            image_filename=None, image_disk_path=None)

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True), \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image') as mock_gen, \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_gen.assert_called_once()

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()

    def test_image_copied_when_image_provided(self, app, db, base_payload, tmp_path):
        """Avec image uploadée, shutil.copy est appelé (generate_track_image non)."""
        from models import Track
        mp3 = tmp_path / 'beat.mp3'
        img = tmp_path / 'cover.jpg'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        img.write_bytes(b'\xff\xd8\xff' + b'\x00' * 100)
        base_payload.update(
            mp3_disk_path=str(mp3), mp3_filename=mp3.name,
            image_filename='cover.jpg',
            image_disk_path=str(img),
        )

        with patch('tasks.track_processing.apply_watermark_and_trim'), \
             patch('tasks.track_processing.convert_to_mp3', return_value=True), \
             patch('tasks.track_processing.extract_primary_from_stems'), \
             patch('tasks.track_processing.generate_track_image') as mock_gen, \
             patch('tasks.track_processing.shutil.copy'):
            _run_worker(app, base_payload)

        mock_gen.assert_not_called()

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()


# ── Performance ───────────────────────────────────────────────────────────────

class TestWorkerPerformance:

    def test_worker_overhead_under_2s_with_mocked_audio(self, app, db, mock_audio_fns, base_payload, tmp_path):
        """Hors traitement audio (tout mocké), le worker doit finir en < 2s."""
        import time
        from models import Track
        mp3 = tmp_path / 'beat.mp3'
        mp3.write_bytes(b'\xff\xfb' + b'\x00' * 500)
        base_payload.update(mp3_disk_path=str(mp3), mp3_filename=mp3.name)

        start = time.perf_counter()
        _run_worker(app, base_payload)
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, f"Worker trop lent (hors audio) : {elapsed:.2f}s (budget : 2s)"

        t = db.session.query(Track).filter_by(title='Test Beat').first()
        if t:
            db.session.delete(t)
            db.session.commit()
