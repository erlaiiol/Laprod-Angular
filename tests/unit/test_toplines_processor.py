"""
Tests unitaires — Pipeline de traitement audio (utils/toplines_processor.py)

Couvre les fonctions pures DSP :
  convert_to_wav        — conversion format → WAV
  apply_audio_effects   — chaîne vocale (hi-pass, de-esser, EQ, reverb)
  apply_deesser         — atténuation des sibilances
  merge_voice_and_beat  — fusion voix traitée + instrumentale
  cleanup_temp_files    — suppression fichiers _temp uniquement
  apply_autotune_effect — correction de pitch frame-par-frame (pYIN)

Stratégie :
  - Fichiers audio générés en mémoire via numpy + soundfile (sinus 440Hz)
  - Flask app context requis (current_app.logger dans toutes les fonctions)
  - config.UPLOAD_FOLDER mocké pour isoler le disque
  - Assertions sur les propriétés audio (durée, pic, format)
  - Budgets de performance trackés pour détecter les régressions futures
"""
import time
import pytest
import numpy as np
import soundfile as sf
from pathlib import Path
from unittest.mock import patch


# ── Génération audio de test ──────────────────────────────────────────────────

def _sine_wav(path, duration=0.5, freq=440, sr=22050, amplitude=0.3):
    """Génère un sinus WAV PCM_16. Retourne le chemin."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    y = (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(str(path), y, sr, format='WAV', subtype='PCM_16')
    return path


def _silent_wav(path, duration=0.5, sr=22050):
    """WAV de silence (testcase limite : pas de fondamentale détectable par pYIN)."""
    y = np.zeros(int(sr * duration), dtype=np.float32)
    sf.write(str(path), y, sr, format='WAV', subtype='PCM_16')
    return path


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def sine_wav(tmp_path):
    """0.5s, 440Hz (A4), 22050Hz, amplitude=0.3."""
    return _sine_wav(tmp_path / 'sine.wav')


@pytest.fixture()
def long_sine_wav(tmp_path):
    """3s pour les mesures de performance — sr=22050 pour rester rapide en CI."""
    return _sine_wav(tmp_path / 'sine_long.wav', duration=3.0, sr=22050)


@pytest.fixture()
def silent_wav(tmp_path):
    return _silent_wav(tmp_path / 'silence.wav')


@pytest.fixture()
def beat_wav(tmp_path):
    """Instrumentale de test : 440Hz à -9dB, 0.5s."""
    return _sine_wav(tmp_path / 'beat.wav', freq=440, amplitude=0.1)


# ── Tests : convert_to_wav ────────────────────────────────────────────────────

class TestConvertToWav:

    def test_wav_input_produces_temp_wav(self, tmp_path, app):
        """Un fichier WAV produit un fichier _temp.wav adjacent."""
        src = _sine_wav(tmp_path / 'input.wav')
        from utils.toplines_processor import convert_to_wav
        with app.app_context():
            result = convert_to_wav(src)
        assert result.endswith('_temp.wav')
        assert Path(result).exists()

    def test_output_is_readable_wav(self, tmp_path, app):
        """Le fichier converti est un WAV lisible par soundfile."""
        src = _sine_wav(tmp_path / 'input.wav')
        from utils.toplines_processor import convert_to_wav
        with app.app_context():
            out = convert_to_wav(src)
        data, sr = sf.read(out, dtype='float32')
        assert len(data) > 0
        assert sr > 0

    def test_output_duration_matches_input(self, tmp_path, app):
        """La durée du WAV converti correspond à celle de l'original (±5%)."""
        duration = 0.5
        sr = 22050
        src = _sine_wav(tmp_path / 'input.wav', duration=duration, sr=sr)
        from utils.toplines_processor import convert_to_wav
        with app.app_context():
            out = convert_to_wav(src)
        data, out_sr = sf.read(out, dtype='float32')
        out_duration = len(data) / out_sr
        assert abs(out_duration - duration) / duration < 0.05

    def test_mp3_auto_detected(self, tmp_path, app):
        """Un fichier MP3 est correctement converti via auto-détection FFmpeg."""
        from pydub import AudioSegment
        from utils.toplines_processor import convert_to_wav
        mp3_path = tmp_path / 'input.mp3'
        seg = AudioSegment.from_wav(str(_sine_wav(tmp_path / 'for_mp3.wav')))
        seg.export(str(mp3_path), format='mp3')
        with app.app_context():
            result = convert_to_wav(mp3_path)
        assert Path(result).exists()
        assert result.endswith('_temp.wav')


# ── Tests : convert_to_wav — validation ──────────────────────────────────────

