"""
Tests d'intégration — POST /api/tracks/post (upload beat)

Couvre :
  - Authentification & permissions (JWT, tokens)
  - Validation des champs obligatoires (titre, BPM, prix, SACEM)
  - Validation des fichiers (MP3, WAV, stems — MIME + taille)
  - Modes d'upload (MP3 seul, WAV seul, MP3+WAV, stems seuls, MP3+stems)
  - Détection des doublons (file_hash)
  - Payload RQ transmis au worker (champs, chemins)
  - Redis initialisé (status=queued, TTL)
  - Gate premium (exclusive license uniquement — les stems sont accessibles à tous)

Stratégie de mocking :
  - config.UPLOAD_FOLDER → tmp_path pytest
  - validate_specific_audio_format / validate_stems_archive → mockés (True, "ok")
  - Track.compute_file_hash / Track.hash_exists → mockés
  - redis_client et Queue → MagicMock
  - Validation des images → mockée
"""
import io
import uuid
import zipfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free  # noqa: F401


# ── Fichiers de test ──────────────────────────────────────────────────────────

def _mp3():
    """Fichier MP3 fictif (header reconnaissable + 2KB)."""
    return (io.BytesIO(b'\xff\xfb\x90\x00' + b'\x00' * 2048), 'beat.mp3', 'audio/mpeg')


def _wav():
    """Fichier WAV fictif (2KB)."""
    return (io.BytesIO(b'RIFF$\x00\x00\x00WAVEfmt ' + b'\x00' * 2048), 'beat.wav', 'audio/wav')


def _stems_zip(files=None):
    """Archive ZIP simulant un export FL Studio."""
    buf = io.BytesIO()
    entries = files or {'Beat_current.wav': b'RIFF' + b'\x00'*100, 'Beat_kick.wav': b'\x00'*50}
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    buf.seek(0)
    return (buf, 'stems.zip', 'application/zip')


def _valid_form(*, title='My Beat', bpm='120', key='C major', style='Trap',
                price_mp3='9.99', price_wav='19.99', price_stems='49.99',
                sacem='50', **extra):
    """FormData valide de base (sans fichiers)."""
    return {
        'title':                    title,
        'bpm':                      bpm,
        'key':                      key,
        'style':                    style,
        'price_mp3':                price_mp3,
        'price_wav':                price_wav,
        'price_stems':              price_stems,
        'sacem_percentage_composer': sacem,
        **extra,
    }


# ── Helper d'upload mocké ─────────────────────────────────────────────────────

def _upload(client, headers, tmp_dir, data, *,
            validation_result=(True, 'ok'),
            stems_result=(True, 'ok'),
            hash_value=None,
            hash_exists=False):
    """POST /api/tracks/post avec toutes les dépendances mockées."""
    import config
    mock_redis = MagicMock()
    mock_queue_inst = MagicMock()
    hash_value = hash_value or uuid.uuid4().hex

    with patch.object(config, 'UPLOAD_FOLDER', tmp_dir), \
         patch.object(config, 'IMAGES_FOLDER', tmp_dir), \
         patch('routes.tracks_api.validate_specific_audio_format',
               return_value=validation_result), \
         patch('routes.tracks_api.validate_stems_archive',
               return_value=stems_result), \
         patch('routes.tracks_api.validate_image_file', return_value=(True, 'ok')), \
         patch('routes.tracks_api.Track.compute_file_hash', return_value=hash_value), \
         patch('routes.tracks_api.Track.hash_exists', return_value=hash_exists), \
         patch('routes.tracks_api.redis_client', mock_redis), \
         patch('routes.tracks_api.Queue', MagicMock(return_value=mock_queue_inst)):
        resp = client.post(
            '/api/tracks/post',
            data=data,
            content_type='multipart/form-data',
            headers=headers,
        )
    return resp, mock_redis, mock_queue_inst


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture()
def beatmaker_headers(app, user):
    """JWT du beatmaker standard (conftest user — pro, beatmaker, tokens disponibles)."""
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    return {'Authorization': f'Bearer {token}'}


@pytest.fixture()
def free_headers(app, user_free):
    """JWT du beatmaker free (tokens limités, is_premium=False)."""
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user_free.id))
    return {'Authorization': f'Bearer {token}'}


# ── Authentification ──────────────────────────────────────────────────────────

