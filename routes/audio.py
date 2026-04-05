"""
Blueprint AUDIO - Streaming et téléchargement de fichiers audio
Routes pour servir les fichiers audio (tracks et toplines)
"""
from flask import Blueprint, send_file, abort, current_app
from flask_login import current_user
from pathlib import Path

import config
from extensions import db, limiter
from models import Track, Topline, User
from utils.path_validator import validate_static_path

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

audio_bp = Blueprint('audio', __name__, url_prefix='/legacy/audio')

# Exempter les routes audio du rate limiter global
# Ce sont des fichiers de streaming, pas des actions sensibles
limiter.exempt(audio_bp)


# ============================================
# ROUTES STREAMING TRACKS
# ============================================

@audio_bp.route('/track/<int:track_id>/stream')
def stream_track_audio(track_id):
    """
    Servir le fichier audio d'un track (preview watermarkée)
    Cette route permet d'éviter les problèmes de routage Flask
    """
    track = db.get_or_404(Track, track_id)

    # Vérifier les permissions
    if not track.is_approved:
        if not current_user.is_authenticated or (current_user.id != track.composer_id and not current_user.is_admin):
            abort(403)

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        audio_path = validate_static_path(track.audio_file)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: track #{track_id}, path: {track.audio_file}")
        abort(404)

    # Servir le fichier avec le bon mimetype
    return send_file(
        audio_path,
        mimetype='audio/mpeg',
        as_attachment=False,  # Pour streaming
        download_name=None
    )


@audio_bp.route('/track/<int:track_id>/original')
def stream_track_original(track_id):
    """
    Servir le fichier ORIGINAL complet (file_mp3) pour le player de la page track
    Ce fichier n'est pas watermarké et contient l'audio complet
    """
    track = db.get_or_404(Track, track_id)

    # Vérifier les permissions
    if not track.is_approved:
        if not current_user.is_authenticated or (current_user.id != track.composer_id and not current_user.is_admin):
            abort(403)

    # Utiliser le fichier ORIGINAL (file_mp3) au lieu de audio_file (preview)
    file_to_serve = track.file_mp3 if track.file_mp3 else track.audio_file

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        audio_path = validate_static_path(file_to_serve)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: track #{track_id}, path: {file_to_serve}")
        abort(404)

    # Servir le fichier avec le bon mimetype
    return send_file(
        audio_path,
        mimetype='audio/mpeg',
        as_attachment=False,  # Pour streaming
        download_name=None
    )


@audio_bp.route('/track/<int:track_id>/download')
def download_track_preview(track_id):
    """
    Télécharger la preview d'un track
    """
    track = db.get_or_404(Track, track_id)

    # Vérifier les permissions
    if not track.is_approved:
        if not current_user.is_authenticated or (current_user.id != track.composer_id and not current_user.is_admin):
            abort(403)

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        audio_path = validate_static_path(track.audio_file)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: track #{track_id}, path: {track.audio_file}")
        abort(404)

    # Nom de fichier pour le téléchargement
    clean_title = track.title.replace(' ', '_').lower()
    download_name = f"{clean_title}_preview.mp3"

    # Servir le fichier en téléchargement
    return send_file(
        audio_path,
        mimetype='audio/mpeg',
        as_attachment=True,
        download_name=download_name
    )


# ============================================
# ROUTES STREAMING ÉCHANTILLONS ENGINEERS (admin)
# ============================================

@audio_bp.route('/engineer-sample/<int:user_id>/<sample_type>')
def serve_engineer_sample(user_id, sample_type):
    """
    Servir un fichier audio de candidature engineer (brut ou traité).
    """

    if sample_type not in ('raw', 'processed'):
        abort(400)

    user = db.get_or_404(User, user_id)
    stored_path = (
        user.mixmaster_sample_raw if sample_type == 'raw'
        else user.mixmaster_sample_processed
    )

    if not stored_path:
        abort(404)

    # Construire le chemin disque depuis config (ne dépend pas du contenu de la BDD)
    filename = Path(stored_path).name
    file_path = config.MIXMASTER_SAMPLES_FOLDER / filename

    if not file_path.exists():
        current_app.logger.warning(f"Échantillon engineer introuvable : {file_path}")
        abort(404)

    ext = filename.rsplit('.', 1)[-1].lower()
    mimetype_map = {
        'mp3': 'audio/mpeg',
        'wav': 'audio/wav',
        'ogg': 'audio/ogg',
        'flac': 'audio/flac',
    }
    mimetype = mimetype_map.get(ext, 'application/octet-stream')

    return send_file(file_path, mimetype=mimetype, as_attachment=False)


# ============================================
# ROUTES STREAMING TOPLINES
# ============================================

@audio_bp.route('/topline/<int:topline_id>/stream')
def stream_topline_audio(topline_id):
    """
    Servir le fichier audio d'une topline
    """
    topline = db.get_or_404(Topline, topline_id)
    track = topline.track

    # Vérifier les permissions (track doit être approuvé ou utilisateur = compositeur/admin)
    if not track.is_approved:
        if not current_user.is_authenticated or (current_user.id != track.composer_id and not current_user.is_admin):
            abort(403)

    #  SÉCURITÉ: Validation du chemin contre path traversal
    try:
        audio_path = validate_static_path(topline.audio_file)
    except ValueError as e:
        current_app.logger.error(f"Path traversal attempt: topline #{topline_id}, path: {topline.audio_file}")
        abort(404)

    # Déterminer le mimetype
    ext = topline.audio_file.rsplit('.', 1)[-1].lower()
    mimetype_map = {
        'mp3': 'audio/mpeg',
        'wav': 'audio/wav',
        'webm': 'audio/webm',
        'ogg': 'audio/ogg'
    }
    mimetype = mimetype_map.get(ext, 'application/octet-stream')

    # Servir le fichier
    return send_file(
        audio_path,
        mimetype=mimetype,
        as_attachment=False,
        download_name=None
    )