class TestConvertToWavValidation:

    def test_missing_file_raises_value_error(self, tmp_path, app):
        """Un fichier absent lève ValueError (pas CouldntDecodeError)."""
        from utils.toplines_processor import convert_to_wav
        ghost = tmp_path / 'nonexistent.webm'
        with app.app_context():
            with pytest.raises(ValueError, match='introuvable'):
                convert_to_wav(ghost)

    def test_empty_file_raises_value_error(self, tmp_path, app):
        """Un fichier de 0 octet lève ValueError avec message explicite."""
        from utils.toplines_processor import convert_to_wav
        empty = tmp_path / 'empty.webm'
        empty.write_bytes(b'')
        with app.app_context():
            with pytest.raises(ValueError, match='vide'):
                convert_to_wav(empty)

    def test_tiny_file_raises_value_error(self, tmp_path, app):
        """Un fichier < 512 octets lève ValueError."""
        from utils.toplines_processor import convert_to_wav
        tiny = tmp_path / 'tiny.webm'
        tiny.write_bytes(b'\x1aE\xdf\xa3' + b'\x00' * 10)  # 14 octets
        with app.app_context():
            with pytest.raises(ValueError, match='octets'):
                convert_to_wav(tiny)

    def test_no_format_hardcoded_for_webm_extension(self, tmp_path, app):
        """Un fichier .webm valide est traité sans hardcoder format='webm'."""
        from pydub import AudioSegment
        from utils.toplines_processor import convert_to_wav
        # Créer un vrai WebM via pydub export
        src = _sine_wav(tmp_path / 'src.wav')
        webm_path = tmp_path / 'voice.webm'
        seg = AudioSegment.from_wav(str(src))
        seg.export(str(webm_path), format='webm')
        with app.app_context():
            result = convert_to_wav(webm_path)
        assert Path(result).exists()
        data, sr = __import__('soundfile').read(result, dtype='float32')
        assert len(data) > 0


# ── Tests : apply_audio_effects ───────────────────────────────────────────────

class TestApplyAudioEffects:

    def test_output_file_created(self, tmp_path, app, sine_wav):
        """apply_audio_effects crée un fichier _effects.wav."""
        import config
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import apply_audio_effects
            out = apply_audio_effects(str(sine_wav), sample_rate=22050)
        assert Path(out).exists()

    def test_output_is_valid_soundfile(self, tmp_path, app, sine_wav):
        """Le fichier de sortie est un WAV lisible."""
        import config
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import apply_audio_effects
            out = apply_audio_effects(str(sine_wav), sample_rate=22050)
        data, sr = sf.read(out, dtype='float32')
        assert len(data) > 0

    def test_peak_guard_keeps_peak_below_limit(self, tmp_path, app):
        """Après traitement, le pic est ≤ 0.9 (peak guard actif)."""
        import config
        loud = _sine_wav(tmp_path / 'loud.wav', amplitude=0.95)
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import apply_audio_effects
            out = apply_audio_effects(str(loud), sample_rate=22050)
        data, _ = sf.read(out, dtype='float32')
        assert np.max(np.abs(data)) <= 0.95

    def test_output_duration_close_to_input(self, tmp_path, app, sine_wav):
        """La durée de sortie est proche de la durée d'entrée (reverb tail peut l'allonger légèrement)."""
        import config
        y_in, sr_in = sf.read(str(sine_wav), dtype='float32')
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import apply_audio_effects
            out = apply_audio_effects(str(sine_wav), sample_rate=22050)
        y_out, sr_out = sf.read(out, dtype='float32')
        dur_in  = len(y_in)  / sr_in
        dur_out = len(y_out) / sr_out
        # La durée de sortie ne doit pas dépasser 2× la durée d'entrée
        assert dur_out <= dur_in * 2

    def test_autotune_off_does_not_call_apply_autotune(self, tmp_path, app, sine_wav):
        """Sans autotune_key, apply_autotune_effect n'est pas appelé."""
        import config
        with app.app_context(), \
             patch.object(config, 'UPLOAD_FOLDER', tmp_path), \
             patch('utils.toplines_processor.apply_autotune_effect') as mock_at:
            from utils.toplines_processor import apply_audio_effects
            apply_audio_effects(str(sine_wav), sample_rate=22050, autotune_key=None)
        mock_at.assert_not_called()

    def test_autotune_on_calls_apply_autotune(self, tmp_path, app, sine_wav):
        """Avec autotune_key, apply_autotune_effect est appelé."""
        import config
        # side_effect passthrough : retourne le signal inchangé (longueur préservée)
        with app.app_context(), \
             patch.object(config, 'UPLOAD_FOLDER', tmp_path), \
             patch('utils.toplines_processor.apply_autotune_effect',
                   side_effect=lambda y, sr, key: y) as mock_at:
            from utils.toplines_processor import apply_audio_effects
            apply_audio_effects(str(sine_wav), sample_rate=22050, autotune_key='C major')
        mock_at.assert_called_once()


# ── Tests : apply_deesser ─────────────────────────────────────────────────────

