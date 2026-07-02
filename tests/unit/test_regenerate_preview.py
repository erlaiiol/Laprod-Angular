"""
Tests unitaires — tasks.track_processing.regenerate_preview

Couvre :
  - apply_watermark_and_trim appelé quand WATERMARK_AVAILABLE=True
  - Pas de watermark si WATERMARK_AVAILABLE=False → shutil.copy direct
  - track.audio_file mis à jour en DB après succès
  - Ancien fichier preview supprimé si différent du nouveau
  - Fallback shutil.copy si le watermark échoue ou ne produit pas de fichier
  - Retour silencieux si le fallback copy échoue aussi
  - Retour silencieux si le track est introuvable en DB
"""
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(
    app,
    track_id: int,
    primary: Path,
    new_preview: Path,
    new_filename: str,
    *,
    watermark_available: bool = True,
    mock_watermark=None,
    mock_copy=None,
):
    """Lance regenerate_preview avec les dépendances patchées."""
    if mock_watermark is None:
        mock_watermark = MagicMock()
    if mock_copy is None:
        mock_copy = MagicMock()

    with patch('tasks.track_processing.create_app', return_value=app), \
         patch('tasks.track_processing.WATERMARK_AVAILABLE', watermark_available), \
         patch('tasks.track_processing.apply_watermark_and_trim', mock_watermark), \
         patch('shutil.copy', mock_copy):
        from tasks.track_processing import regenerate_preview
        regenerate_preview(track_id, str(primary), str(new_preview), new_filename)

    return mock_watermark, mock_copy


def _watermark_creates_file(new_preview: Path):
    """side_effect pour apply_watermark_and_trim : crée le fichier de sortie."""
    def _impl(**kwargs):
        Path(kwargs['output_path']).write_bytes(b'\x00' * 64)
    return _impl


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def preview_track(db, user):
    """Track avec audio_file='old_preview.mp3' en DB."""
    from models import Track
    t = Track(
        title='Preview Test',
        composer_id=user.id,
        file_hash=str(uuid.uuid4()),
        audio_file='old_preview.mp3',
        bpm=130,
        key='A minor',
        style='RnB',
        is_approved=True,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRegeneratePreviewWatermark:

    def test_appelle_watermark_avec_les_bons_chemins(self, app, preview_track, tmp_path):
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        mock_wm = MagicMock(side_effect=_watermark_creates_file(new_preview))
        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             mock_watermark=mock_wm)

        mock_wm.assert_called_once()
        call_kwargs = mock_wm.call_args.kwargs
        assert call_kwargs['input_path'] == str(primary)
        assert call_kwargs['output_path'] == str(new_preview)

    def test_pas_de_watermark_si_non_disponible(self, app, preview_track, tmp_path):
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        mock_wm = MagicMock()
        mock_copy = MagicMock(side_effect=lambda src, dst: Path(dst).write_bytes(b'\x00'))

        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             watermark_available=False, mock_watermark=mock_wm, mock_copy=mock_copy)

        mock_wm.assert_not_called()
        mock_copy.assert_called_once()


class TestRegeneratePreviewFallback:

    def test_fallback_copy_si_watermark_echoue(self, app, preview_track, tmp_path):
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        mock_wm = MagicMock(side_effect=Exception('codec manquant'))
        mock_copy = MagicMock(side_effect=lambda src, dst: Path(dst).write_bytes(b'\x00'))

        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             mock_watermark=mock_wm, mock_copy=mock_copy)

        mock_copy.assert_called_once_with(str(primary), str(new_preview))

    def test_fallback_copy_si_watermark_ne_produit_pas_de_fichier(
        self, app, preview_track, tmp_path
    ):
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        # Watermark ne crée pas le fichier de sortie
        mock_wm = MagicMock()  # ne crée pas new_preview
        mock_copy = MagicMock(side_effect=lambda src, dst: Path(dst).write_bytes(b'\x00'))

        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             mock_watermark=mock_wm, mock_copy=mock_copy)

        # shutil.copy appelé car le fichier de sortie est absent
        mock_copy.assert_called_once_with(str(primary), str(new_preview))

    def test_retour_silencieux_si_fallback_copy_echoue(self, app, preview_track, tmp_path):
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        mock_wm = MagicMock(side_effect=Exception('watermark failed'))
        mock_copy = MagicMock(side_effect=Exception('disque plein'))

        # Ne doit pas propager l'exception
        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             mock_watermark=mock_wm, mock_copy=mock_copy)


class TestRegeneratePreviewDB:

    def test_met_a_jour_audio_file_en_db(self, app, db, preview_track, tmp_path):
        from models import Track
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             mock_watermark=MagicMock(side_effect=_watermark_creates_file(new_preview)))

        db.session.expire(preview_track)
        reloaded = db.session.get(Track, preview_track.id)
        assert reloaded.audio_file == 'new_preview.mp3'

    def test_retour_silencieux_si_track_introuvable(self, app, tmp_path):
        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        # track_id=99999 → introuvable → pas d'exception
        _run(app, 99999, primary, new_preview, 'new_preview.mp3',
             mock_watermark=MagicMock(side_effect=_watermark_creates_file(new_preview)))


class TestRegeneratePreviewCleanup:

    def test_supprime_ancien_preview_apres_succes(
        self, app, preview_track, tmp_path, monkeypatch
    ):
        import config as _cfg
        monkeypatch.setattr(_cfg, 'UPLOAD_FOLDER', tmp_path)

        # Crée l'ancien fichier preview
        old_file = tmp_path / 'old_preview.mp3'
        old_file.write_bytes(b'\x00' * 64)

        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / 'new_preview.mp3'

        _run(app, preview_track.id, primary, new_preview, 'new_preview.mp3',
             mock_watermark=MagicMock(side_effect=_watermark_creates_file(new_preview)))

        assert not old_file.exists(), "L'ancien preview doit être supprimé"

    def test_ne_supprime_pas_si_meme_nom(
        self, app, db, preview_track, tmp_path, monkeypatch
    ):
        """Quand le nouveau preview a le même nom que l'ancien, pas de suppression."""
        import config as _cfg
        monkeypatch.setattr(_cfg, 'UPLOAD_FOLDER', tmp_path)

        same_name = 'old_preview.mp3'
        existing_file = tmp_path / same_name
        existing_file.write_bytes(b'\x00' * 64)

        primary = tmp_path / 'primary.mp3'
        primary.write_bytes(b'\xff\xfb' + b'\x00' * 512)
        new_preview = tmp_path / same_name

        mock_wm = MagicMock(side_effect=_watermark_creates_file(new_preview))
        _run(app, preview_track.id, primary, new_preview, same_name,
             mock_watermark=mock_wm)

        # Le fichier doit exister (pas supprimé car même nom)
        assert new_preview.exists()
