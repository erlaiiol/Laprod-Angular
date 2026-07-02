"""
Toplines Processor — pipeline de traitement audio pour les toplines.

Fonctions pures (pas de Flask Blueprint ni de DB) :
  convert_to_wav            — conversion vers WAV via pydub
  apply_audio_effects       — chaîne vocale complète (hi-pass, autotune, EQ, reverb)
  apply_autotune_effect     — correction de pitch pYIN + PSOLA frame-par-frame
  merge_voice_and_beat      — fusion voix traitée + instrumentale
  cleanup_temp_files        — suppression des fichiers temporaires

Dépendances :
  pydub, librosa, soundfile, numpy, scipy
  pyrubberband (optionnel, fallback sur librosa si absent)
"""
from pathlib import Path
from flask import current_app

import librosa
import soundfile as sf
import numpy as np
import config


# ── convert_to_wav ────────────────────────────────────────────────────────────

def convert_to_wav(audio_path):
    """
    Convertit n'importe quel format audio (webm, mp3, mp4/m4a, ogg, wav…) en WAV.
    Laisse FFmpeg détecter automatiquement le format — ne suppose jamais webm.

    Args:
        audio_path: Path ou str vers le fichier source.

    Returns:
        str: Chemin vers le fichier WAV temporaire généré.

    Raises:
        ValueError: Fichier absent, vide ou trop petit pour être audio.
        pydub.exceptions.CouldntDecodeError: FFmpeg ne peut pas décoder le fichier.
    """
    from pydub import AudioSegment

    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise ValueError(f"Fichier audio introuvable : {audio_path.name}")

    file_size = audio_path.stat().st_size
    if file_size < 512:
        raise ValueError(
            f"Fichier audio invalide ou vide ({file_size} octets). "
            "L'enregistrement a peut-être été interrompu avant le début."
        )

    temp_wav_path = str(audio_path).rsplit('.', 1)[0] + '_temp.wav'

    audio = AudioSegment.from_file(str(audio_path))
    audio.export(temp_wav_path, format='wav')
    return temp_wav_path


# ── De-esser ─────────────────────────────────────────────────────────────────

def apply_deesser(y, sr, center_freq=5472, reduction_db=-27, bandwidth=2000):
    """
    De-esser en mode Split.

    Args:
        y:            Signal audio (numpy array float32)
        sr:           Sample rate
        center_freq:  Fréquence centrale des sibilances (Hz)
        reduction_db: Réduction maximale en dB
        bandwidth:    Largeur de bande du filtre (Hz)

    Returns:
        np.ndarray: Signal avec sibilances atténuées.
    """
    from scipy.signal import butter, sosfilt

    nyquist = sr / 2
    low_freq  = max(center_freq - bandwidth / 2, 20)
    high_freq = min(center_freq + bandwidth / 2, nyquist - 100)

    low_n  = low_freq  / nyquist
    high_n = high_freq / nyquist

    sos_bandpass   = butter(4, [low_n, high_n], btype='band', output='sos')
    sibilance_band = sosfilt(sos_bandpass, y)

    envelope        = np.abs(sibilance_band)
    window_size     = int(sr * 0.005)
    window          = np.ones(window_size) / window_size
    envelope_smooth = np.convolve(envelope, window, mode='same')

    threshold      = np.sqrt(np.mean(sibilance_band ** 2)) * 1.5
    ratio          = 10
    gain_reduction = np.ones_like(envelope_smooth)
    mask           = envelope_smooth > threshold

    if np.any(mask):
        over_threshold  = envelope_smooth[mask] / threshold
        compression     = 1.0 - (1.0 - 1.0 / over_threshold) * (1.0 - 1.0 / ratio)
        reduction_linear = 10 ** (reduction_db / 20)
        compression     = np.maximum(compression, reduction_linear)
        gain_reduction[mask] = compression

    sibilance_reduced = sibilance_band * gain_reduction
    y_deessed         = y - sibilance_band + sibilance_reduced

    max_reduction    = np.min(gain_reduction)
    max_reduction_db = 20 * np.log10(max_reduction) if max_reduction > 0 else reduction_db
    current_app.logger.debug(f"De-esser: {center_freq}Hz, max reduction: {max_reduction_db:.1f}dB")

    return y_deessed


