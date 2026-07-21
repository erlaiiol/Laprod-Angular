"""
Tests d'intégration — cohérence des chemins de fichiers pour les previews
d'audition mixmaster (page publique /mixmaster/engineers).

Contexte (bug prod juillet 2026) : le lecteur audio de /mixmaster/engineers
recevait des URLs en 404. Deux causes distinctes, désormais couvertes ici
pour qu'une régression soit détectée par la suite plutôt qu'en prod :

1. app.py `serve_db_assets` (+ nginx.conf en miroir) n'autorisait que
   images/main/fonts → tout /db_assets/mixmaster/... était bloqué, y compris
   les previews publiques légitimes.
2. Les endpoints d'upload (auth_api.submit_mixmaster_sample,
   premium_api.update_mix_previews, admin_api.admin_upload_engineer_sample)
   enregistraient les fichiers sur disque à un endroit différent de celui
   encodé dans l'URL stockée en DB (dossiers 'mixmaster_samples' vs
   'mixmaster/samples', UPLOAD_FOLDER vs MIXMASTER_SAMPLES_FOLDER).

Stratégie : chaque test d'upload va bout en bout — il poste un fichier via
l'API, puis effectue un GET sur l'URL réellement retournée/stockée. Un test
qui vérifierait juste le code retour de l'upload n'aurait pas détecté ce bug :
c'est la cohérence upload → URL servie qui compte.
"""

import io
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.factories.user_factory import UserFactory


# ── Helpers ───────────────────────────────────────────────────────────────────

def _jwt_headers(app, user_id):
    """Headers JWT sans Content-Type imposé (nécessaire pour le multipart)."""
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {'Authorization': f'Bearer {token}'}


def _mp3(name):
    return (io.BytesIO(b'ID3\x03fake mp3 bytes'), name, 'audio/mpeg')


@pytest.fixture()
def isolated_mixmaster_samples_dir():
    """Redirige config.BASE_DIR et config.MIXMASTER_SAMPLES_FOLDER vers un
    répertoire temporaire : les tests n'écrivent jamais dans le vrai
    db_assets/ du dépôt, tout en gardant la route /db_assets/... utilisable
    de bout en bout (upload réel → fichier réel → GET réel)."""
    import config
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        samples_dir = tmp_path / 'db_assets' / 'mixmaster' / 'samples'
        samples_dir.mkdir(parents=True)
        with patch.object(config, 'BASE_DIR', tmp_path), \
             patch.object(config, 'MIXMASTER_SAMPLES_FOLDER', samples_dir):
            yield samples_dir


@pytest.fixture()
def _cleanup_users(db):
    created = []
    yield created
    for u in created:
        existing = db.session.get(type(u), u.id)
        if existing:
            db.session.delete(existing)
    db.session.commit()


# ── 1. Allowlist /db_assets/ : previews publiques vs. contenus privés ────────

class TestDbAssetsMixmasterAllowlist:
    """mixmaster/samples doit être public ; mixmaster/uploads et
    mixmaster/processed doivent rester bloqués (stems bruts client /
    livrables payants)."""

    def test_samples_are_publicly_servable(self, client, isolated_mixmaster_samples_dir):
        (isolated_mixmaster_samples_dir / 'preview.mp3').write_bytes(b'fake audio')
        resp = client.get('/db_assets/mixmaster/samples/preview.mp3')
        assert resp.status_code == 200

    def test_uploads_remain_blocked(self, client, isolated_mixmaster_samples_dir):
        uploads_dir = isolated_mixmaster_samples_dir.parent / 'uploads'
        uploads_dir.mkdir()
        (uploads_dir / 'stems.zip').write_bytes(b'fake zip')
        resp = client.get('/db_assets/mixmaster/uploads/stems.zip')
        assert resp.status_code == 404

    def test_processed_remain_blocked(self, client, isolated_mixmaster_samples_dir):
        processed_dir = isolated_mixmaster_samples_dir.parent / 'processed'
        processed_dir.mkdir()
        (processed_dir / 'final.mp3').write_bytes(b'fake audio')
        resp = client.get('/db_assets/mixmaster/processed/final.mp3')
        assert resp.status_code == 404

    def test_missing_sample_file_still_404s(self, client, isolated_mixmaster_samples_dir):
        """L'allowlist ne doit pas masquer un vrai fichier manquant."""
        resp = client.get('/db_assets/mixmaster/samples/does-not-exist.mp3')
        assert resp.status_code == 404


# ── 2. Upload initial (certification) — auth_api.submit_mixmaster_sample ────