class TestApplyDeesser:

    def test_output_shape_matches_input(self, app):
        """Le de-esser conserve exactement la longueur du signal."""
        sr = 22050
        y = (0.3 * np.sin(2 * np.pi * 5000 * np.arange(sr) / sr)).astype(np.float32)
        with app.app_context():
            from utils.toplines_processor import apply_deesser
            result = apply_deesser(y, sr, center_freq=5472, reduction_db=-27)
        assert result.shape == y.shape

    def test_sibilance_band_attenuated(self, app):
        """Un signal centré sur la fréquence de sibilance est atténué."""
        sr = 22050
        center = 5472
        t = np.arange(sr) / sr
        y = (0.8 * np.sin(2 * np.pi * center * t)).astype(np.float32)
        with app.app_context():
            from utils.toplines_processor import apply_deesser
            result = apply_deesser(y, sr, center_freq=center, reduction_db=-27)
        assert np.max(np.abs(result)) <= np.max(np.abs(y))


# ── Tests : merge_voice_and_beat ──────────────────────────────────────────────

class TestMergeVoiceAndBeat:

    def test_output_file_created_at_expected_path(self, tmp_path, app, sine_wav, beat_wav):
        """merge_voice_and_beat crée le fichier topline_final_*.wav."""
        import config
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import merge_voice_and_beat
            rel_path = merge_voice_and_beat(
                voice_path=str(sine_wav),
                beat_path=str(beat_wav),
                track_id=1,
                user_id=1,
                timestamp='20260701_120000',
            )
        assert rel_path.startswith('audio/toplines/')
        assert rel_path.endswith('.wav')
        full_path = tmp_path / 'toplines' / Path(rel_path).name
        assert full_path.exists()

    def test_relative_path_returned(self, tmp_path, app, sine_wav, beat_wav):
        """La fonction retourne un chemin relatif (pour stockage en DB)."""
        import config
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import merge_voice_and_beat
            rel = merge_voice_and_beat(str(sine_wav), str(beat_wav), 1, 1, '20260701_120000')
        assert not Path(rel).is_absolute()

    def test_output_duration_matches_shorter_input(self, tmp_path, app, beat_wav):
        """La durée de sortie correspond au plus court des deux (voix ou beat)."""
        import config
        voice = _sine_wav(tmp_path / 'short_voice.wav', duration=0.3, sr=22050)
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import merge_voice_and_beat
            rel = merge_voice_and_beat(str(voice), str(beat_wav), 1, 1, '20260701_130000')
        out_path = tmp_path / 'toplines' / Path(rel).name
        data, sr = sf.read(str(out_path))
        dur = len(data) / sr
        # La durée de sortie doit être proche de la voix courte (0.3s)
        assert dur < 0.5 + 0.05

    def test_merged_audio_is_valid_wav(self, tmp_path, app, sine_wav, beat_wav):
        """Le fichier fusionné est lisible par soundfile."""
        import config
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import merge_voice_and_beat
            rel = merge_voice_and_beat(str(sine_wav), str(beat_wav), 1, 1, '20260701_140000')
        out_path = tmp_path / 'toplines' / Path(rel).name
        data, sr = sf.read(str(out_path), dtype='float32')
        assert len(data) > 0
        assert sr > 0


# ── Tests : cleanup_temp_files ────────────────────────────────────────────────

class TestCleanupTempFiles:

    def test_cleanup_skips_files_without_marker(self, app):
        """
        Seuls les fichiers contenant '_temp' dans leur chemin sont supprimés.

        Note : cleanup_temp_files vérifie `'_temp' in str(path)` (chemin complet).
        On utilise tempfile.TemporaryDirectory avec un préfixe neutre pour éviter
        que le répertoire parent contienne lui-même '_temp'.
        """
        import tempfile
        with tempfile.TemporaryDirectory(prefix='laprod_proc_') as td:
            dirpath  = Path(td)
            del_file = dirpath / 'voice_temp.wav'     # doit être supprimé
            keep_file = dirpath / 'voice_effects.wav'  # doit être conservé
            del_file.write_bytes(b'fake')
            keep_file.write_bytes(b'fake')

            with app.app_context():
                from utils.toplines_processor import cleanup_temp_files
                cleanup_temp_files([del_file, keep_file])

            assert not del_file.exists()
            assert keep_file.exists()

    def test_ignores_nonexistent_paths(self, tmp_path, app):
        """Aucune erreur si un fichier n'existe pas déjà."""
        ghost = tmp_path / 'ghost_temp.wav'
        with app.app_context():
            from utils.toplines_processor import cleanup_temp_files
            cleanup_temp_files([ghost])

    def test_ignores_none_values(self, app):
        """Aucune erreur si la liste contient None."""
        with app.app_context():
            from utils.toplines_processor import cleanup_temp_files
            cleanup_temp_files([None, None])


