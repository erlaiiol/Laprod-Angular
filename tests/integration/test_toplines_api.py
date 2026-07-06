"""
Tests d'intégration — API Toplines (routes/toplines_api.py + routes/streaming_service.py)

Couvre les 6 endpoints CRUD et le streaming :
  GET    /api/toplines/track/<id>    → toplines publiées (public)
  GET    /api/toplines/my/<id>       → toplines perso (JWT)
  POST   /api/toplines/upload        → upload voix + quota + enqueue RQ
  POST   /api/toplines/<id>/publish  → publication (propriétaire)
  POST   /api/toplines/<id>/unpublish
  DELETE /api/toplines/<id>          → suppression (propriétaire + fichier)
  GET    /api/stream/toplines/<id>   → streaming audio (publié = public, sinon propriétaire)

Stratégie de mocking pour /upload :
  - config.UPLOAD_FOLDER  → tmp_path pytest (isolé, nettoyé automatiquement)
  - routes.toplines_api.redis_client → MagicMock (assertions sur les appels Redis)
  - routes.toplines_api.Queue        → MagicMock (assertions sur le payload RQ)
  Le fichier brut est physiquement sauvé dans tmp_path pour vérifier le comportement réel.
"""
import io
import struct
import time
import uuid
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free, user_artist  # noqa: F401
from tests.scenarios.tracks import track_default_prices  # noqa: F401


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_voice():
    """Blob audio webm stub 1KB — dépasse la validation de taille minimale (512 octets)."""
    return (io.BytesIO(b'\x1aE\xdf\xa3' + b'\x00' * 1020), 'voice.webm', 'audio/webm')


def _fake_voice_iphone():
    """Blob audio MP4/M4A stub simulant Safari iOS (audio/mp4, 1KB)."""
    return (io.BytesIO(b'\x00\x00\x00\x18ftypm4a ' + b'\x00' * 1000), 'voice.mp4', 'audio/mp4')


def _fake_voice_empty():
    """Blob audio trop petit pour être valide (< 512 octets)."""
    return (io.BytesIO(b'\x1aE\xdf\xa3' + b'\x00' * 10), 'voice.webm', 'audio/webm')


def _upload_payload(track_id, *, voice=None, autotune='false', description=''):
    return {
        'voice_file': voice if voice is not None else _fake_voice(),
        'track_id': str(track_id),
        'use_autotune': autotune,
        'description': description,
    }


