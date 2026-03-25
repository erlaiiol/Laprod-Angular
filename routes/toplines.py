"""
Blueprint TOPLINES - Gestion des toplines
Routes pour upload, écoute, téléchargement
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_file, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from pathlib import Path
import uuid
import shutil
import librosa
import soundfile as sf
import numpy as np
from flask_wtf.csrf import validate_csrf
import config

from extensions import db, limiter
from models import Track, Tag, User, Topline
from helpers import generate_track_image, sanitize_html
from utils.ownership_authorizer import ToplineOwnership, requires_ownership
from utils.path_validator import validate_static_path

# Imports pour watermarking et validation
try:
    from utils.audio_processing import apply_watermark_and_trim, convert_to_mp3
    WATERMARK_AVAILABLE = True
except ImportError:
    WATERMARK_AVAILABLE = False

try:
    from utils.file_validator import validate_topline_file
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

toplines_bp = Blueprint('toplines', __name__)


# ============================================
# ROUTE : ÉCOUTER UNE TOPLINE
# ============================================

@toplines_bp.route('/topline/<int:topline_id>/listen')
def listen_topline(topline_id):
    """Afficher une page pour écouter une topline"""
    topline = db.get_or_404(Topline, topline_id)
    track = topline.track
    
    # Vérifier les permissions (track doit être approuvé)
    if not track.is_approved:
        if not current_user.is_authenticated or (current_user.id != track.composer_id and not current_user.is_admin):
            abort(403)
    
    return render_template('listen_topline.html', topline=topline, track=track)


# ============================================
# ROUTE : UPLOAD TOPLINE
# ============================================

# OUTDATED : upload_and_process is the same + librosa treatment


# @toplines_bp.route('/track/<int:track_id>/upload-topline', methods=['POST'])
# @limiter.limit("10 per hour")
# @login_required
# def upload_topline(track_id):
#     """Upload topline - VERSION AMÉLIORÉE avec conversion"""
#     track = Track.query.get_or_404(track_id)

#     # Vérifier les quotas de topline
#     can_submit, quota_message = current_user.can_submit_topline()
#     if not can_submit:
#         flash(f'{quota_message}', 'error')
#         return redirect(url_for('main.track_detail', track_id=track_id))

#     if not track.is_approved:
#         flash("Track pas encore disponible.", 'warning')
#         return redirect(url_for('main.index'))

#     topline_file = request.files.get('topline_audio')
#     #  SÉCURITÉ : Nettoyer la description pour éviter XSS
#     description = sanitize_html(request.form.get('description', ''))
    
#     if not topline_file or not topline_file.filename:
#         flash("Aucun fichier audio fourni.", 'danger')
#         return redirect(url_for('main.track_detail', track_id=track_id))

#     # ============================================
#     # VALIDATION SÉCURISÉE DU FICHIER
#     # ============================================

#     #  SÉCURITÉ CRITIQUE: python-magic est OBLIGATOIRE pour éviter les uploads malveillants
#     if not VALIDATION_AVAILABLE:
#         current_app.logger.error('CRITIQUE: Validation mime-type via python-magic indisponible')
#         flash('Erreur serveur: validation de sécurité non disponible. Contactez l\'administrateur.', 'error')
#         abort(500)

#     # Valider le MIME type et la taille de la topline (limite stricte: 5 MB pour forcer MP3)
#     is_valid, error_message = validate_topline_file(topline_file)
#     if not is_valid:
#         flash(f'Topline invalide : {error_message}', 'danger')
#         return redirect(url_for('main.track_detail', track_id=track_id))
    
#     # Vérifier l'extension
#     original_filename = secure_filename(topline_file.filename)
#     file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    
#     # Créer un nom de fichier unique
#     unique_id = uuid.uuid4().hex
    
#     # Sauvegarder temporairement
#     temp_filename = f"topline_temp_{unique_id}_{original_filename}"
#     temp_disk_path = config.UPLOAD_FOLDER / temp_filename
#     topline_file.save(temp_disk_path)
    
#     current_app.logger.info(f"Fichier topline uploadé: {temp_filename} ({file_ext})")
    
#     # Déterminer le nom final (convertir WebM en MP3 si nécessaire)
#     if file_ext in ['mp3', 'wav', 'ogg']:
#         # Format déjà acceptable
#         final_filename = f"topline_{unique_id}.{file_ext}"
#         final_disk_path = config.UPLOAD_FOLDER / final_filename
#         shutil.move(temp_disk_path, final_disk_path)

#     elif file_ext == 'webm':
#         # Convertir WebM en MP3
#         current_app.logger.debug(" Conversion WebM -> MP3...")
#         final_filename = f"topline_{unique_id}.mp3"
#         final_disk_path = config.UPLOAD_FOLDER / final_filename

#         try:
#             success = convert_to_mp3(str(temp_disk_path), str(final_disk_path), bitrate="192k")

#             if success:
#                 current_app.logger.debug("Conversion réussie")
#                 temp_disk_path.unlink()
#             else:
#                 current_app.logger.debug("Conversion échouée, utilisation du fichier original")
#                 shutil.move(temp_disk_path, final_disk_path)

#         except Exception as e:
#             current_app.logger.error(f"Erreur conversion: {e}", exc_info=True)
#             final_filename = f"topline_{unique_id}.webm"
#             final_disk_path = config.UPLOAD_FOLDER / final_filename
#             shutil.move(temp_disk_path, final_disk_path)
#     else:
#         # Format non reconnu mais on l'accepte quand même
#         current_app.logger.warning(f"Format audio inhabituel: {file_ext}")
#         final_filename = f"topline_{unique_id}.{file_ext}"
#         final_disk_path = config.UPLOAD_FOLDER / final_filename
#         shutil.move(temp_disk_path, final_disk_path)
    
#     # Créer l'entrée dans la BDD
#     new_topline = Topline(
#         track_id=track_id,
#         artist_id=current_user.id,
#         audio_file=f'audio/{final_filename}',
#         description=description
#     )

#     db.session.add(new_topline)
#     try:
#         db.session.commit()

#         flash(f"Topline soumise avec succès ! {current_user.topline_tokens} token(s) de topline restant(s)", 'success')
#         current_app.logger.info(f"Topline enregistrée: {final_filename}")

#         return redirect(url_for('main.track_detail', track_id=track_id))

#     except Exception as e:
#         db.session.rollback()

#         if final_disk_path.exists():
#             final_disk_path.unlink()

#         flash(f'Erreur lors de la sauvegarde de la topline: {str(e)}', 'error')
#         current_app.logger.error(f'Erreur lors de la sauvegarde. Topline: {str(e)}', exc_info=True)
#         return redirect(url_for('main.track_detail', track_id=track_id))

# ============================================
# ROUTE : DOWNLOAD TOPLINE MERGED
# ============================================

@toplines_bp.route('/download-topline-merged/<int:topline_id>')
@login_required
@requires_ownership(ToplineOwnership)
def download_topline_merged(topline_id, topline=None):
    """
    Télécharger une topline (déjà fusionnée avec le beat)

    Note: La topline sauvegardée contient déjà la voix + le beat fusionnés
    Le décorateur @requires_ownership a déjà vérifié les permissions et chargé la topline
    """
    # Le décorateur a déjà chargé la topline
    track = topline.track

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        file_path = validate_static_path(topline.audio_file)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: topline #{topline_id}, path: {topline.audio_file}")
        flash('Fichier topline introuvable.', 'danger')
        return redirect(url_for('main.track_detail', track_id=track.id))
    
    # Créer un nom de fichier descriptif
    download_name = f"{track.title.replace(' ', '_')}_{topline.artist_user.username}_topline.wav"
    
    current_app.logger.info(f"Téléchargement topline fusionnée: {download_name}")
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='audio/wav'
    )

# ============================================
# ROUTE : SUPPRIMER UNE TOPLINE
# ============================================

@toplines_bp.route('/topline/<int:topline_id>/delete', methods=['POST'])
@login_required
@requires_ownership(ToplineOwnership)
def delete_topline(topline_id, topline=None):
    """
    Supprimer une topline

    Le décorateur @requires_ownership a déjà vérifié les permissions et chargé la topline
    """
    try:
        # Sauvegarder le track_id avant suppression
        track_id = topline.track_id

        # Supprimer le fichier audio
        file_path = config.UPLOAD_FOLDER / topline.audio_file.replace('audio/', '', 1)
        if file_path.exists():
            file_path.unlink()
            current_app.logger.info(f"Deleted file: {topline.audio_file}")

        # Supprimer de la BDD
        db.session.delete(topline)
        db.session.commit()

        current_app.logger.info(f"Topline #{topline_id} deleted by user #{current_user.id}")

        # Appel JS (fetch) → JSON, formulaire HTML → redirect
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': True, 'message': 'Topline supprimée', 'track_id': track_id})

        flash('Topline supprimée avec succès.', 'success')
        return redirect(url_for('main.track_detail', track_id=track_id))

    except Exception as e:
        current_app.logger.error(f"Error deleting topline: {e}", exc_info=True)
        if request.accept_mimetypes.best == 'application/json':
            return jsonify({'success': False, 'error': str(e)}), 500
        flash('Erreur lors de la suppression.', 'danger')
        return redirect(url_for('main.track_detail', track_id=topline.track_id))


    
@toplines_bp.route('/upload-and-process', methods=['POST'])
@login_required
def upload_and_process():
    """
    Route unifiée : Upload + Effets (+ Auto-tune) + Fusion avec beat

    Workflow :
    1. Upload voix RAW (WebM/MP3)
    2. Convertir en WAV
    3. Appliquer chaîne vocale unifiée (effets + autotune si activé)
    4. Fusionner voix + instrumentale
    5. Sauvegarder en BDD
    """

    # Vérifier les quotas de topline
    can_submit, quota_message = current_user.can_submit_topline()
    if not can_submit:
        return jsonify({'success': False, 'error': quota_message}), 403

    csrf_token = request.form.get('csrf_token')

    try:
        validate_csrf(csrf_token)
    except:
        return jsonify({'success': False, 'error': 'Invalid CSRF Token'}), 403

    try:
        # Récupérer les données
        audio_file = request.files.get('audio')
        track_id = request.form.get('track_id')
        apply_autotune = request.form.get('apply_autotune', 'false') == 'true'
        
        if not audio_file or not track_id:
            return jsonify({'success': False, 'error': 'Missing audio or track_id'}), 400
        
        track = db.get_or_404(Track, track_id)
        
        # Créer timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        current_app.logger.debug(f"\n{'='*60}")
        current_app.logger.debug(f"TRAITEMENT TOPLINE - Track #{track_id}")
        current_app.logger.debug(f"Artiste: {current_user.username} (ID: {current_user.id})")
        current_app.logger.debug(f"Auto-tune: {'Activé' if apply_autotune else 'Désactivé'}")
        current_app.logger.debug(f"{'='*60}")
        
        # ===== ÉTAPE 1 : UPLOAD =====
        current_app.logger.debug("\n[1/6] Upload fichier RAW...")
        
        # Déterminer l'extension
        content_type = audio_file.content_type
        if 'webm' in content_type:
            ext = 'webm'
        elif 'mp3' in content_type or 'mpeg' in content_type:
            ext = 'mp3'
        elif 'mp4' in content_type:
            ext = 'm4a'
        else:
            ext = 'webm'  # Par défaut
        
        filename_raw = f"topline_raw_{track_id}_{current_user.id}_{timestamp}.{ext}"

        # Créer le dossier audio/toplines si nécessaire
        toplines_dir = config.UPLOAD_FOLDER / 'toplines'
        toplines_dir.mkdir(parents=True, exist_ok=True)

        raw_path = toplines_dir / filename_raw
        audio_file.save(raw_path)

        current_app.logger.debug(f"Saved: {filename_raw}")
        current_app.logger.debug(f"Size: {raw_path.stat().st_size / 1024:.1f} KB")
        
        # ===== ÉTAPE 2 : CONVERSION WebM → WAV =====
        current_app.logger.debug("\n[2/6] Conversion → WAV...")
        
        wav_temp_path = convert_to_wav(raw_path)
        current_app.logger.debug(f"   ✓ Converted to WAV")
        
        # ===== ÉTAPE 3 : EFFETS + AUTO-TUNE (chaîne unifiée) =====
        current_app.logger.debug(f"\n[3/5] Application des effets{' + auto-tune' if apply_autotune else ''}...")

        wav_effects_path = apply_audio_effects(
            wav_temp_path,
            sample_rate=48000,
            autotune_key=track.key if apply_autotune else None
        )
        wav_final_voice = wav_effects_path
        current_app.logger.debug(f"Effects applied")

        # ===== ÉTAPE 4 : FUSION VOIX + BEAT =====
        current_app.logger.debug("\n[4/5] Fusion voix + instrumentale...")




        # Charger l'instrumentale
        # Note: track.audio_file contient le chemin relatif, ex: "audio/tracks/track_123.mp3"
        beat_path = config.UPLOAD_FOLDER / track.audio_file.replace('audio/', '', 1)

        if not beat_path.exists():
            # Si le fichier n'existe pas, essayer avec le chemin complet
            beat_path_alt = Path(current_app.root_path) / 'static' / track.audio_file
            if beat_path_alt.exists():
                beat_path = beat_path_alt
                current_app.logger.debug(f"Beat trouvé: {beat_path}")
            else:
                current_app.logger.debug(f"Beat not found: {beat_path} ni {beat_path_alt}")
                return jsonify({'success': False, 'error': 'Instrumentale not found'}), 404

        # Fusionner
        final_relative_path = merge_voice_and_beat(
            voice_path=wav_final_voice,
            beat_path=str(beat_path),
            track_id=track_id,
            user_id=current_user.id,
            timestamp=timestamp
        )
        
        current_app.logger.debug(f"Merged successfully")
        
        # ===== ÉTAPE 5 : SAUVEGARDER EN BDD =====
        current_app.logger.debug("\n[5/5] Sauvegarde en base de données...")
        
        #  CRÉER LA TOPLINE AVEC LES BONNES COLONNES DU MODÈLE
        topline = Topline(
            track_id=int(track_id),           #  track_id
            artist_id=current_user.id,        #  artist_id
            audio_file=final_relative_path,   #  audio_file (chemin relatif)
            description=None                  #  description (optionnelle)
            # created_at est auto (datetime.now)
        )
        
        db.session.add(topline)
        current_user.consume_topline_token()
        db.session.commit()

        current_app.logger.debug(f"Topline #{topline.id} created as {topline.audio_file}, token consumed: {current_user.topline_tokens}")

        # Nettoyer les fichiers temporaires (wav_final_voice = wav_effects_path, pas de fichier autotune séparé)
        cleanup_temp_files([wav_temp_path, wav_effects_path])

        current_app.logger.debug(f"\n{'='*60}")
        current_app.logger.debug(f"TRAITEMENT TERMINÉ - Topline #{topline.id}")
        current_app.logger.debug(f"{'='*60}\n")

        # Retourner le résultat
        return jsonify({
            'success': True,
            'topline_id': topline.id,
            'download_url': url_for('toplines.download_topline', topline_id=topline.id, _external=True),
            'tokens_remaining': current_user.topline_tokens
        })
        
    except Exception as e:
        current_app.logger.error(f"Erreur traitement topline (autotune): {str(e)}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# ===== FONCTIONS UTILITAIRES =====

def convert_to_wav(audio_path):
    """
    Convertir n'importe quel format audio en WAV
    """
    from pydub import AudioSegment  # Import local pour éviter erreur si pydub manquant

    # Déterminer le format source
    ext = str(audio_path).lower().split('.')[-1]

    # Créer un fichier WAV temporaire
    temp_wav_path = str(audio_path).rsplit('.', 1)[0] + '_temp.wav'
    
    # Convertir
    if ext == 'webm':
        audio = AudioSegment.from_file(audio_path, format='webm')
    elif ext == 'mp3':
        audio = AudioSegment.from_mp3(audio_path)
    elif ext in ['mp4', 'm4a']:
        audio = AudioSegment.from_file(audio_path, format='mp4')
    else:
        audio = AudioSegment.from_file(audio_path)
    
    # Exporter en WAV
    audio.export(temp_wav_path, format='wav')
    
    return temp_wav_path

def apply_deesser(y, sr, center_freq=5472, reduction_db=-27, bandwidth=2000):
    """
    De-esser professionnel en mode Split
    
    Args:
        y: Signal audio (numpy array)
        sr: Sample rate
        center_freq: Fréquence centrale des sibilances (Hz) - 5472 Hz par défaut
        reduction_db: Réduction maximale en dB - -27 dB par défaut
        bandwidth: Largeur de bande du filtre (Hz) - 2000 Hz par défaut
    
    Returns:
        Signal avec sibilances atténuées
    """
    from scipy.signal import butter, sosfilt
    import numpy as np
    
    # 1. CRÉER UN FILTRE PASSE-BANDE POUR ISOLER LES SIBILANCES
    nyquist = sr / 2
    
    # Fréquences basses et hautes de la bande
    low_freq = max(center_freq - bandwidth / 2, 20)  # Minimum 20 Hz
    high_freq = min(center_freq + bandwidth / 2, nyquist - 100)  # Maximum Nyquist - marge
    
    # Normaliser par rapport à la fréquence de Nyquist
    low_normalized = low_freq / nyquist
    high_normalized = high_freq / nyquist
    
    # Filtre passe-bande d'ordre 4 (comme un filtre pro)
    sos_bandpass = butter(4, [low_normalized, high_normalized], btype='band', output='sos')
    
    # Isoler la bande des sibilances
    sibilance_band = sosfilt(sos_bandpass, y)
    
    # 2. DÉTECTER LES SIBILANCES (ENVELOPE SUIVEUR)
    # Utiliser la valeur absolue et lisser avec une fenêtre glissante
    envelope = np.abs(sibilance_band)
    
    # Fenêtre de lissage (attack/release du de-esser)
    window_size = int(sr * 0.005)  # 5ms (rapide pour les "S")
    window = np.ones(window_size) / window_size
    envelope_smooth = np.convolve(envelope, window, mode='same')
    
    # 3. CALCULER LE GAIN DE RÉDUCTION DYNAMIQUE
    # Seuil automatique basé sur le RMS de la bande
    threshold = np.sqrt(np.mean(sibilance_band ** 2)) * 1.5  # 1.5x le RMS moyen
    
    # Ratio de compression (plus c'est élevé, plus c'est agressif)
    ratio = 10  # Compression forte sur les sibilances
    
    # Calculer le gain de réduction
    gain_reduction = np.ones_like(envelope_smooth)
    
    # Là où l'envelope dépasse le seuil, appliquer la compression
    mask = envelope_smooth > threshold
    
    if np.any(mask):
        # Formule de compression : gain = 1 - (1 - threshold/level) * (1 - 1/ratio)
        over_threshold = envelope_smooth[mask] / threshold
        compression = 1.0 - (1.0 - 1.0 / over_threshold) * (1.0 - 1.0 / ratio)
        
        # Limiter la réduction maximale à reduction_db
        reduction_linear = 10 ** (reduction_db / 20)  # -27 dB = 0.0447 (95.5% de réduction)
        compression = np.maximum(compression, reduction_linear)
        
        gain_reduction[mask] = compression
    
    # 4. APPLIQUER LE GAIN DE RÉDUCTION À LA BANDE DES SIBILANCES
    sibilance_reduced = sibilance_band * gain_reduction
    
    # 5. RECONSTRUIRE LE SIGNAL
    # Signal original MOINS les sibilances originales PLUS les sibilances réduites
    y_deessed = y - sibilance_band + sibilance_reduced
    
    # Stats pour le log
    max_reduction = np.min(gain_reduction)
    max_reduction_db = 20 * np.log10(max_reduction) if max_reduction > 0 else reduction_db
    
    current_app.logger.debug(f"De-esser: {center_freq}Hz, max reduction: {max_reduction_db:.1f}dB")
    
    return y_deessed


def _make_bell_sos(center_hz, gain_db, Q, sr):
    """
    Calcul des coefficients d'un EQ paramétrique bell (RBJ Audio EQ Cookbook).
    Coût identique à un shelf (1 biquad = 5 MACs/sample) mais courbe musicale.

    Args:
        center_hz: Fréquence centrale en Hz
        gain_db: Gain en dB (positif = boost, négatif = cut)
        Q: Facteur de qualité (0.3 = très large, 0.7 = standard, 2+ = narrow)
        sr: Sample rate
    Returns:
        np.ndarray: Coefficients SOS (1 section, shape [1, 6])
    """
    A = 10 ** (gain_db / 40)  # sqrt du gain linéaire
    w0 = 2 * np.pi * center_hz / sr
    alpha = np.sin(w0) / (2 * Q)

    b0 = 1 + alpha * A
    b1 = -2 * np.cos(w0)
    b2 = 1 - alpha * A
    a0 = 1 + alpha / A
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha / A

    # Normaliser par a0 et formater en SOS [b0, b1, b2, 1, a1/a0, a2/a0]
    sos = np.array([[b0/a0, b1/a0, b2/a0, 1.0, a1/a0, a2/a0]], dtype=np.float32)
    return sos


def _generate_hall_ir(sr, decay_time=2.5, size=1.0, diffusion=1.0):
    """
    Génère une réponse impulsionnelle de type hall algorithmique.
    Schroeder/Moorer style : 6 comb filters parallèles + 2 allpass en série.
    Pas de dépendance externe.

    Args:
        sr: Sample rate
        decay_time: Temps de réverb en secondes (RT60)
        size: Taille de la salle (0-1, contrôle les délais)
        diffusion: Diffusion (0-1, contrôle le feedback des allpass)
    Returns:
        np.ndarray: IR mono (float32)
    """
    ir_length = int(sr * decay_time * 1.2)  # Marge pour la queue de reverb
    ir = np.zeros(ir_length, dtype=np.float32)

    # Délais des comb filters (en samples) — espacés pour éviter les modes
    # Valeurs classiques Schroeder/Moorer, scalées par size
    base_delays = [1557, 1617, 1491, 1422, 1277, 1356]
    comb_delays = [int(d * size * sr / 44100) for d in base_delays]

    # Feedback calculé pour atteindre -60dB au temps decay_time
    for delay in comb_delays:
        if delay <= 0:
            continue
        feedback = 10 ** (-3 * delay / (decay_time * sr))  # RT60 formula
        comb = np.zeros(ir_length, dtype=np.float32)
        comb[0] = 1.0
        for i in range(delay, ir_length):
            comb[i] += comb[i - delay] * feedback
        ir += comb

    # Normaliser les combs avant les allpass
    peak = np.max(np.abs(ir))
    if peak > 0:
        ir = ir / peak

    # Allpass filters pour diffusion (augmente la densité)
    allpass_delays = [225, 556]
    allpass_delays = [int(d * size * sr / 44100) for d in allpass_delays]

    for delay in allpass_delays:
        if delay <= 0:
            continue
        g = 0.7 * diffusion  # Coefficient allpass
        output = np.zeros(ir_length, dtype=np.float32)
        for i in range(ir_length):
            if i >= delay:
                output[i] = -g * ir[i] + ir[i - delay] + g * output[i - delay]
            else:
                output[i] = -g * ir[i]
        ir = output

    # Normaliser l'IR finale
    peak = np.max(np.abs(ir))
    if peak > 0:
        ir = ir / peak

    return ir


def apply_audio_effects(audio_path, sample_rate=48000, autotune_key=None):
    """
    Chaîne vocale unifiée :
    1. Hi-pass 160Hz (coupe rumbles/vibrations)
    2. Auto-tune (optionnel, si autotune_key fourni — sur signal propre pour meilleure détection)
    3. Noise Gate -40dB (DÉSACTIVÉ — test)
    4. De-esser 5472Hz (DÉSACTIVÉ — test)
    5. EQ : Bell large +4dB @ 6kHz (clarté vocale sans agressivité)
    6. Tanh soft limiter -1dB (seulement si signal dépasse ceiling, sinon bypass)
    7. Peak guard (atténue si > 0.9, jamais d'amplification)
    8. Hall reverb 1% wet (mid-focused, invisible mais spatiale)

    Args:
        audio_path: Chemin vers le fichier WAV
        sample_rate: Sample rate cible (48000)
        autotune_key: Clé musicale pour l'autotune (ex: "C", "D# Minor"), None = pas d'autotune
    """
    from scipy.signal import butter, sosfilt, fftconvolve

    current_app.logger.debug(f"Loading audio...")

    # float32 : ~1.8x plus rapide que float64 (SIMD double throughput)
    y, sr = sf.read(audio_path, dtype='float32')
    if y.ndim > 1:
        y = np.mean(y, axis=1)  # Mono si stéréo
    # Resample si nécessaire (soundfile charge au sr natif)
    if sr != sample_rate:
        y = librosa.resample(y, orig_sr=sr, target_sr=sample_rate)
        sr = sample_rate
    nyquist = sr / 2

    current_app.logger.debug(f"Audio: {len(y)} samples @ {sr}Hz ({len(y)/sr:.1f}s), float32")

    # 1. HI-PASS 160Hz — Coupe les rumbles, plosives, vibrations de micro
    hp_freq = 160 / nyquist
    sos_hp = butter(4, hp_freq, btype='high', output='sos')
    y = sosfilt(sos_hp, y).astype(np.float32)
    current_app.logger.debug(f"Hi-pass: 160Hz (order 4)")

    # 2. AUTO-TUNE (optionnel) — appliqué tôt dans la chaîne pour une détection de pitch optimale
    if autotune_key:
        current_app.logger.info(f"[AUTOTUNE] Appliqué dans la chaîne — key={autotune_key}")
        y = apply_autotune_effect(y, sr, key=autotune_key)
        if not isinstance(y, np.ndarray):
            y = np.array(y, dtype=np.float32)
        y = y.astype(np.float32)
    else:
        current_app.logger.debug("Auto-tune: désactivé")

    # 3. NOISE GATE (-40dB) — DÉSACTIVÉ pour test qualité audio
    # threshold_linear = np.float32(10 ** (-40 / 20))
    # y_gated = np.where(np.abs(y) > threshold_linear, y, np.float32(0))
    # current_app.logger.debug(f"Noise Gate: -40dB")
    y_gated = y
    current_app.logger.debug("Noise Gate: BYPASS (test)")

    # 4. DE-ESSER (5472Hz, -27dB) — DÉSACTIVÉ pour test qualité audio
    y_deessed = apply_deesser(y_gated, sr, center_freq=5472, reduction_db=-27, bandwidth=2000)
    # y_deessed = y_gated
    current_app.logger.debug("De-esser: activated (test)")

    # 5. EQ — Bell large +6dB @ 6kHz (Q=0.6)
    #    Un bell large centre l'énergie autour de 6kHz (zone de clarté vocale)
    #    sans exciter les artefacts >10kHz du micro/codec navigateur.
    bell_freq = min(6000, nyquist * 0.9)
    sos_bell = _make_bell_sos(bell_freq, gain_db=6.0, Q=0.6, sr=sr)
    y_eq = sosfilt(sos_bell, y_deessed).astype(np.float32)
    current_app.logger.debug(f"Bell EQ: +4dB @ {bell_freq:.0f}Hz, Q=0.6")

    # 6. TANH SOFT LIMITER -1dB
    #    np.tanh = saturation musicale naturelle (pas d'artefacts de hard clip)
    #    Seulement appliqué si le signal dépasse le ceiling — transparent sur signaux faibles
    ceiling = np.float32(10 ** (-1 / 20))  # ~0.891
    peak_pre = np.max(np.abs(y_eq))
    if peak_pre > ceiling:
        drive = np.float32(1.5)
        y_limited = np.tanh(y_eq * drive / ceiling) * ceiling
        current_app.logger.debug(f"Tanh limiter actif: peak={peak_pre:.3f} > ceiling={ceiling:.3f}")
    else:
        y_limited = y_eq
        current_app.logger.debug(f"Tanh limiter bypass: peak={peak_pre:.3f} < ceiling={ceiling:.3f}")

    # 7. PEAK GUARD — atténue seulement si le signal dépasse 0.9 (jamais d'amplification)
    peak = np.max(np.abs(y_limited))
    if peak > 0.9:
        y_normalized = y_limited * np.float32(0.9 / peak)
        current_app.logger.debug(f"Peak guard: atténué de {peak:.3f} à 0.9")
    else:
        y_normalized = y_limited
        current_app.logger.debug(f"Peak guard bypass: peak={peak:.3f} <= 0.9")

    # 8. HALL REVERB — 1% wet, mid-focused
    #    IR algorithmique (Schroeder) : pas de fichier externe nécessaire
    #    EQ de la reverb : on filtre l'IR pour garder les mediums (200Hz-6kHz)
    #    → reverb "invisible" qui ajoute de l'espace sans brouiller
    ir = _generate_hall_ir(sr, decay_time=2.5, size=1.0, diffusion=1.0)

    # Filtrer l'IR : hi-pass 200Hz + lo-pass 6kHz (reverb mid-focused)
    ir_hp = 200 / nyquist
    ir_lp = min(6000, nyquist * 0.9) / nyquist
    sos_ir_hp = butter(2, ir_hp, btype='high', output='sos')
    sos_ir_lp = butter(2, ir_lp, btype='low', output='sos')
    ir = sosfilt(sos_ir_hp, ir).astype(np.float32)
    ir = sosfilt(sos_ir_lp, ir).astype(np.float32)

    # Normaliser l'IR filtrée
    ir_peak = np.max(np.abs(ir))
    if ir_peak > 0:
        ir = ir / ir_peak

    # Convolution (fftconvolve est O(N log N) — rapide pour du offline)
    wet = fftconvolve(y_normalized, ir, mode='full')[:len(y_normalized)].astype(np.float32)

    # Mix wet/dry : 5% wet (reverb quasi-invisible, juste de l'espace)
    wet_ratio = np.float32(0.01)
    y_final = y_normalized * (1 - wet_ratio) + wet * wet_ratio

    # Re-normaliser après mix (la reverb peut légèrement pousser le niveau)
    final_peak = np.max(np.abs(y_final))
    if final_peak > 0.9:
        y_final = y_final * np.float32(0.9 / final_peak)

    current_app.logger.debug(f"Hall reverb: 5% wet, 2.5s decay, mid-focused (200-6kHz)")

    # Sauvegarder
    output_path = audio_path.replace('_temp.wav', '_effects.wav')
    sf.write(output_path, y_final, sr, format='WAV', subtype='PCM_16')

    return output_path


def apply_autotune_effect(y, sr, key='C'):
    """
    Auto-tune frame-par-frame (correction de pitch uniquement).
    - pYIN détecte le pitch de chaque frame
    - Chaque frame est corrigée vers la note la plus proche de la gamme

    Pas d'EQ ni de normalisation ici — c'est apply_audio_effects qui s'en occupe.
    L'autotune opère sur le signal brut (après hi-pass) pour une détection de pitch optimale.

    Args:
        y: Signal audio numpy array (float32)
        sr: Sample rate
        key: Clé musicale (ex: "C", "D# Minor")

    Returns:
        np.ndarray: Signal pitch-corrigé (même longueur, même sr)
    """
    current_app.logger.info(f"[AUTOTUNE] Démarrage — key={key}")

    # 1. Parser la clé : "D# Minor" → root="D#", mode="minor"
    #    Normaliser les relatives : A Minor → C Major (mêmes notes)
    parts = key.strip().split()
    root_note = parts[0]
    mode = parts[1].lower() if len(parts) > 1 else 'major'

    if mode == 'minor':
        root_hz = librosa.note_to_hz(root_note + '4')
        relative_major_hz = root_hz * (2 ** (3 / 12))
        relative_major_note = librosa.hz_to_note(relative_major_hz, unicode=False)
        root_note = relative_major_note[:-1]
        current_app.logger.debug(f"[AUTOTUNE] {parts[0]} {mode} → relative majeure {root_note} Major")

    # Construire la gamme majeure
    base_note = librosa.note_to_hz(root_note + '4')
    intervals = [0, 2, 4, 5, 7, 9, 11]

    scale_notes = []
    for octave_offset in range(-3, 4):
        for interval in intervals:
            semitones = octave_offset * 12 + interval
            freq = base_note * (2 ** (semitones / 12))
            if 50 < freq < 2000:
                scale_notes.append(freq)

    scale_notes = sorted(set(scale_notes))
    current_app.logger.debug(f"[AUTOTUNE] Gamme: {len(scale_notes)} notes ({root_note} majeur)")

    # 2. Détection de pitch haute résolution avec pYIN
    hop_length = 256
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y,
        fmin=librosa.note_to_hz('C2'),
        fmax=librosa.note_to_hz('C6'),
        sr=sr,
        frame_length=2048,
        hop_length=hop_length
    )

    n_frames = len(f0)
    voiced_count = np.sum(~np.isnan(f0) & (voiced_probs > 0.5))
    current_app.logger.debug(f"[AUTOTUNE] Frames: {n_frames} total, {voiced_count} voiced ({100*voiced_count/max(n_frames,1):.0f}%)")

    if voiced_count == 0:
        current_app.logger.warning("[AUTOTUNE] Aucune frame vocale détectée — signal inchangé")
        return y

    # 3. Calculer la correction par frame (en semitones)
    corrections = np.zeros(n_frames)
    corrected_count = 0

    for i in range(n_frames):
        freq = f0[i]
        if np.isnan(freq) or freq <= 0 or voiced_probs[i] < 0.5:
            corrections[i] = 0.0
            continue

        closest_note = min(scale_notes, key=lambda x: abs(12 * np.log2(x / freq)))
        shift = 12 * np.log2(closest_note / freq)

        if abs(shift) > 0.15:
            corrections[i] = shift
            corrected_count += 1

    current_app.logger.debug(
        f"[AUTOTUNE] Corrections: {corrected_count}/{voiced_count} frames corrigées, "
        f"shift moyen={np.mean(np.abs(corrections[corrections != 0])):.2f} semitones" if corrected_count > 0 else
        f"[AUTOTUNE] Corrections: 0 frames — voix déjà juste"
    )

    if corrected_count == 0:
        current_app.logger.info("[AUTOTUNE] Voix déjà dans la gamme — signal inchangé")
        return y

    # 4. Appliquer la correction frame-par-frame via PSOLA (overlap-add)
    y_autotune = _apply_frame_by_frame_correction(y, sr, f0, corrections, hop_length)
    current_app.logger.debug(f"[AUTOTUNE] Correction frame-par-frame appliquée")

    return y_autotune


def _apply_frame_by_frame_correction(y, sr, f0, corrections, hop_length):
    """
    Applique les corrections de pitch frame-par-frame via resynthèse segmentée.
    Chaque segment voiced est pitch-shifté individuellement, puis recollé.
    """
    y_out = y.copy()
    n_frames = len(corrections)

    # Regrouper les frames consécutives ayant la même correction (~arrondie à 0.5 semitones)
    # pour éviter de pitch-shifter frame par frame (trop d'artefacts)
    segments = []
    i = 0
    while i < n_frames:
        if corrections[i] == 0.0:
            i += 1
            continue

        # Début d'un segment à corriger
        seg_start = i
        seg_shift = corrections[i]

        # Étendre tant que les frames suivantes ont un shift similaire (±0.25 semitones)
        while i < n_frames and corrections[i] != 0.0 and abs(corrections[i] - seg_shift) < 0.25:
            seg_shift = (seg_shift + corrections[i]) / 2  # Moyenne glissante
            i += 1

        segments.append((seg_start, i, seg_shift))

    current_app.logger.debug(f"[AUTOTUNE] {len(segments)} segments à corriger")

    for seg_start, seg_end, shift in segments:
        # Convertir frames → échantillons (avec marge pour overlap)
        sample_start = max(0, seg_start * hop_length - hop_length)
        sample_end = min(len(y), seg_end * hop_length + hop_length)

        segment_audio = y[sample_start:sample_end]

        if len(segment_audio) < 512:
            continue

        # Pitch shift ce segment
        try:
            import pyrubberband as pyrb
            shifted = pyrb.pitch_shift(segment_audio, sr, n_steps=shift)
        except (ImportError, Exception):
            shifted = librosa.effects.pitch_shift(
                segment_audio, sr=sr, n_steps=shift, bins_per_octave=24
            )

        # Crossfade pour éviter les clics (fade de hop_length échantillons)
        fade_len = min(hop_length, len(shifted) // 4, len(y_out) - sample_start)
        if fade_len > 0 and sample_start + len(shifted) <= len(y_out):
            fade_in = np.linspace(0, 1, fade_len)
            fade_out = np.linspace(1, 0, fade_len)

            # Appliquer le crossfade au début
            shifted[:fade_len] = shifted[:fade_len] * fade_in + y_out[sample_start:sample_start + fade_len] * fade_out

            # Appliquer le crossfade à la fin
            end_pos = sample_start + len(shifted)
            if end_pos <= len(y_out) and fade_len <= len(shifted):
                shifted[-fade_len:] = shifted[-fade_len:] * fade_out + y_out[end_pos - fade_len:end_pos] * fade_in

            # Écrire le segment corrigé
            y_out[sample_start:sample_start + len(shifted)] = shifted

    return y_out


def merge_voice_and_beat(voice_path, beat_path, track_id, user_id, timestamp):
    """
    Fusionner la voix traitée avec l'instrumentale

    Args:
        voice_path: Chemin vers la voix traitée (WAV)
        beat_path: Chemin vers l'instrumentale (MP3/WAV)
        track_id: ID de la track
        user_id: ID de l'utilisateur
        timestamp: Timestamp pour le nom de fichier

    Returns:
        str: Chemin relatif du fichier fusionné (ex: 'audio/toplines/topline_final_X.wav')
    """
    from pydub import AudioSegment  # Import local pour éviter erreur si pydub manquant

    current_app.logger.info(f" Loading voice: {Path(voice_path).name} and beat : {Path(beat_path).name}")

    # Charger les fichiers
    voice = AudioSegment.from_wav(voice_path)
    beat = AudioSegment.from_file(beat_path)

    current_app.logger.debug(f"Voice duration: {len(voice)/1000:.2f}s")
    current_app.logger.debug(f"Beat duration: {len(beat)/1000:.2f}s")

    # Ajuster les volumes
    # Beat à -6dB (60% du volume original)
    beat_adjusted = beat - 9

    # Voix à 0dB (volume original, pas d'atténuation)
    voice_adjusted = voice + 0

    current_app.logger.debug(f"Beat volume: -9dB")
    current_app.logger.debug(f"Voice volume: 0dB")

    # Prendre la durée la plus courte
    duration = min(len(voice_adjusted), len(beat_adjusted))
    beat_trimmed = beat_adjusted[:duration]
    voice_trimmed = voice_adjusted[:duration]

    current_app.logger.debug(f"Trimmed to: {duration/1000:.2f}s")

    # Fusionner (overlay = superposer)
    merged = beat_trimmed.overlay(voice_trimmed)

    # Normaliser le résultat (éviter la saturation)
    peak = merged.max_dBFS
    if peak > -1:
        # Réduire le volume si le pic dépasse -1dB
        reduction = peak + 1
        merged = merged - reduction
        current_app.logger.debug(f"Normalized: -{reduction:.1f}dB")

    # Sauvegarder
    filename = f"topline_final_{track_id}_{user_id}_{timestamp}.wav"
    toplines_dir = config.UPLOAD_FOLDER / 'toplines'
    toplines_dir.mkdir(parents=True, exist_ok=True)
    output_path = toplines_dir / filename

    merged.export(str(output_path), format='wav')

    file_size = output_path.stat().st_size / 1024 / 1024
    current_app.logger.info(f"Saved: {filename} ({file_size:.1f} MB)")

    # Retourner le chemin RELATIF pour la BDD
    return f'audio/toplines/{filename}'


def cleanup_temp_files(file_paths):
    """
    Supprimer les fichiers temporaires
    """
    for path in file_paths:
        if path and '_temp' in str(path):
            path_obj = Path(path)
            if path_obj.exists():
                try:
                    path_obj.unlink()
                    current_app.logger.debug(f"Removed temp file: {path_obj.name}")
                except Exception as e:
                    current_app.logger.warning(f"Could not remove {path_obj.name}: {e}", exc_info=True)


# ===== ROUTES DE TÉLÉCHARGEMENT ET PUBLICATION =====

@toplines_bp.route('/topline/<int:topline_id>/download')
@login_required
@requires_ownership(ToplineOwnership)
def download_topline(topline_id, topline=None):
    """
    Télécharger le fichier fusionné

    Le décorateur @requires_ownership a déjà vérifié les permissions et chargé la topline
    """
    # Le décorateur a déjà chargé la topline

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        file_path = validate_static_path(topline.audio_file)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: topline download #{topline_id}, path: {topline.audio_file}")
        abort(404)

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f"topline_{topline_id}.wav"
    )


@toplines_bp.route('/topline/<int:topline_id>/publish', methods=['POST'])
@login_required
@requires_ownership(ToplineOwnership)
def publish_topline(topline_id, topline=None):
    """
    Publier une topline (is_published = True)

    Le décorateur @requires_ownership a déjà vérifié les permissions et chargé la topline
    """
    try:
        # Le décorateur a déjà chargé la topline et vérifié les permissions

        # Publier
        topline.is_published = True
        db.session.commit()

        current_app.logger.info(f"Topline #{topline_id} published by user #{current_user.id}")

        return jsonify({'success': True, 'message': 'Topline publiée'})

    except Exception as e:
        current_app.logger.error(f"Error publishing topline: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500