# ── EQ bell (RBJ Audio EQ Cookbook) ──────────────────────────────────────────

def _make_bell_sos(center_hz, gain_db, Q, sr):
    """
    Coefficients d'un EQ paramétrique bell.

    Returns:
        np.ndarray: Coefficients SOS (shape [1, 6]).
    """
    A  = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * center_hz / sr
    alpha = np.sin(w0) / (2 * Q)

    b0 = 1 + alpha * A
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / A

    return np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]], dtype=np.float32)


# ── Hall reverb IR (Schroeder/Moorer) ─────────────────────────────────────────

def _generate_hall_ir(sr, decay_time=2.5, size=1.0, diffusion=1.0):
    """
    Génère une réponse impulsionnelle de type hall algorithmique.

    Returns:
        np.ndarray: IR mono (float32).
    """
    ir_length   = int(sr * decay_time * 1.2)
    ir          = np.zeros(ir_length, dtype=np.float32)
    base_delays = [1557, 1617, 1491, 1422, 1277, 1356]
    comb_delays = [int(d * size * sr / 44100) for d in base_delays]

    for delay in comb_delays:
        if delay <= 0:
            continue
        feedback = 10 ** (-3 * delay / (decay_time * sr))
        comb = np.zeros(ir_length, dtype=np.float32)
        comb[0] = 1.0
        for i in range(delay, ir_length):
            comb[i] += comb[i - delay] * feedback
        ir += comb

    peak = np.max(np.abs(ir))
    if peak > 0:
        ir = ir / peak

    allpass_delays = [int(d * size * sr / 44100) for d in [225, 556]]
    for delay in allpass_delays:
        if delay <= 0:
            continue
        g      = 0.7 * diffusion
        output = np.zeros(ir_length, dtype=np.float32)
        for i in range(ir_length):
            if i >= delay:
                output[i] = -g * ir[i] + ir[i - delay] + g * output[i - delay]
            else:
                output[i] = -g * ir[i]
        ir = output

    peak = np.max(np.abs(ir))
    if peak > 0:
        ir = ir / peak

    return ir


# ── Chaîne vocale complète ────────────────────────────────────────────────────

