"""
Tests unitaires — utils/file_validator.py

Couvre :
  FileValidator.validate_filename     — sécurité des noms de fichier
  validate_specific_audio_format      — MP3 / WAV + MIME réel + taille min
  validate_stems_archive              — ZIP/RAR de stems + require_primary
  validate_audio_duration_match       — cohérence durée MP3 vs WAV

Stratégie :
  - Les appels python-magic sont mockés pour isoler la logique de validation
    et éviter de dépendre d'un vrai décodeur binaire dans la CI.
  - Les ZIPs sont créés en mémoire / tmp avec la stdlib `zipfile`.
  - Les tailles minimales (MIN_MP3_SIZE, MIN_STEMS_SIZE) sont patchées
    à 0 pour que les petits fichiers de test passent les barrières de taille.
"""
import io
import os
import zipfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from werkzeug.datastructures import FileStorage


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fs(content: bytes, filename: str, content_type: str = 'application/octet-stream') -> FileStorage:
    """Crée un FileStorage werkzeug à partir de bytes bruts."""
    return FileStorage(
        stream=io.BytesIO(content),
        filename=filename,
        content_type=content_type,
    )


def _zip_bytes(files: dict) -> bytes:
    """Génère un ZIP en mémoire.  files = {'nom': b'contenu', ...}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_STORED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


MP3_HEADER = b'\xff\xfb\x90\x00' + b'\x00' * 100
WAV_HEADER = b'RIFF$\x00\x00\x00WAVEfmt ' + b'\x00' * 100


# ── FileValidator.validate_filename ───────────────────────────────────────────

class TestValidateFilename:

    def test_valid_alphanumeric(self):
        from utils.file_validator import FileValidator
        assert FileValidator.validate_filename('MyBeat01') == 'MyBeat01'

    def test_valid_with_dash_underscore(self):
        from utils.file_validator import FileValidator
        assert FileValidator.validate_filename('my-beat_v2') == 'my-beat_v2'

    def test_empty_raises(self):
        from utils.file_validator import FileValidator
        with pytest.raises(ValueError):
            FileValidator.validate_filename('')

    def test_too_short_raises(self):
        from utils.file_validator import FileValidator
        with pytest.raises(ValueError):
            FileValidator.validate_filename('a')

    def test_too_long_raises(self):
        from utils.file_validator import FileValidator
        with pytest.raises(ValueError):
            FileValidator.validate_filename('a' * 101)

    def test_dot_in_name_raises(self):
        from utils.file_validator import FileValidator
        with pytest.raises(ValueError):
            FileValidator.validate_filename('my.beat')

    def test_space_in_name_raises(self):
        from utils.file_validator import FileValidator
        with pytest.raises(ValueError):
            FileValidator.validate_filename('my beat')

    def test_path_traversal_raises(self):
        from utils.file_validator import FileValidator
        with pytest.raises(ValueError):
            FileValidator.validate_filename('../etc')

    def test_max_length_boundary_valid(self):
        from utils.file_validator import FileValidator
        name = 'a' * 100
        assert FileValidator.validate_filename(name) == name

    def test_min_length_boundary_valid(self):
        from utils.file_validator import FileValidator
        assert FileValidator.validate_filename('ab') == 'ab'


# ── validate_specific_audio_format ────────────────────────────────────────────

class TestValidateSpecificAudioFormat:

    def test_mp3_valid_passes(self):
        """Un MP3 avec MIME correct et taille suffisante est valide."""
        from utils.file_validator import validate_specific_audio_format, FileValidator
        file = _fs(MP3_HEADER, 'beat.mp3', 'audio/mpeg')
        with patch('utils.file_validator.magic.from_buffer', return_value='audio/mpeg'), \
             patch.object(FileValidator, 'MIN_MP3_SIZE', 0):
            valid, msg = validate_specific_audio_format(file, 'mp3')
        assert valid is True

    def test_wav_valid_passes(self):
        """Un WAV avec MIME correct est valide."""
        from utils.file_validator import validate_specific_audio_format, FileValidator
        file = _fs(WAV_HEADER, 'beat.wav', 'audio/wav')
        with patch('utils.file_validator.magic.from_buffer', return_value='audio/wav'), \
             patch.object(FileValidator, 'MIN_WAV_SIZE', 0):
            valid, msg = validate_specific_audio_format(file, 'wav')
        assert valid is True

    def test_mp3_wrong_mime_rejected(self):
        """Un fichier avec MIME audio/wav mais extension .mp3 est refusé."""
        from utils.file_validator import validate_specific_audio_format, FileValidator
        file = _fs(WAV_HEADER, 'beat.mp3', 'audio/wav')
        with patch('utils.file_validator.magic.from_buffer', return_value='audio/wav'), \
             patch.object(FileValidator, 'MIN_MP3_SIZE', 0):
            valid, msg = validate_specific_audio_format(file, 'mp3')
        assert valid is False
        assert 'mp3' in msg.lower() or 'mpeg' in msg.lower() or 'mp3' in msg.lower()

    def test_wav_wrong_mime_rejected(self):
        """Un fichier MP3 passé comme WAV est refusé."""
        from utils.file_validator import validate_specific_audio_format, FileValidator
        file = _fs(MP3_HEADER, 'beat.wav', 'audio/mpeg')
        with patch('utils.file_validator.magic.from_buffer', return_value='audio/mpeg'), \
             patch.object(FileValidator, 'MIN_WAV_SIZE', 0):
            valid, msg = validate_specific_audio_format(file, 'wav')
        assert valid is False

    def test_empty_file_rejected(self):
        """Un fichier vide est refusé avant la détection MIME."""
        from utils.file_validator import validate_specific_audio_format
        file = _fs(b'', 'beat.mp3')
        valid, msg = validate_specific_audio_format(file, 'mp3')
        assert valid is False
        assert 'vide' in msg.lower() or 'empty' in msg.lower()

    def test_mp3_below_min_size_rejected(self):
        """MP3 trop petit (< MIN_MP3_SIZE) → refusé."""
        import config
        from utils.file_validator import validate_specific_audio_format, FileValidator
        small_content = b'\xff\xfb\x90\x00' + b'\x00' * 10
        file = _fs(small_content, 'tiny.mp3')
        with patch('utils.file_validator.magic.from_buffer', return_value='audio/mpeg'):
            valid, msg = validate_specific_audio_format(file, 'mp3')
        assert valid is False
        assert 'trop petit' in msg or 'petit' in msg

    def test_unsupported_format_raises_friendly_error(self):
        """Un format non supporté ('flac' en tant que format attendu) retourne False."""
        from utils.file_validator import validate_specific_audio_format
        file = _fs(b'\x00' * 100, 'beat.xyz')
        valid, msg = validate_specific_audio_format(file, 'xyz')
        assert valid is False

    def test_no_filename_rejected(self):
        """FileStorage sans filename → refusé."""
        from utils.file_validator import validate_specific_audio_format
        file = FileStorage(stream=io.BytesIO(MP3_HEADER), filename='')
        valid, msg = validate_specific_audio_format(file, 'mp3')
        assert valid is False


# ── validate_stems_archive ────────────────────────────────────────────────────

class TestValidateStemsArchive:

    def _valid_zip_fs(self, files: dict | None = None) -> FileStorage:
        """ZIP FileStorage avec des fichiers WAV fictifs."""
        default = {'Beat_kick.wav': WAV_HEADER, 'Beat_snare.wav': WAV_HEADER}
        content = _zip_bytes(files or default)
        return _fs(content, 'stems.zip', 'application/zip')

    def test_valid_zip_with_wav_files_accepted(self):
        """Un ZIP valide avec fichiers .wav est accepté."""
        from utils.file_validator import validate_stems_archive, FileValidator
        file = self._valid_zip_fs()
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is True
        assert 'valide' in msg.lower()

    def test_require_primary_true_with_current_accepted(self):
        """require_primary=True + _current.wav présent → valide."""
        from utils.file_validator import validate_stems_archive, FileValidator
        file = self._valid_zip_fs({
            'Beat_current.wav': WAV_HEADER,
            'Beat_kick.wav':    WAV_HEADER,
        })
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file, require_primary=True)
        assert valid is True

    def test_require_primary_true_with_master_accepted(self):
        """require_primary=True + _master.wav (sans _current) → valide."""
        from utils.file_validator import validate_stems_archive, FileValidator
        file = self._valid_zip_fs({
            'Beat_master.wav': WAV_HEADER,
            'Beat_kick.wav':   WAV_HEADER,
        })
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file, require_primary=True)
        assert valid is True

    def test_require_primary_true_without_current_or_master_rejected(self):
        """require_primary=True sans _current.* ni _master.* → refusé avec message FL Studio."""
        from utils.file_validator import validate_stems_archive, FileValidator
        file = self._valid_zip_fs({
            'kick.wav':  WAV_HEADER,
            'snare.wav': WAV_HEADER,
        })
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file, require_primary=True)
        assert valid is False
        assert '_current' in msg or 'current' in msg.lower()
        assert 'FL Studio' in msg or 'fl studio' in msg.lower()

    def test_error_message_mentions_master_as_fallback(self):
        """Le message d'erreur require_primary cite *_master.* comme alternative."""
        from utils.file_validator import validate_stems_archive, FileValidator
        file = self._valid_zip_fs({'kick.wav': WAV_HEADER})
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            _, msg = validate_stems_archive(file, require_primary=True)
        assert '_master' in msg

    def test_empty_zip_rejected(self):
        """ZIP vide → refusé."""
        from utils.file_validator import validate_stems_archive, FileValidator
        content = _zip_bytes({})
        file = _fs(content, 'stems.zip', 'application/zip')
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is False
        assert 'vide' in msg.lower() or 'empty' in msg.lower()

    def test_zip_with_no_audio_files_rejected(self):
        """ZIP ne contenant que des fichiers non-audio → refusé."""
        from utils.file_validator import validate_stems_archive, FileValidator
        content = _zip_bytes({'project.fls': b'\x00'*100, 'notes.txt': b'hello'})
        file = _fs(content, 'stems.zip', 'application/zip')
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is False
        assert 'audio' in msg.lower() or 'wav' in msg.lower()

    def test_archive_below_min_size_rejected(self):
        """Archive trop petite (< MIN_STEMS_SIZE) → refusée avant d'ouvrir l'archive."""
        from utils.file_validator import validate_stems_archive, FileValidator
        content = _zip_bytes({'Beat_kick.wav': WAV_HEADER})
        file = _fs(content, 'stems.zip', 'application/zip')
        # MIN_STEMS_SIZE restera à sa vraie valeur (5 MB), le petit ZIP sera rejeté
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'):
            valid, msg = validate_stems_archive(file)
        assert valid is False
        assert 'mb' in msg.lower() or 'mo' in msg.lower() or 'taille' in msg.lower() or 'petite' in msg.lower()

    def test_corrupt_zip_rejected_gracefully(self):
        """Bytes aléatoires détectés comme zip mais corrompus → refusé sans crash."""
        from utils.file_validator import validate_stems_archive, FileValidator
        file = _fs(b'PK\x03\x04' + b'\xff' * 200, 'stems.zip', 'application/zip')
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is False

    def test_non_archive_mime_rejected(self):
        """Fichier audio passé comme archive → refusé par validate_archive d'abord."""
        from utils.file_validator import validate_stems_archive
        file = _fs(MP3_HEADER, 'beat.zip', 'audio/mpeg')
        with patch('utils.file_validator.magic.from_buffer', return_value='audio/mpeg'):
            valid, msg = validate_stems_archive(file)
        assert valid is False

    def test_no_file_provided_rejected(self):
        """Appel sans fichier → refusé immédiatement."""
        from utils.file_validator import validate_stems_archive
        file = FileStorage(stream=io.BytesIO(b''), filename='')
        valid, msg = validate_stems_archive(file)
        assert valid is False

    def test_mp3_stems_accepted_as_audio(self):
        """Les stems en .mp3 à l'intérieur du ZIP sont comptés comme audio."""
        from utils.file_validator import validate_stems_archive, FileValidator
        content = _zip_bytes({'beat_kick.mp3': MP3_HEADER, 'beat_snare.mp3': MP3_HEADER})
        file = _fs(content, 'stems.zip', 'application/zip')
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is True

    def test_flac_stems_accepted_as_audio(self):
        """Les stems en .flac à l'intérieur du ZIP sont comptés comme audio."""
        from utils.file_validator import validate_stems_archive, FileValidator
        content = _zip_bytes({'beat.flac': b'fLaC' + b'\x00'*100})
        file = _fs(content, 'stems.zip', 'application/zip')
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is True

    def test_audio_count_in_success_message(self):
        """Le message de succès indique le nombre de fichiers audio."""
        from utils.file_validator import validate_stems_archive, FileValidator
        content = _zip_bytes({
            'kick.wav': WAV_HEADER,
            'snare.wav': WAV_HEADER,
            'hat.wav': WAV_HEADER,
        })
        file = _fs(content, 'stems.zip', 'application/zip')
        with patch('utils.file_validator.magic.from_buffer', return_value='application/zip'), \
             patch.object(FileValidator, 'MIN_STEMS_SIZE', 0):
            valid, msg = validate_stems_archive(file)
        assert valid is True
        assert '3' in msg