class TestAuthApiSubmitMixmasterSample:
    def test_uploaded_sample_url_is_publicly_fetchable(
        self, client, db, app, bound_factories, isolated_mixmaster_samples_dir, _cleanup_users,
    ):
        user = UserFactory(is_mix_engineer=True)
        _cleanup_users.append(user)
        headers = _jwt_headers(app, user.id)

        resp = client.post(
            '/api/auth/submit-mixmaster-sample',
            data={
                'reference_price': '100',
                'price_min': '40',
                'bio': 'Ingénieur du son certifié, 10 ans d\'expérience.',
                'sample_raw': _mp3('raw.mp3'),
                'sample_processed': _mp3('proc.mp3'),
            },
            content_type='multipart/form-data',
            headers=headers,
        )
        assert resp.status_code == 200

        db.session.refresh(user)
        assert user.mixmaster_sample_raw
        assert user.mixmaster_sample_processed

        for stored_path in (user.mixmaster_sample_raw, user.mixmaster_sample_processed):
            fetch = client.get(f'/{stored_path}')
            assert fetch.status_code == 200, f'{stored_path} devrait être servable'


# ── 3. Mise à jour self-service Pro — premium_api.update_mix_previews ───────

class TestPremiumApiUpdateMixPreviews:
    def test_uploaded_sample_url_is_publicly_fetchable(
        self, client, db, app, bound_factories, isolated_mixmaster_samples_dir, _cleanup_users,
    ):
        user = UserFactory(
            is_mixmaster_engineer=True,
            subscription_plan='pro_structure',
            premium_expires_at=None,
        )
        _cleanup_users.append(user)
        headers = _jwt_headers(app, user.id)

        resp = client.post(
            '/api/premium/update-mix-previews',
            data={'sample_raw': _mp3('raw_update.mp3')},
            content_type='multipart/form-data',
            headers=headers,
        )
        assert resp.status_code == 200

        db.session.refresh(user)
        assert user.mixmaster_sample_raw

        fetch = client.get(f'/{user.mixmaster_sample_raw}')
        assert fetch.status_code == 200, f'{user.mixmaster_sample_raw} devrait être servable'


# ── 4. Upload admin (bypass validation) — admin_api.admin_upload_engineer_sample ─

class TestAdminApiUploadEngineerSample:
    def test_uploaded_sample_url_is_publicly_fetchable(
        self, client, db, app, bound_factories, isolated_mixmaster_samples_dir, _cleanup_users,
    ):
        admin = UserFactory(is_admin=True)
        engineer = UserFactory(is_mix_engineer=True)
        _cleanup_users += [admin, engineer]
        headers = _jwt_headers(app, admin.id)

        resp = client.post(
            f'/api/admin/engineers/{engineer.id}/upload-sample',
            data={'sample_raw': _mp3('admin_raw.mp3')},
            content_type='multipart/form-data',
            headers=headers,
        )
        assert resp.status_code == 200

        db.session.refresh(engineer)
        assert engineer.mixmaster_sample_raw
        # Même convention de chemin que les deux autres endpoints d'upload.
        assert engineer.mixmaster_sample_raw.startswith('db_assets/mixmaster/samples/')

        fetch = client.get(f'/{engineer.mixmaster_sample_raw}')
        assert fetch.status_code == 200, f'{engineer.mixmaster_sample_raw} devrait être servable'


# ── 5. Bout en bout via la page publique /mixmaster/engineers ───────────────

class TestPublicEngineersListingSampleUrls:
    def test_sample_url_from_listing_is_fetchable(
        self, client, db, bound_factories, isolated_mixmaster_samples_dir, _cleanup_users,
    ):
        engineer = UserFactory(
            is_mixmaster_engineer=True,
            mixmaster_reference_price=100,
            mixmaster_price_min=40,
        )
        _cleanup_users.append(engineer)

        fname = 'listing_preview.mp3'
        (isolated_mixmaster_samples_dir / fname).write_bytes(b'fake audio')
        engineer.mixmaster_sample_raw = f'db_assets/mixmaster/samples/{fname}'
        db.session.commit()

        resp = client.get('/api/mixmaster/engineers')
        assert resp.status_code == 200
        engineers = resp.get_json()['data']['engineers']
        entry = next(e for e in engineers if e['id'] == engineer.id)

        assert entry['sample_raw_url'] == f'/db_assets/mixmaster/samples/{fname}'
        fetch = client.get(entry['sample_raw_url'])
        assert fetch.status_code == 200