def apply_audio_effects(audio_path, sample_rate=48000, autotune_key=None):
    """
    Chaîne vocale unifiée :
      1. Hi-pass 160 Hz
      2. Auto-tune (optionnel)
      3. Noise Gate (bypass — test)
      4. De-esser 5472 Hz
      5. Bell EQ +6 dB @ 6 kHz
      6. Tanh soft limiter -1 dB
      7. Peak guard
      8. Hall reverb 1 % wet

    Args:
        audio_path:   Chemin vers le fichier WAV source.
        sample_rate:  Sample rate cible.
        autotune_key: Clé musicale pour l'autotune (ex: "C", "D# Minor"), None = désactivé.

    Returns:
        str: Chemin vers le fichier WAV traité.
    """
    from scipy.signal import butter, sosfilt, fftconvolve

    current_app.logger.debug("Loading audio...")
    y, sr = sf.read(audio_path, dtype='float32')
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    if sr != sample_rate:
        y  = librosa.resample(y, orig_sr=sr, target_sr=sample_rate)
        sr = sample_rate
    nyquist = sr / 2

    current_app.logger.debug(f"Audio: {len(y)} samples @ {sr}Hz ({len(y)/sr:.1f}s), float32")

    # 1. Hi-pass 160 Hz
    hp_freq = 160 / nyquist
    sos_hp  = butter(4, hp_freq, btype='high', output='sos')
    y = sosfilt(sos_hp, y).astype(np.float32)
    current_app.logger.debug("Hi-pass: 160Hz (order 4)")

    # 2. Auto-tune
    if autotune_key:
        current_app.logger.info(f"[AUTOTUNE] Appliqué — key={autotune_key}")
        y = apply_autotune_effect(y, sr, key=autotune_key)
        y = np.array(y, dtype=np.float32)
    else:
        current_app.logger.debug("Auto-tune: désactivé")

    # 3. Noise Gate (bypass)
    y_gated = y
    current_app.logger.debug("Noise Gate: BYPASS (test)")

    # 4. De-esser
    y_deessed = apply_deesser(y_gated, sr, center_freq=5472, reduction_db=-27, bandwidth=2000)
    current_app.logger.debug("De-esser: activated (test)")

    # 5. Bell EQ +6 dB @ 6 kHz
    bell_freq = min(6000, nyquist * 0.9)
    sos_bell  = _make_bell_sos(bell_freq, gain_db=6.0, Q=0.6, sr=sr)
    y_eq      = sosfilt(sos_bell, y_deessed).astype(np.float32)
    current_app.logger.debug(f"Bell EQ: +6dB @ {bell_freq:.0f}Hz, Q=0.6")

    # 6. Tanh soft limiter -1 dB
    ceiling = np.float32(10 ** (-1 / 20))
    peak_pre = np.max(np.abs(y_eq))
    if peak_pre > ceiling:
        drive     = np.float32(1.5)
        y_limited = np.tanh(y_eq * drive / ceiling) * ceiling
        current_app.logger.debug(f"Tanh limiter actif: peak={peak_pre:.3f} > ceiling={ceiling:.3f}")
    else:
        y_limited = y_eq
        current_app.logger.debug(f"Tanh limiter bypass: peak={peak_pre:.3f} <= ceiling={ceiling:.3f}")

    # 7. Peak guard
    peak = np.max(np.abs(y_limited))
    if peak > 0.9:
        y_normalized = y_limited * np.float32(0.9 / peak)
        current_app.logger.debug(f"Peak guard: atténué de {peak:.3f} à 0.9")
    else:
        y_normalized = y_limited
        current_app.logger.debug(f"Peak guard bypass: peak={peak:.3f} <= 0.9")

    # 8. Hall reverb 1 % wet
    ir = _generate_hall_ir(sr, decay_time=2.5, size=1.0, diffusion=1.0)

    ir_hp    = 200 / nyquist
    ir_lp    = min(6000, nyquist * 0.9) / nyquist
    sos_ir_hp = butter(2, ir_hp, btype='high', output='sos')
    sos_ir_lp = butter(2, ir_lp, btype='low',  output='sos')
    ir = sosfilt(sos_ir_hp, ir).astype(np.float32)
    ir = sosfilt(sos_ir_lp, ir).astype(np.float32)

    ir_peak = np.max(np.abs(ir))
    if ir_peak > 0:
        ir = ir / ir_peak

    wet       = fftconvolve(y_normalized, ir, mode='full')[:len(y_normalized)].astype(np.float32)
    wet_ratio = np.float32(0.01)
    y_final   = y_normalized * (1 - wet_ratio) + wet * wet_ratio

    final_peak = np.max(np.abs(y_final))
    if final_peak > 0.9:
        y_final = y_final * np.float32(0.9 / final_peak)

    current_app.logger.debug("Hall reverb: 1% wet, 2.5s decay, mid-focused (200-6kHz)")

    output_path = audio_path.replace('_temp.wav', '_effects.wav')
    sf.write(output_path, y_final, sr, format='WAV', subtype='PCM_16')
    return output_path


# ── Auto-tune ─────────────────────────────────────────────────────────────────