class TestUploadAuthentication:

    def test_no_jwt_returns_401(self, client):
        resp = client.post('/api/tracks/post', data={}, content_type='multipart/form-data')
        assert resp.status_code == 401

    def test_invalid_jwt_returns_4xx(self, client):
        """Token JWT malformé → 401 (signature invalide) ou 422 (token non parseable)."""
        resp = client.post(
            '/api/tracks/post',
            data={},
            content_type='multipart/form-data',
            headers={'Authorization': 'Bearer invalid_token_xyz'},
        )
        assert resp.status_code in (401, 422)

    def test_user_without_tokens_returns_403(self, client, db, beatmaker_headers, user):
        """Un beatmaker sans tokens upload reçoit 403."""
        user.upload_track_tokens = 0
        db.session.commit()
        resp = client.post(
            '/api/tracks/post',
            data={},
            content_type='multipart/form-data',
            headers=beatmaker_headers,
        )
        user.upload_track_tokens = 5  # restaurer
        db.session.commit()
        assert resp.status_code == 403


# ── Validation des champs ─────────────────────────────────────────────────────

class TestUploadFieldValidation:

    def test_missing_title_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(title=''), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_missing_bpm_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(bpm=''), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_bpm_below_range_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(bpm='30'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_bpm_above_range_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(bpm='250'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_bpm_not_integer_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(bpm='not_a_number'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_price_below_minimum_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(price_mp3='0.10'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_price_above_maximum_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(price_mp3='1500.00'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_sacem_above_85_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(sacem='90'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_sacem_negative_returns_400(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(sacem='-10'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_no_audio_file_returns_400(self, client, tmp_path, beatmaker_headers):
        """Aucun fichier audio fourni → 400."""
        data = _valid_form()
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 400

    def test_error_message_in_response(self, client, tmp_path, beatmaker_headers):
        """La réponse d'erreur contient un message lisible."""
        data = {**_valid_form(title=''), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        body = resp.get_json()
        assert 'message' in body or 'feedback' in body


# ── Validation des fichiers ───────────────────────────────────────────────────

class TestUploadFileValidation:

    def test_invalid_mp3_returns_400(self, client, tmp_path, beatmaker_headers):
        """validate_specific_audio_format retourne False → 400."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             validation_result=(False, 'Fichier MP3 trop petit'))
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'MP3' in str(body) or 'mp3' in str(body).lower()

    def test_invalid_wav_returns_400(self, client, tmp_path, beatmaker_headers):
        """validate_specific_audio_format sur le WAV retourne False → 400."""
        data = {**_valid_form(), 'file_wav': _wav()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             validation_result=(False, 'WAV invalide'))
        assert resp.status_code == 400

    def test_invalid_stems_returns_400(self, client, tmp_path, beatmaker_headers):
        """validate_stems_archive retourne False → 400 avec message."""
        data = {**_valid_form(), 'file_stems': _stems_zip()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             stems_result=(False, 'Archive corrompue'))
        assert resp.status_code == 400
        body = resp.get_json()
        assert 'stems' in str(body).lower() or 'archive' in str(body).lower()

    def test_stems_without_current_master_returns_400(self, client, tmp_path, beatmaker_headers):
        """Stems seuls sans _current.* ni _master.* → 400 (require_primary=True)."""
        data = {**_valid_form(), 'file_stems': _stems_zip({'kick.wav': b'\x00'*100})}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             stems_result=(False, "_current.* absent"))
        assert resp.status_code == 400


# ── Modes d'upload valides ────────────────────────────────────────────────────

class TestUploadHappyPaths:

    def test_mp3_only_returns_202_with_job_id(self, client, tmp_path, beatmaker_headers):
        """Mode MP3 seul → 202 avec job_id UUID."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 202
        job_id = resp.get_json()['data']['job_id']
        uuid.UUID(job_id)  # lève ValueError si non-UUID

    def test_wav_only_returns_202_with_job_id(self, client, tmp_path, beatmaker_headers):
        """Mode WAV seul → 202 avec job_id."""
        data = {**_valid_form(), 'file_wav': _wav()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 202
        uuid.UUID(resp.get_json()['data']['job_id'])

    def test_mp3_and_wav_returns_202(self, client, tmp_path, beatmaker_headers):
        """MP3 + WAV → 202."""
        data = {**_valid_form(), 'file_mp3': _mp3(), 'file_wav': _wav()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 202

    def test_stems_only_returns_202(self, client, tmp_path, beatmaker_headers):
        """Stems seuls (tout utilisateur) → 202."""
        data = {**_valid_form(), 'file_stems': _stems_zip()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 202

    def test_mp3_with_stems_returns_202(self, client, tmp_path, beatmaker_headers):
        """MP3 + stems (mode mixte) → 202."""
        data = {**_valid_form(), 'file_mp3': _mp3(), 'file_stems': _stems_zip()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.status_code == 202

    def test_response_contains_title(self, client, tmp_path, beatmaker_headers):
        """La réponse 202 contient le titre du beat."""
        data = {**_valid_form(title='Super Beat'), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data)
        assert resp.get_json()['data']['title'] == 'Super Beat'

    def test_mp3_file_saved_to_upload_folder(self, client, tmp_path, beatmaker_headers):
        """Le fichier MP3 est physiquement sauvé dans UPLOAD_FOLDER."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _upload(client, beatmaker_headers, tmp_path, data)
        saved = list(tmp_path.glob('*_full.mp3'))
        assert len(saved) == 1

    def test_wav_file_saved_to_upload_folder(self, client, tmp_path, beatmaker_headers):
        """Le fichier WAV est physiquement sauvé dans UPLOAD_FOLDER."""
        data = {**_valid_form(), 'file_wav': _wav()}
        _upload(client, beatmaker_headers, tmp_path, data)
        saved = list(tmp_path.glob('*_full.wav'))
        assert len(saved) == 1

    def test_stems_file_saved_to_upload_folder(self, client, tmp_path, beatmaker_headers):
        """L'archive stems est physiquement sauvée dans UPLOAD_FOLDER."""
        data = {**_valid_form(), 'file_stems': _stems_zip()}
        _upload(client, beatmaker_headers, tmp_path, data)
        saved = list(tmp_path.glob('*_stems.zip'))
        assert len(saved) == 1


# ── Détection des doublons ────────────────────────────────────────────────────

class TestUploadDuplicateDetection:

    def test_duplicate_mp3_hash_returns_409(self, client, tmp_path, beatmaker_headers):
        """Même hash que un beat existant → 409 Conflict."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             hash_exists=True)
        assert resp.status_code == 409

    def test_duplicate_wav_hash_returns_409(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(), 'file_wav': _wav()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             hash_exists=True)
        assert resp.status_code == 409

    def test_unique_hash_proceeds_normally(self, client, tmp_path, beatmaker_headers):
        data = {**_valid_form(), 'file_mp3': _mp3()}
        resp, _, _ = _upload(client, beatmaker_headers, tmp_path, data,
                             hash_exists=False)
        assert resp.status_code == 202


# ── Redis & RQ ────────────────────────────────────────────────────────────────

class TestUploadRedisBehavior:

    def test_redis_status_initialized_to_queued(self, client, tmp_path, beatmaker_headers):
        """Le statut initial Redis est 'queued'."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _, mock_redis, _ = _upload(client, beatmaker_headers, tmp_path, data)
        first_hset = mock_redis.hset.call_args_list[0]
        mapping = first_hset.kwargs.get('mapping') or first_hset.args[1]
        assert mapping['status'] == 'queued'

    def test_redis_ttl_set(self, client, tmp_path, beatmaker_headers):
        """Le TTL Redis est défini sur la clé job."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _, mock_redis, _ = _upload(client, beatmaker_headers, tmp_path, data)
        mock_redis.expire.assert_called_once()
        ttl = mock_redis.expire.call_args.args[1]
        assert ttl == 7200

    def test_rq_task_path_correct(self, client, tmp_path, beatmaker_headers):
        """Le job RQ pointe vers tasks.track_processing.process_track_data."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data)
        mock_queue.enqueue.assert_called()
        task_path = mock_queue.enqueue.call_args.args[0]
        assert task_path == 'tasks.track_processing.process_track_data'

    def test_rq_payload_contains_all_required_fields(self, client, tmp_path, beatmaker_headers, user):
        """Le payload RQ contient les champs métier essentiels."""
        data = {**_valid_form(title='Test Track', bpm='140'), 'file_mp3': _mp3()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data)
        payload = mock_queue.enqueue.call_args.args[1]

        assert payload['user_id']   == user.id
        assert payload['title']     == 'Test Track'
        assert payload['bpm']       == 140
        assert payload['price_mp3'] == 9.99
        for field in ('job_id', 'safe_title', 'unique_id', 'file_hash',
                      'preview_disk_path', 'preview_filename', 'tag_ids'):
            assert field in payload, f"Champ manquant dans job_payload: {field}"

    def test_rq_payload_mp3_path_set(self, client, tmp_path, beatmaker_headers):
        """mp3_disk_path est défini dans le payload quand un MP3 est uploadé."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data)
        payload = mock_queue.enqueue.call_args.args[1]
        assert payload['mp3_disk_path'] is not None
        assert payload['mp3_filename'] is not None

    def test_rq_payload_wav_path_set(self, client, tmp_path, beatmaker_headers):
        """wav_disk_path est défini dans le payload quand un WAV est uploadé."""
        data = {**_valid_form(), 'file_wav': _wav()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data)
        payload = mock_queue.enqueue.call_args.args[1]
        assert payload['wav_disk_path'] is not None

    def test_rq_payload_stems_path_set(self, client, tmp_path, beatmaker_headers):
        """stems_disk_path est défini dans le payload quand stems est uploadé."""
        data = {**_valid_form(), 'file_stems': _stems_zip()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data)
        payload = mock_queue.enqueue.call_args.args[1]
        assert payload['stems_disk_path'] is not None
        assert payload['stems_filename'] is not None

    def test_rq_not_enqueued_when_validation_fails(self, client, tmp_path, beatmaker_headers):
        """En cas d'erreur de validation, le job n'est PAS enqueued."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data,
                                   validation_result=(False, 'Fichier invalide'))
        mock_queue.enqueue.assert_not_called()


# ── Gate premium ──────────────────────────────────────────────────────────────

class TestUploadPremiumGate:

    def test_exclusive_license_requires_premium(self, client, tmp_path, free_headers):
        """contract_price_exclusive sans abonnement premium → 403."""
        data = {
            **_valid_form(),
            'file_mp3': _mp3(),
            'contract_price_exclusive': '500',
        }
        import config
        mock_redis = MagicMock()
        mock_queue = MagicMock()
        with patch.object(config, 'UPLOAD_FOLDER', tmp_path), \
             patch.object(config, 'IMAGES_FOLDER', tmp_path), \
             patch('routes.tracks_api.redis_client', mock_redis), \
             patch('routes.tracks_api.Queue', MagicMock(return_value=mock_queue)):
            resp = client.post(
                '/api/tracks/post',
                data=data,
                content_type='multipart/form-data',
                headers=free_headers,
            )
        assert resp.status_code == 403

    def test_free_user_can_upload_stems(self, client, tmp_path, free_headers):
        """Un utilisateur free peut uploader des stems (la restriction premium a été levée)."""
        data = {**_valid_form(), 'file_mp3': _mp3(), 'file_stems': _stems_zip()}
        resp, _, mock_queue = _upload(client, free_headers, tmp_path, data)
        assert resp.status_code == 202
        payload = mock_queue.enqueue.call_args.args[1]
        assert payload['stems_disk_path'] is not None


# ── Nommage des fichiers ───────────────────────────────────────────────────────

class TestUploadFileNaming:

    def test_saved_mp3_contains_safe_title(self, client, tmp_path, beatmaker_headers):
        """Le nom de fichier MP3 sauvé sur disque contient le titre sécurisé."""
        data = {**_valid_form(title='My Super Beat'), 'file_mp3': _mp3()}
        _upload(client, beatmaker_headers, tmp_path, data)
        saved = list(tmp_path.glob('*_full.mp3'))
        assert len(saved) == 1
        assert 'MySuperBeat' in saved[0].name or 'My' in saved[0].name

    def test_preview_filename_in_payload(self, client, tmp_path, beatmaker_headers):
        """Le payload contient preview_filename et preview_disk_path cohérents."""
        data = {**_valid_form(), 'file_mp3': _mp3()}
        _, _, mock_queue = _upload(client, beatmaker_headers, tmp_path, data)
        payload = mock_queue.enqueue.call_args.args[1]
        assert payload['preview_filename'].endswith('.mp3')
        assert payload['preview_disk_path'].endswith(payload['preview_filename'])


# ── Performance ───────────────────────────────────────────────────────────────

class TestUploadPerformance:

    def test_upload_responds_under_500ms(self, client, tmp_path, beatmaker_headers):
        """L'upload (avec fichier + Redis + enqueue mockés) répond en < 500ms."""
        import time
        data = {**_valid_form(), 'file_mp3': _mp3()}
        start = time.perf_counter()
        _upload(client, beatmaker_headers, tmp_path, data)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 500, f"Upload trop lent : {elapsed_ms:.0f}ms (budget : 500ms)"