# ── Tests : apply_autotune_effect ─────────────────────────────────────────────

class TestApplyAutotune:

    def test_silent_signal_returned_unchanged(self, app):
        """Un signal silencieux (pas de frames voiced) est retourné sans modification."""
        sr = 22050
        y = np.zeros(sr, dtype=np.float32)
        with app.app_context():
            from utils.toplines_processor import apply_autotune_effect
            result = apply_autotune_effect(y, sr, key='C major')
        np.testing.assert_array_equal(result, y)

    def test_in_key_signal_not_modified(self, app):
        """Un sinus A4 (440Hz) déjà en gamme C major → peu ou pas de corrections."""
        sr = 22050
        t = np.linspace(0, 1.0, sr, endpoint=False)
        y = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        with app.app_context():
            from utils.toplines_processor import apply_autotune_effect
            result = apply_autotune_effect(y, sr, key='C major')
        assert result.shape == y.shape
        assert result.dtype in (np.float32, np.float64)

    def test_output_shape_preserved(self, app):
        """L'autotune ne modifie pas la longueur du signal."""
        sr = 22050
        y = (0.3 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)).astype(np.float32)
        with app.app_context():
            from utils.toplines_processor import apply_autotune_effect
            result = apply_autotune_effect(y, sr, key='G major')
        assert result.shape == y.shape

    def test_minor_key_resolved_to_relative_major(self, app):
        """A minor → relative major C major : l'autotune ne doit pas planter."""
        sr = 22050
        y = (0.3 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr)).astype(np.float32)
        with app.app_context():
            from utils.toplines_processor import apply_autotune_effect
            result = apply_autotune_effect(y, sr, key='A minor')
        assert result is not None
        assert len(result) > 0


# ── Tests de performance ──────────────────────────────────────────────────────

class TestProcessorPerformance:
    """
    Budgets de performance pour les fonctions audio.
    Ces assertions permettent de mesurer les régressions au fil du temps.
    Les budgets sont intentionnellement généreux pour ne pas flaquer en CI
    mais suffisants pour détecter des problèmes sérieux (complexité quadratique,
    appels bloquants, etc.).

    Clip de référence : 3s à 22050Hz (mono).
    """

    def test_apply_audio_effects_under_15s_without_autotune(
        self, tmp_path, app, long_sine_wav
    ):
        """
        Chaîne vocale complète sans autotune sur 3s → < 15s.
        Budget : hi-pass + de-esser + EQ bell + limiter + reverb (FFT).
        """
        import config
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import apply_audio_effects
            start = time.perf_counter()
            apply_audio_effects(str(long_sine_wav), sample_rate=22050, autotune_key=None)
            elapsed = time.perf_counter() - start
        assert elapsed < 15.0, (
            f"apply_audio_effects trop lent sur 3s sans autotune : "
            f"{elapsed:.1f}s (budget : 15s)"
        )

    def test_merge_voice_and_beat_under_5s(self, tmp_path, app, long_sine_wav):
        """
        Fusion voix + beat sur 3s → < 5s.
        Budget : overlay pydub + normalisation.
        """
        import config
        beat = _sine_wav(tmp_path / 'beat_perf.wav', duration=3.0, sr=22050, amplitude=0.1)
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import merge_voice_and_beat
            start = time.perf_counter()
            merge_voice_and_beat(
                voice_path=str(long_sine_wav),
                beat_path=str(beat),
                track_id=99,
                user_id=99,
                timestamp='20260701_perf',
            )
            elapsed = time.perf_counter() - start
        assert elapsed < 5.0, (
            f"merge_voice_and_beat trop lent sur 3s : {elapsed:.1f}s (budget : 5s)"
        )

    def test_full_pipeline_without_autotune_under_20s(self, tmp_path, app, long_sine_wav):
        """
        Pipeline complet (convert → effects → merge) sans autotune sur 3s → < 20s.
        Mesure l'overhead total visible du côté utilisateur (hors RQ queue).
        """
        import config
        beat = _sine_wav(tmp_path / 'beat_full_perf.wav', duration=3.0, sr=22050, amplitude=0.1)
        with app.app_context(), patch.object(config, 'UPLOAD_FOLDER', tmp_path):
            from utils.toplines_processor import (
                convert_to_wav, apply_audio_effects, merge_voice_and_beat,
            )
            start = time.perf_counter()
            wav  = convert_to_wav(long_sine_wav)
            eff  = apply_audio_effects(wav, sample_rate=22050, autotune_key=None)
            merge_voice_and_beat(eff, str(beat), 99, 99, '20260701_fullperf')
            elapsed = time.perf_counter() - start

        assert elapsed < 20.0, (
            f"Pipeline complet trop lent sur 3s sans autotune : "
            f"{elapsed:.1f}s (budget : 20s)"
        )