def apply_autotune_effect(y, sr, key='C'):
    """
    Auto-tune frame-par-frame : pYIN → correction de pitch vers la gamme.

    Args:
        y:   Signal audio numpy array (float32)
        sr:  Sample rate
        key: Clé musicale (ex: "C", "D# Minor")

    Returns:
        np.ndarray: Signal pitch-corrigé.
    """
    current_app.logger.info(f"[AUTOTUNE] Démarrage — key={key}")

    parts     = key.strip().split()
    root_note = parts[0]
    mode      = parts[1].lower() if len(parts) > 1 else 'major'

    if mode == 'minor':
        root_hz              = librosa.note_to_hz(root_note + '4')
        relative_major_hz    = root_hz * (2 ** (3 / 12))
        relative_major_note  = librosa.hz_to_note(relative_major_hz, unicode=False)
        root_note            = relative_major_note[:-1]
        current_app.logger.debug(f"[AUTOTUNE] {parts[0]} {mode} → relative majeure {root_note} Major")

    base_note   = librosa.note_to_hz(root_note + '4')
    intervals   = [0, 2, 4, 5, 7, 9, 11]
    scale_notes = []

    for octave_offset in range(-3, 4):
        for interval in intervals:
            semitones = octave_offset * 12 + interval
            freq = base_note * (2 ** (semitones / 12))
            if 50 < freq < 2000:
                scale_notes.append(freq)

    scale_notes = sorted(set(scale_notes))
    current_app.logger.debug(f"[AUTOTUNE] Gamme: {len(scale_notes)} notes ({root_note} majeur)")

    hop_length = 256
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y,
        fmin=librosa.note_to_hz('C2'),
        fmax=librosa.note_to_hz('C6'),
        sr=sr,
        frame_length=2048,
        hop_length=hop_length,
    )

    n_frames    = len(f0)
    voiced_count = np.sum(~np.isnan(f0) & (voiced_probs > 0.5))
    current_app.logger.debug(
        f"[AUTOTUNE] Frames: {n_frames} total, {voiced_count} voiced "
        f"({100*voiced_count/max(n_frames,1):.0f}%)"
    )

    if voiced_count == 0:
        current_app.logger.warning("[AUTOTUNE] Aucune frame vocale — signal inchangé")
        return y

    corrections    = np.zeros(n_frames)
    corrected_count = 0

    for i in range(n_frames):
        freq = f0[i]
        if np.isnan(freq) or freq <= 0 or voiced_probs[i] < 0.5:
            corrections[i] = 0.0
            continue
        closest_note   = min(scale_notes, key=lambda x: abs(12 * np.log2(x / freq)))
        shift          = 12 * np.log2(closest_note / freq)
        if abs(shift) > 0.15:
            corrections[i] = shift
            corrected_count += 1

    current_app.logger.debug(
        f"[AUTOTUNE] Corrections: {corrected_count}/{voiced_count} frames corrigées, "
        f"shift moyen={np.mean(np.abs(corrections[corrections != 0])):.2f} semitones"
        if corrected_count > 0 else
        "[AUTOTUNE] Corrections: 0 frames — voix déjà juste"
    )

    if corrected_count == 0:
        current_app.logger.info("[AUTOTUNE] Voix déjà dans la gamme — signal inchangé")
        return y

    return _apply_frame_by_frame_correction(y, sr, f0, corrections, hop_length)