# ── validate_audio_duration_match ─────────────────────────────────────────────

class TestValidateAudioDurationMatch:

    def _make_wav_file(self, duration_sec: float, sr: int = 22050) -> FileStorage:
        """Crée un vrai fichier WAV de durée précise via soundfile."""
        import numpy as np
        import soundfile as sf
        n = int(sr * duration_sec)
        y = (0.1 * np.sin(2 * np.pi * 440 * np.arange(n) / sr)).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, y, sr, format='WAV', subtype='PCM_16')
        buf.seek(0)
        return FileStorage(stream=buf, filename='beat.wav')

    def _make_mp3_file(self, wav_fs: FileStorage) -> FileStorage:
        """Convertit un WAV FileStorage en MP3 (via pydub)."""
        from pydub import AudioSegment
        wav_fs.stream.seek(0)
        seg = AudioSegment.from_wav(wav_fs.stream)
        mp3_buf = io.BytesIO()
        seg.export(mp3_buf, format='mp3')
        mp3_buf.seek(0)
        return FileStorage(stream=mp3_buf, filename='beat.mp3')

    def test_same_duration_accepted(self, tmp_path):
        """MP3 et WAV de même durée (±2s tolérance) → valide."""
        from utils.file_validator import validate_audio_duration_match
        wav_fs = self._make_wav_file(30.0)
        mp3_fs = self._make_mp3_file(wav_fs)
        wav_fs.stream.seek(0)
        valid, msg = validate_audio_duration_match(mp3_fs, wav_fs)
        assert valid is True

    def test_large_duration_mismatch_rejected(self, tmp_path):
        """MP3 de 10s vs WAV de 30s (écart > 2s) → refusé."""
        from utils.file_validator import validate_audio_duration_match
        wav_short = self._make_wav_file(10.0)
        mp3_short = self._make_mp3_file(wav_short)
        wav_long  = self._make_wav_file(30.0)
        wav_short.stream.seek(0)
        wav_long.stream.seek(0)
        valid, msg = validate_audio_duration_match(mp3_short, wav_long)
        assert valid is False
        assert 's' in msg  # mentionne les durées en secondes