def _minimal_wav_bytes():
    """Génère 44 octets d'un WAV PCM valide (0 sample) — pour les tests de streaming."""
    sr, ch, bps = 44100, 1, 16
    return struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 36, b'WAVE',
        b'fmt ', 16, 1, ch, sr, sr * ch * bps // 8, ch * bps // 8, bps,
        b'data', 0,
    )


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture()
def artist_headers(app, user_artist):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user_artist.id))
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture()
def topline(db, user_artist, track_default_prices):
    """Topline non publiée, appartient à user_artist."""
    from models import Topline
    tl = Topline(
        track_id=track_default_prices.id,
        artist_id=user_artist.id,
        audio_file='audio/toplines/topline_test_fixture.wav',
        description='Description de test',
        is_published=False,
    )
    db.session.add(tl)
    db.session.commit()
    yield tl
    db.session.rollback()
    existing = db.session.get(Topline, tl.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def published_topline(db, user_artist, track_default_prices):
    """Topline publiée, appartient à user_artist."""
    from models import Topline
    tl = Topline(
        track_id=track_default_prices.id,
        artist_id=user_artist.id,
        audio_file='audio/toplines/topline_published_fixture.wav',
        description='Topline publiée',
        is_published=True,
    )
    db.session.add(tl)
    db.session.commit()
    yield tl
    db.session.rollback()
    existing = db.session.get(Topline, tl.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def other_user_headers(app, db):
    """Second artiste pour les tests d'ownership violation."""
    from models import User
    from tests.scenarios import _teardown_user
    from flask_jwt_extended import create_access_token
    uid = uuid.uuid4().hex[:6]
    u = User(
        email=f'other_{uid}@test.laprod.fr',
        username=f'other_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_artist=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    with app.app_context():
        token = create_access_token(identity=str(u.id))
    yield {'Authorization': f'Bearer {token}'}, u
    _teardown_user(db, u)


@pytest.fixture()
def topline_with_file(db, app, user_artist, track_default_prices):
    """Topline avec un vrai fichier WAV sur disque — nécessaire pour send_file()."""
    from models import Topline
    fname = f'topline_stream_test_{uuid.uuid4().hex[:8]}.wav'
    audio_dir = Path(app.root_path) / 'db_assets' / 'audio' / 'toplines'
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / fname
    audio_path.write_bytes(_minimal_wav_bytes())

    tl = Topline(
        track_id=track_default_prices.id,
        artist_id=user_artist.id,
        audio_file=f'audio/toplines/{fname}',
        is_published=False,
    )
    db.session.add(tl)
    db.session.commit()
    yield tl
    db.session.rollback()
    existing = db.session.get(Topline, tl.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()
    if audio_path.exists():
        audio_path.unlink()


# ── Helper upload mocké ────────────────────────────────────────────────────────

def _upload(client, track_id, headers, tmp_dir, *, voice=None, **kwargs):
    """POST /upload avec UPLOAD_FOLDER, redis et Queue mockés."""
    import config
    mock_redis = MagicMock()
    mock_queue = MagicMock()
    with patch.object(config, 'UPLOAD_FOLDER', tmp_dir), \
         patch('routes.toplines_api.redis_client', mock_redis), \
         patch('routes.toplines_api.Queue', MagicMock(return_value=mock_queue)):
        resp = client.post(
            '/api/toplines/upload',
            data=_upload_payload(track_id, voice=voice, **kwargs),
            content_type='multipart/form-data',
            headers=headers,
        )
    return resp, mock_redis, mock_queue


# ── GET /api/toplines/track/<id> ──────────────────────────────────────────────

class TestGetTrackToplines:

    def test_returns_only_published_toplines(
        self, client, published_topline, topline, track_default_prices
    ):
        """La route publique ne retourne que les toplines is_published=True."""
        resp = client.get(f'/api/toplines/track/{track_default_prices.id}')
        assert resp.status_code == 200
        ids = [tl['id'] for tl in resp.json['data']['toplines']]
        assert published_topline.id in ids
        assert topline.id not in ids

    def test_response_shape(self, client, published_topline, track_default_prices):
        """Vérifie que le serializer retourne les champs attendus par le front."""
        resp = client.get(f'/api/toplines/track/{track_default_prices.id}')
        tl = resp.json['data']['toplines'][0]
        for field in ('id', 'stream_url', 'description', 'is_published', 'created_at', 'artist_user'):
            assert field in tl, f"Champ manquant dans le serializer : {field}"
        assert tl['stream_url'] == f'/api/stream/toplines/{published_topline.id}'

    def test_empty_list_when_no_toplines(self, client, track_default_prices):
        resp = client.get(f'/api/toplines/track/{track_default_prices.id}')
        assert resp.status_code == 200
        assert resp.json['data']['toplines'] == []

    def test_unknown_track_returns_404(self, client):
        resp = client.get('/api/toplines/track/999999')
        assert resp.status_code == 404


# ── GET /api/toplines/my/<id> ─────────────────────────────────────────────────

class TestGetMyToplines:

    def test_requires_authentication(self, client, track_default_prices):
        resp = client.get(f'/api/toplines/my/{track_default_prices.id}')
        assert resp.status_code == 401

    def test_returns_all_own_toplines_including_unpublished(
        self, client, artist_headers, published_topline, topline, track_default_prices
    ):
        """Un artiste voit ses toplines publiées ET privées."""
        resp = client.get(f'/api/toplines/my/{track_default_prices.id}', headers=artist_headers)
        assert resp.status_code == 200
        ids = {tl['id'] for tl in resp.json['data']['toplines']}
        assert published_topline.id in ids
        assert topline.id in ids

    def test_does_not_return_others_toplines(
        self, client, other_user_headers, topline, track_default_prices
    ):
        """Un artiste ne voit pas les toplines d'un autre utilisateur."""
        other_hdrs, _ = other_user_headers
        resp = client.get(f'/api/toplines/my/{track_default_prices.id}', headers=other_hdrs)
        assert resp.status_code == 200
        ids = [tl['id'] for tl in resp.json['data']['toplines']]
        assert topline.id not in ids


# ── POST /api/toplines/upload ─────────────────────────────────────────────────

class TestUploadTopline:

    def test_requires_authentication(self, client):
        resp = client.post('/api/toplines/upload', data={})
        assert resp.status_code == 401

    def test_happy_path_returns_job_id(self, client, tmp_path, artist_headers, track_default_prices):
        """Upload valide → 200 avec un job_id UUID."""
        resp, _, _ = _upload(client, track_default_prices.id, artist_headers, tmp_path)
        assert resp.status_code == 200
        job_id = resp.json['data']['job_id']
        uuid.UUID(job_id)  # lève ValueError si non-UUID

    def test_raw_file_saved_to_upload_folder(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Le fichier brut est sauvegardé physiquement dans <UPLOAD_FOLDER>/toplines/."""
        _upload(client, track_default_prices.id, artist_headers, tmp_path)
        saved = list((tmp_path / 'toplines').glob('topline_raw_*.webm'))
        assert len(saved) == 1

    def test_redis_job_status_initialized_to_queued(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Le statut initial du job dans Redis doit être 'queued'."""
        _, mock_redis, _ = _upload(client, track_default_prices.id, artist_headers, tmp_path)
        first_hset = mock_redis.hset.call_args_list[0]
        mapping = first_hset.kwargs.get('mapping') or first_hset.args[1]
        assert mapping['status'] == 'queued'

    def test_redis_ttl_set_on_job_key(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Le TTL Redis est défini sur la clé du job."""
        _, mock_redis, _ = _upload(client, track_default_prices.id, artist_headers, tmp_path)
        mock_redis.expire.assert_called_once()
        ttl = mock_redis.expire.call_args.args[1]
        assert ttl == 7200

    def test_rq_enqueued_with_correct_task_path(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Le job RQ pointe vers la bonne fonction worker."""
        _, _, mock_queue = _upload(client, track_default_prices.id, artist_headers, tmp_path)
        mock_queue.enqueue.assert_called_once()
        assert mock_queue.enqueue.call_args.args[0] == 'tasks.topline_processing.process_topline_data'

    def test_rq_payload_contains_expected_fields(
        self, client, tmp_path, artist_headers, user_artist, track_default_prices
    ):
        """Le payload transmis au worker contient tous les champs métier."""
        _, _, mock_queue = _upload(client, track_default_prices.id, artist_headers, tmp_path)
        payload = mock_queue.enqueue.call_args.args[1]
        assert payload['user_id']         == user_artist.id
        assert payload['track_id']        == track_default_prices.id
        assert payload['use_autotune']    is False
        assert payload['beat_audio_file'] == track_default_prices.audio_file
        assert payload['track_key']       == track_default_prices.key
        assert 'job_id'    in payload
        assert 'raw_path'  in payload
        assert 'timestamp' in payload

    def test_autotune_flag_forwarded_correctly(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """use_autotune='true' dans le form → payload worker avec use_autotune=True."""
        _, _, mock_queue = _upload(
            client, track_default_prices.id, artist_headers, tmp_path, autotune='true'
        )
        assert mock_queue.enqueue.call_args.args[1]['use_autotune'] is True

    def test_description_stripped_and_forwarded(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """La description est nettoyée (strip + limit 500) et forwarded au worker."""
        _, _, mock_queue = _upload(
            client, track_default_prices.id, artist_headers, tmp_path,
            description='  Ma topline vocale  ',
        )
        assert mock_queue.enqueue.call_args.args[1]['description'] == 'Ma topline vocale'

    def test_description_truncated_at_500_chars(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        _, _, mock_queue = _upload(
            client, track_default_prices.id, artist_headers, tmp_path,
            description='X' * 600,
        )
        desc = mock_queue.enqueue.call_args.args[1]['description']
        assert len(desc) == 500

    def test_quota_exceeded_returns_403_and_nothing_enqueued(
        self, client, tmp_path, db, artist_headers, user_artist, track_default_prices
    ):
        """Tokens épuisés → 403 QUOTA_EXCEEDED, aucun job enqueued."""
        user_artist.topline_tokens = 0
        db.session.commit()
        import config
        mock_queue = MagicMock()
        with patch.object(config, 'UPLOAD_FOLDER', tmp_path), \
             patch('routes.toplines_api.redis_client', MagicMock()), \
             patch('routes.toplines_api.Queue', MagicMock(return_value=mock_queue)):
            resp = client.post(
                '/api/toplines/upload',
                data=_upload_payload(track_default_prices.id),
                content_type='multipart/form-data',
                headers=artist_headers,
            )
        assert resp.status_code == 403
        assert resp.json['code'] == 'QUOTA_EXCEEDED'
        mock_queue.enqueue.assert_not_called()

    def test_missing_voice_file_returns_400(self, client, artist_headers, track_default_prices):
        import config
        with patch.object(config, 'UPLOAD_FOLDER', Path('/tmp')), \
             patch('routes.toplines_api.redis_client', MagicMock()), \
             patch('routes.toplines_api.Queue', MagicMock()):
            resp = client.post(
                '/api/toplines/upload',
                data={'track_id': str(track_default_prices.id)},
                content_type='multipart/form-data',
                headers=artist_headers,
            )
        assert resp.status_code == 400
        assert resp.json['code'] == 'VALIDATION_ERROR'

    def test_missing_track_id_returns_400(self, client, artist_headers):
        import config
        with patch.object(config, 'UPLOAD_FOLDER', Path('/tmp')), \
             patch('routes.toplines_api.redis_client', MagicMock()), \
             patch('routes.toplines_api.Queue', MagicMock()):
            resp = client.post(
                '/api/toplines/upload',
                data={'voice_file': _fake_voice()},
                content_type='multipart/form-data',
                headers=artist_headers,
            )
        assert resp.status_code == 400
        assert resp.json['code'] == 'VALIDATION_ERROR'

    def test_unknown_track_returns_404(self, client, tmp_path, artist_headers):
        resp, _, _ = _upload(client, 999999, artist_headers, tmp_path)
        assert resp.status_code == 404
        assert resp.json['code'] == 'TRACK_NOT_FOUND'

    def test_unapproved_track_returns_403(
        self, client, tmp_path, db, artist_headers, track_default_prices
    ):
        track_default_prices.is_approved = False
        db.session.commit()
        try:
            resp, _, _ = _upload(client, track_default_prices.id, artist_headers, tmp_path)
            assert resp.status_code == 403
            assert resp.json['code'] == 'TRACK_UNAVAILABLE'
        finally:
            track_default_prices.is_approved = True
            db.session.commit()

    def test_upload_response_time_under_500ms(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """
        L'upload (I/O fichier + init Redis + enqueue) doit répondre en < 500ms.
        Cette assertion permet de détecter des régressions de performance futures.
        """
        start = time.perf_counter()
        _upload(client, track_default_prices.id, artist_headers, tmp_path)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"Upload trop lent : {elapsed_ms:.0f}ms (budget : 500ms)"

    def test_weekly_quota_reset_allows_upload(
        self, client, tmp_path, db, artist_headers, user_artist, track_default_prices, app
    ):
        """
        Un utilisateur dont les tokens sont épuisés récupère son quota
        après la période de reset hebdomadaire.
        """
        from datetime import date, timedelta
        user_artist.topline_tokens = 0
        user_artist.last_topline_reset = date.today() - timedelta(days=8)
        db.session.commit()

        resp, _, _ = _upload(client, track_default_prices.id, artist_headers, tmp_path)
        assert resp.status_code == 200, f"Reset hebdo non appliqué : {resp.json}"

    def test_iphone_mp4_upload_accepted_and_saved_as_m4a(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Safari iOS envoie audio/mp4 — le fichier doit être sauvé en .m4a."""
        resp, _, mock_queue = _upload(
            client, track_default_prices.id, artist_headers, tmp_path,
            voice=_fake_voice_iphone(),
        )
        assert resp.status_code == 200, f"Upload iPhone rejeté : {resp.json}"
        saved = list((tmp_path / 'toplines').glob('topline_raw_*.m4a'))
        assert len(saved) == 1, "Le fichier MP4 iPhone devrait être sauvé en .m4a"
        mock_queue.enqueue.assert_called_once()

    def test_empty_file_returns_400_invalid_audio(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Un fichier audio trop petit (< 512 octets) doit retourner 400 INVALID_AUDIO."""
        resp, _, mock_queue = _upload(
            client, track_default_prices.id, artist_headers, tmp_path,
            voice=_fake_voice_empty(),
        )
        assert resp.status_code == 400
        assert resp.json['code'] == 'INVALID_AUDIO'
        mock_queue.enqueue.assert_not_called()

    def test_ogg_upload_accepted_and_saved_as_ogg(
        self, client, tmp_path, artist_headers, track_default_prices
    ):
        """Chrome Android peut envoyer audio/ogg — sauvé en .ogg."""
        ogg_voice = (io.BytesIO(b'OggS' + b'\x00' * 1020), 'voice.ogg', 'audio/ogg')
        resp, _, mock_queue = _upload(
            client, track_default_prices.id, artist_headers, tmp_path,
            voice=ogg_voice,
        )
        assert resp.status_code == 200
        saved = list((tmp_path / 'toplines').glob('topline_raw_*.ogg'))
        assert len(saved) == 1


# ── POST /api/toplines/upload-processed ───────────────────────────────────────
#
# Chemin mobile natif (studio Capacitor) : le mix vocal+beat est déjà fait côté
# client, on reçoit directement un MP3 final. Pas de job RQ — écriture DB directe,
# is_mobile_processed=True. Contrairement à /upload, un JWT est obligatoire (pas
# de guest) et le fichier est validé comme MP3/WAV/MP4 déjà traité, pas une voix brute.

def _fake_processed_mp3():
    """Blob MP3 stub 1KB — dépasse la validation de taille minimale (512 octets)."""
    return (io.BytesIO(b'ID3\x03\x00\x00\x00' + b'\x00' * 1016), 'maquette.mp3', 'audio/mpeg')


def _fake_processed_empty():
    return (io.BytesIO(b'ID3' + b'\x00' * 10), 'maquette.mp3', 'audio/mpeg')


def _upload_processed(client, track_id, headers, *, processed=None, description=None):
    data = {
        'processed_file': processed if processed is not None else _fake_processed_mp3(),
        'track_id': str(track_id),
    }
    if description is not None:
        data['description'] = description
    return client.post(
        '/api/toplines/upload-processed',
        data=data,
        content_type='multipart/form-data',
        headers=headers,
    )


class TestUploadProcessedTopline:

    def test_requires_authentication(self, client, track_default_prices):
        resp = client.post(
            '/api/toplines/upload-processed',
            data={'processed_file': _fake_processed_mp3(), 'track_id': str(track_default_prices.id)},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 401

    def test_happy_path_returns_topline_id(self, client, artist_headers, track_default_prices):
        resp = _upload_processed(client, track_default_prices.id, artist_headers)
        assert resp.status_code == 200, resp.json
        assert resp.json['success'] is True
        assert isinstance(resp.json['data']['topline_id'], int)

    def test_topline_persisted_with_is_mobile_processed_true(
        self, client, db, artist_headers, track_default_prices
    ):
        from models import Topline
        resp = _upload_processed(client, track_default_prices.id, artist_headers)
        tl = db.session.get(Topline, resp.json['data']['topline_id'])
        assert tl is not None
        assert tl.is_mobile_processed is True
        assert tl.is_published is False

    def test_token_consumed_on_success(
        self, client, db, artist_headers, user_artist, track_default_prices
    ):
        before = user_artist.topline_tokens
        _upload_processed(client, track_default_prices.id, artist_headers)
        db.session.refresh(user_artist)
        assert user_artist.topline_tokens == before - 1

    def test_quota_exceeded_returns_403(
        self, client, db, artist_headers, user_artist, track_default_prices
    ):
        user_artist.topline_tokens = 0
        db.session.commit()
        resp = _upload_processed(client, track_default_prices.id, artist_headers)
        assert resp.status_code == 403
        assert resp.json['code'] == 'QUOTA_EXCEEDED'

    def test_missing_processed_file_returns_400(self, client, artist_headers, track_default_prices):
        resp = client.post(
            '/api/toplines/upload-processed',
            data={'track_id': str(track_default_prices.id)},
            content_type='multipart/form-data',
            headers=artist_headers,
        )
        assert resp.status_code == 400
        assert resp.json['code'] == 'VALIDATION_ERROR'

    def test_missing_track_id_returns_400(self, client, artist_headers):
        resp = client.post(
            '/api/toplines/upload-processed',
            data={'processed_file': _fake_processed_mp3()},
            content_type='multipart/form-data',
            headers=artist_headers,
        )
        assert resp.status_code == 400
        assert resp.json['code'] == 'VALIDATION_ERROR'

    def test_invalid_format_rejected(self, client, artist_headers, track_default_prices):
        bad_file = (io.BytesIO(b'\x1aE\xdf\xa3' + b'\x00' * 1020), 'voice.webm', 'audio/webm')
        resp = _upload_processed(client, track_default_prices.id, artist_headers, processed=bad_file)
        assert resp.status_code == 400
        assert resp.json['code'] == 'INVALID_FORMAT'

    def test_empty_file_returns_400_invalid_audio(self, client, artist_headers, track_default_prices):
        resp = _upload_processed(
            client, track_default_prices.id, artist_headers, processed=_fake_processed_empty(),
        )
        assert resp.status_code == 400
        assert resp.json['code'] == 'INVALID_AUDIO'

    def test_unknown_track_returns_404(self, client, artist_headers):
        resp = _upload_processed(client, 999999, artist_headers)
        assert resp.status_code == 404
        assert resp.json['code'] == 'TRACK_NOT_FOUND'

    def test_unapproved_track_returns_403(
        self, client, db, artist_headers, track_default_prices
    ):
        track_default_prices.is_approved = False
        db.session.commit()
        try:
            resp = _upload_processed(client, track_default_prices.id, artist_headers)
            assert resp.status_code == 403
            assert resp.json['code'] == 'TRACK_UNAVAILABLE'
        finally:
            track_default_prices.is_approved = True
            db.session.commit()

    def test_description_forwarded(self, client, db, artist_headers, track_default_prices):
        from models import Topline
        resp = _upload_processed(
            client, track_default_prices.id, artist_headers, description='Ma maquette mobile',
        )
        tl = db.session.get(Topline, resp.json['data']['topline_id'])
        assert tl.description == 'Ma maquette mobile'

    def test_no_rq_job_enqueued(self, client, artist_headers, track_default_prices):
        """Contrairement à /upload, le chemin mobile n'utilise aucune queue RQ."""
        mock_queue = MagicMock()
        with patch('routes.toplines_api.Queue', MagicMock(return_value=mock_queue)):
            resp = _upload_processed(client, track_default_prices.id, artist_headers)
        assert resp.status_code == 200
        mock_queue.enqueue.assert_not_called()


# ── POST /api/toplines/<id>/publish ───────────────────────────────────────────

class TestPublishTopline:

    def test_requires_authentication(self, client, topline):
        assert client.post(f'/api/toplines/{topline.id}/publish').status_code == 401

    def test_owner_can_publish(self, client, db, artist_headers, topline):
        resp = client.post(f'/api/toplines/{topline.id}/publish', headers=artist_headers)
        assert resp.status_code == 200
        db.session.expire(topline)
        assert db.session.get(type(topline), topline.id).is_published is True

    def test_publish_returns_updated_topline(self, client, artist_headers, topline):
        resp = client.post(f'/api/toplines/{topline.id}/publish', headers=artist_headers)
        tl = resp.json['data']['topline']
        assert tl['id'] == topline.id
        assert tl['is_published'] is True

    def test_other_user_cannot_publish(self, client, other_user_headers, topline):
        hdrs, _ = other_user_headers
        assert client.post(f'/api/toplines/{topline.id}/publish', headers=hdrs).status_code == 403

    def test_nonexistent_topline_returns_404(self, client, artist_headers):
        assert client.post('/api/toplines/999999/publish', headers=artist_headers).status_code == 404


# ── POST /api/toplines/<id>/unpublish ─────────────────────────────────────────

class TestUnpublishTopline:

    def test_owner_can_unpublish(self, client, db, artist_headers, published_topline):
        resp = client.post(f'/api/toplines/{published_topline.id}/unpublish', headers=artist_headers)
        assert resp.status_code == 200
        db.session.expire(published_topline)
        assert db.session.get(type(published_topline), published_topline.id).is_published is False

    def test_other_user_cannot_unpublish(self, client, other_user_headers, published_topline):
        hdrs, _ = other_user_headers
        resp = client.post(f'/api/toplines/{published_topline.id}/unpublish', headers=hdrs)
        assert resp.status_code == 403


# ── DELETE /api/toplines/<id> ─────────────────────────────────────────────────

class TestDeleteTopline:

    def test_requires_authentication(self, client, topline):
        assert client.delete(f'/api/toplines/{topline.id}').status_code == 401

    def test_owner_can_delete(self, client, db, artist_headers, topline):
        tid = topline.id
        resp = client.delete(f'/api/toplines/{tid}', headers=artist_headers)
        assert resp.status_code == 200
        assert db.session.get(type(topline), tid) is None

    def test_delete_returns_track_id(self, client, artist_headers, topline, track_default_prices):
        resp = client.delete(f'/api/toplines/{topline.id}', headers=artist_headers)
        assert resp.json['data']['track_id'] == track_default_prices.id

    def test_audio_file_physically_deleted(
        self, client, app, db, artist_headers, user_artist, track_default_prices
    ):
        """Le fichier audio est retiré du disque lors de la suppression."""
        from models import Topline
        fname = f'topline_delete_test_{uuid.uuid4().hex[:8]}.wav'
        audio_dir = Path(app.root_path) / 'db_assets' / 'audio' / 'toplines'
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / fname
        audio_path.write_bytes(_minimal_wav_bytes())

        tl = Topline(
            track_id=track_default_prices.id,
            artist_id=user_artist.id,
            audio_file=f'audio/toplines/{fname}',
            is_published=False,
        )
        db.session.add(tl)
        db.session.commit()

        resp = client.delete(f'/api/toplines/{tl.id}', headers=artist_headers)
        assert resp.status_code == 200
        assert not audio_path.exists(), "Le fichier audio devrait avoir été supprimé"

    def test_other_user_cannot_delete(self, client, other_user_headers, topline):
        hdrs, _ = other_user_headers
        assert client.delete(f'/api/toplines/{topline.id}', headers=hdrs).status_code == 403

    def test_nonexistent_topline_returns_404(self, client, artist_headers):
        assert client.delete('/api/toplines/999999', headers=artist_headers).status_code == 404


# ── GET /api/stream/toplines/<id> ────────────────────────────────────────────

class TestStreamTopline:

    def test_private_topline_requires_auth(self, client, topline_with_file):
        resp = client.get(f'/api/stream/toplines/{topline_with_file.id}')
        assert resp.status_code == 403

    def test_owner_can_stream_private_topline(
        self, client, artist_headers, topline_with_file
    ):
        resp = client.get(
            f'/api/stream/toplines/{topline_with_file.id}',
            headers=artist_headers,
        )
        assert resp.status_code == 200
        assert 'audio' in resp.content_type

    def test_published_topline_streams_without_auth(self, client, db, topline_with_file):
        topline_with_file.is_published = True
        db.session.commit()
        resp = client.get(f'/api/stream/toplines/{topline_with_file.id}')
        assert resp.status_code == 200

    def test_audio_bytes_correspond_to_correct_file(
        self, client, artist_headers, topline_with_file
    ):
        """Le contenu retourné est bien le fichier WAV de la topline (signature RIFF)."""
        resp = client.get(
            f'/api/stream/toplines/{topline_with_file.id}',
            headers=artist_headers,
        )
        assert resp.status_code == 200
        assert resp.data[:4] == b'RIFF'

    def test_nonexistent_topline_returns_404(self, client):
        assert client.get('/api/stream/toplines/999999').status_code == 404

    def test_other_user_cannot_stream_private_topline(
        self, client, other_user_headers, topline_with_file
    ):
        hdrs, _ = other_user_headers
        resp = client.get(f'/api/stream/toplines/{topline_with_file.id}', headers=hdrs)
        assert resp.status_code == 403