def _apply_frame_by_frame_correction(y, sr, f0, corrections, hop_length):
    """
    Applique les corrections de pitch frame-par-frame via resynthèse segmentée.
    """
    y_out    = y.copy()
    n_frames = len(corrections)
    segments = []
    i = 0

    while i < n_frames:
        if corrections[i] == 0.0:
            i += 1
            continue
        seg_start = i
        seg_shift = corrections[i]
        while i < n_frames and corrections[i] != 0.0 and abs(corrections[i] - seg_shift) < 0.25:
            seg_shift = (seg_shift + corrections[i]) / 2
            i += 1
        segments.append((seg_start, i, seg_shift))

    current_app.logger.debug(f"[AUTOTUNE] {len(segments)} segments à corriger")

    for seg_start, seg_end, shift in segments:
        sample_start  = max(0, seg_start * hop_length - hop_length)
        sample_end    = min(len(y), seg_end * hop_length + hop_length)
        segment_audio = y[sample_start:sample_end]

        if len(segment_audio) < 512:
            continue

        try:
            import pyrubberband as pyrb
            shifted = pyrb.pitch_shift(segment_audio, sr, n_steps=shift)
        except (ImportError, Exception):
            shifted = librosa.effects.pitch_shift(segment_audio, sr=sr, n_steps=shift, bins_per_octave=24)

        fade_len = min(hop_length, len(shifted) // 4, len(y_out) - sample_start)
        if fade_len > 0 and sample_start + len(shifted) <= len(y_out):
            fade_in  = np.linspace(0, 1, fade_len)
            fade_out = np.linspace(1, 0, fade_len)
            shifted[:fade_len]  = shifted[:fade_len]  * fade_in  + y_out[sample_start:sample_start + fade_len] * fade_out
            end_pos = sample_start + len(shifted)
            if end_pos <= len(y_out) and fade_len <= len(shifted):
                shifted[-fade_len:] = shifted[-fade_len:] * fade_out + y_out[end_pos - fade_len:end_pos] * fade_in
            y_out[sample_start:sample_start + len(shifted)] = shifted

    return y_out


# ── Fusion voix + beat ────────────────────────────────────────────────────────

def merge_voice_and_beat(voice_path, beat_path, track_id, user_id, timestamp, latency_ms=0):
    """
    Fusionne la voix traitée avec l'instrumentale via pydub.

    Args:
        voice_path:  Chemin vers la voix traitée (WAV).
        beat_path:   Chemin vers l'instrumentale (MP3/WAV).
        track_id:    ID de la track.
        user_id:     ID de l'utilisateur.
        timestamp:   Timestamp pour le nom de fichier.
        latency_ms:  Latence audio hardware mesurée côté client (AudioContext.outputLatency
                     + baseLatency). Rogne le début de la voix de cette durée pour compenser
                     le décalage perçu : l'utilisateur chante en réponse à ce qu'il entend,
                     mais le son lui parvient avec `latency_ms` ms de retard. Sans correction,
                     la voix dans le mix final est d'autant en retard sur le beat.

    Returns:
        str: Chemin relatif du fichier fusionné (ex: 'audio/toplines/topline_final_X.wav').
    """
    from pydub import AudioSegment

    current_app.logger.info(f"Loading voice: {Path(voice_path).name} and beat: {Path(beat_path).name}")

    voice = AudioSegment.from_wav(voice_path)
    beat  = AudioSegment.from_file(beat_path)

    current_app.logger.debug(f"Voice: {len(voice)/1000:.2f}s — Beat: {len(beat)/1000:.2f}s")

    # Compensation de latence hardware : rogner le début de la voix avance son
    # positionnement dans le mix sans altérer sa durée utile.
    latency_ms = max(0, min(int(latency_ms), 500))
    if latency_ms > 0 and len(voice) > latency_ms + 500:  # garder au moins 500ms de voix
        voice = voice[latency_ms:]
        current_app.logger.info(f"Sync correction: -{latency_ms}ms voice start (hardware latency)")

    beat_adjusted  = beat  - 9   # -9 dB
    voice_adjusted = voice + 0   # 0 dB (inchangé)

    duration      = min(len(voice_adjusted), len(beat_adjusted))
    beat_trimmed  = beat_adjusted[:duration]
    voice_trimmed = voice_adjusted[:duration]

    merged = beat_trimmed.overlay(voice_trimmed)

    peak = merged.max_dBFS
    if peak > -1:
        reduction = peak + 1
        merged    = merged - reduction
        current_app.logger.debug(f"Normalisé: -{reduction:.1f}dB")

    filename     = f"topline_final_{track_id}_{user_id}_{timestamp}.wav"
    toplines_dir = config.UPLOAD_FOLDER / 'toplines'
    toplines_dir.mkdir(parents=True, exist_ok=True)
    output_path  = toplines_dir / filename

    merged.export(str(output_path), format='wav')

    file_size = output_path.stat().st_size / 1024 / 1024
    current_app.logger.info(f"Saved: {filename} ({file_size:.1f} MB)")

    return f'audio/toplines/{filename}'


# ── Nettoyage des fichiers temporaires ────────────────────────────────────────

def cleanup_temp_files(file_paths):
    """
    Supprime les fichiers temporaires (ceux dont le nom contient '_temp').
    """
    for path in file_paths:
        if path and '_temp' in str(path):
            path_obj = Path(path)
            if path_obj.exists():
                try:
                    path_obj.unlink()
                    current_app.logger.debug(f"Supprimé: {path_obj.name}")
                except Exception as e:
                    current_app.logger.warning(f"Impossible de supprimer {path_obj.name}: {e}")
