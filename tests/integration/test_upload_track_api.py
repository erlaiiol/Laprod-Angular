"""
Tests d'intégration — POST /api/tracks/post  et  PUT /api/tracks/put/<id>

Couvre :
  - Authentification requise
  - Validation des champs (titre manquant, BPM invalide, fichier absent)
  - Quota de tokens upload
  - Upload valide → job_id renvoyé + RQ enqueued (Redis mocké)
  - PUT avec regenerate_preview=1 → task RQ enqueued
  - PUT sans flag regenerate_preview → pas d'enqueue
"""
import io
import json
import uuid
import contextlib
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _audio_file(name: str = 'beat.mp3'):
    """BytesIO simulant un fichier audio minimal pour multipart/form-data."""
    return (io.BytesIO(b'\xff\xfb' + b'\x00' * 512), name)


def _post_headers(auth_headers: dict) -> dict:
    """Extrait uniquement le header Authorization (sans Content-Type JSON)."""
    return {'Authorization': auth_headers['Authorization']}


def _post_track(client, auth_headers, extra=None):
    data = {
        'title': 'Test Beat Upload',
        'bpm': '120',
        'key': 'C major',
        'style': 'Trap',
        'price_mp3': '9.99',
        'price_wav': '19.99',
        'file_mp3': _audio_file(),
        **(extra or {}),
    }
    return client.post(
        '/api/tracks/post',
        headers=_post_headers(auth_headers),
        data=data,
        content_type='multipart/form-data',
    )


# ── Fixture locale ─────────────────────────────────────────────────────────────

@pytest.fixture()
def track(db, user):
    """Track minimal approuvé, lié à l'utilisateur standard."""
    from models import Track
    t = Track(
        title='Beat à éditer',
        composer_id=user.id,
        file_hash=str(uuid.uuid4()),
        audio_file='old_preview_edit.mp3',
        bpm=120,
        key='C major',
        style='Trap',
        is_approved=True,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


# ── POST /api/tracks/post — authentification ──────────────────────────────────

class TestPostTrackAuth:

    def test_requiert_authentification(self, client):
        resp = client.post('/api/tracks/post')
        assert resp.status_code == 401

    def test_retourne_403_sans_token_upload(self, client, app, db, bound_factories):
        from tests.factories.user_factory import UserFactory
        from flask_jwt_extended import create_access_token
        u = UserFactory(upload_track_tokens=0)
        with app.app_context():
            token = create_access_token(identity=str(u.id))
        resp = client.post(
            '/api/tracks/post',
            headers={'Authorization': f'Bearer {token}'},
            data={},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403


# ── POST /api/tracks/post — validation ───────────────────────────────────────

class TestPostTrackValidation:

    def test_erreur_titre_manquant(self, client, auth_headers):
        resp = client.post(
            '/api/tracks/post',
            headers=_post_headers(auth_headers),
            data={
                'bpm': '120', 'key': 'C major', 'style': 'Trap',
                'price_mp3': '9.99', 'price_wav': '19.99',
                'file_mp3': _audio_file(),
            },
            content_type='multipart/form-data',
        )
        body = json.loads(resp.data)
        assert body['success'] is False

    def test_erreur_bpm_hors_plage(self, client, auth_headers):
        resp = client.post(
            '/api/tracks/post',
            headers=_post_headers(auth_headers),
            data={
                'title': 'Beat', 'bpm': '250',
                'key': 'C major', 'style': 'Trap',
                'price_mp3': '9.99', 'price_wav': '19.99',
                'file_mp3': _audio_file(),
            },
            content_type='multipart/form-data',
        )
        body = json.loads(resp.data)
        assert body['success'] is False

    def test_erreur_bpm_non_numerique(self, client, auth_headers):
        resp = client.post(
            '/api/tracks/post',
            headers=_post_headers(auth_headers),
            data={
                'title': 'Beat', 'bpm': 'rapide',
                'key': 'C', 'style': 'Trap',
                'price_mp3': '9.99', 'price_wav': '19.99',
                'file_mp3': _audio_file(),
            },
            content_type='multipart/form-data',
        )
        body = json.loads(resp.data)
        assert body['success'] is False

    def test_erreur_sans_fichier_audio(self, client, auth_headers):
        resp = client.post(
            '/api/tracks/post',
            headers=_post_headers(auth_headers),
            data={
                'title': 'Beat', 'bpm': '120',
                'key': 'C major', 'style': 'Trap',
                'price_mp3': '9.99', 'price_wav': '19.99',
                # Aucun fichier audio
            },
            content_type='multipart/form-data',
        )
        body = json.loads(resp.data)
        assert body['success'] is False

    def test_erreur_prix_hors_plage(self, client, auth_headers):
        resp = client.post(
            '/api/tracks/post',
            headers=_post_headers(auth_headers),
            data={
                'title': 'Beat', 'bpm': '120',
                'key': 'C major', 'style': 'Trap',
                'price_mp3': '0.10',  # < 0.50
                'price_wav': '19.99',
                'file_mp3': _audio_file(),
            },
            content_type='multipart/form-data',
        )
        body = json.loads(resp.data)
        assert body['success'] is False


# ── POST /api/tracks/post — upload valide ─────────────────────────────────────

@contextlib.contextmanager
def _upload_valide_ctx(tmp_path, *, unique_hash=None):
    """Context manager groupant tous les patches pour un POST d'upload valide.

    Patche : UPLOAD_FOLDER → tmp_path, validation audio OK, hash unique,
    Redis et RQ moqués. Yields (mock_redis, mock_queue).
    """
    if unique_hash is None:
        unique_hash = uuid.uuid4().hex

    mock_redis = MagicMock()
    mock_queue = MagicMock()

    with patch('config.UPLOAD_FOLDER', tmp_path), \
         patch('routes.tracks_api.VALIDATION_AVAILABLE', True), \
         patch('routes.tracks_api.validate_specific_audio_format', return_value=(True, None)), \
         patch('models.Track.compute_file_hash', return_value=unique_hash), \
         patch('models.Track.hash_exists', return_value=False), \
         patch('routes.tracks_api.redis_client', mock_redis), \
         patch('routes.tracks_api.Queue', return_value=mock_queue):
        yield mock_redis, mock_queue


class TestPostTrackValid:

    def test_upload_valide_retourne_job_id(self, client, user, auth_headers, tmp_path):
        with _upload_valide_ctx(tmp_path):
            resp = _post_track(client, auth_headers)
        body = json.loads(resp.data)
        assert body['success'] is True, body
        assert 'job_id' in body['data']
        assert body['data']['job_id']

    def test_upload_valide_enqueue_rq(self, client, user, auth_headers, tmp_path):
        with _upload_valide_ctx(tmp_path) as (_, mock_queue):
            _post_track(client, auth_headers)
        mock_queue.enqueue.assert_called_once()
        assert 'process_track_data' in str(mock_queue.enqueue.call_args)

    def test_upload_valide_initialise_statut_redis(
        self, client, user, auth_headers, tmp_path
    ):
        with _upload_valide_ctx(tmp_path) as (mock_redis, _):
            resp = _post_track(client, auth_headers)
        job_id = json.loads(resp.data)['data']['job_id']
        all_keys = [str(c) for c in mock_redis.hset.call_args_list]
        assert any(f'job:{job_id}' in k for k in all_keys)

    def test_upload_valide_retourne_title_dans_data(
        self, client, user, auth_headers, tmp_path
    ):
        with _upload_valide_ctx(tmp_path):
            resp = _post_track(client, auth_headers)
        assert json.loads(resp.data)['data']['title'] == 'Test Beat Upload'


# ── PUT /api/tracks/put/<id> — regenerate_preview ─────────────────────────────

@contextlib.contextmanager
def _put_valide_ctx(tmp_path):
    """Patches pour un PUT avec fichier audio : validation OK, pas de Redis."""
    mock_queue = MagicMock()
    with patch('config.UPLOAD_FOLDER', tmp_path), \
         patch('routes.tracks_api.VALIDATION_AVAILABLE', True), \
         patch('routes.tracks_api.validate_specific_audio_format', return_value=(True, None)), \
         patch('routes.tracks_api.Queue', return_value=mock_queue):
        yield mock_queue


class TestPutTrackRegeneratePreview:

    def _put_data(self, track, extra=None):
        return {
            'title': track.title,
            'bpm': str(track.bpm),
            'key': track.key,
            'style': track.style or 'Trap',
            'price_mp3': '9.99',
            'price_wav': '19.99',
            'file_mp3': _audio_file('replace.mp3'),
            **(extra or {}),
        }

    def test_regenerate_preview_enqueue_la_tache(
        self, client, user, auth_headers, track, tmp_path
    ):
        with _put_valide_ctx(tmp_path) as mock_queue:
            resp = client.put(
                f'/api/tracks/put/{track.id}',
                headers=_post_headers(auth_headers),
                data=self._put_data(track, extra={'regenerate_preview': '1'}),
                content_type='multipart/form-data',
            )
        body = json.loads(resp.data)
        assert body['success'] is True, body
        calls_str = [str(c) for c in mock_queue.enqueue.call_args_list]
        assert any('regenerate_preview' in s for s in calls_str)

    def test_sans_flag_regenerate_preview_pas_d_enqueue(
        self, client, user, auth_headers, track, tmp_path
    ):
        with _put_valide_ctx(tmp_path) as mock_queue:
            resp = client.put(
                f'/api/tracks/put/{track.id}',
                headers=_post_headers(auth_headers),
                data=self._put_data(track),
                content_type='multipart/form-data',
            )
        body = json.loads(resp.data)
        assert body['success'] is True, body
        calls_str = [str(c) for c in mock_queue.enqueue.call_args_list]
        assert not any('regenerate_preview' in s for s in calls_str)

    def test_proprietaire_uniquement_peut_modifier(
        self, client, db, track, bound_factories, app
    ):
        """Un autre utilisateur ne peut pas éditer le track."""
        from tests.factories.user_factory import UserFactory
        from flask_jwt_extended import create_access_token
        other = UserFactory()
        with app.app_context():
            token = create_access_token(identity=str(other.id))
        resp = client.put(
            f'/api/tracks/put/{track.id}',
            headers={'Authorization': f'Bearer {token}'},
            data={
                'title': 'Hack', 'bpm': '120', 'key': 'C', 'style': 'Trap',
                'price_mp3': '9.99', 'price_wav': '19.99',
            },
            content_type='multipart/form-data',
        )
        assert resp.status_code in (403, 404)
