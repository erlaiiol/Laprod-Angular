"""
Blueprint TRACKS - Gestion des beats et toplines
Routes pour upload, édition, toplines
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app, send_file, jsonify
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from pathlib import Path
import uuid
import shutil
import config

from flask_wtf.csrf import generate_csrf, validate_csrf
from werkzeug.exceptions import BadRequest
from helpers import generate_track_image
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

from extensions import db, limiter
from models import Track, Tag, Category, User, Topline
from helpers import generate_track_image
from utils.ownership_authorizer import TrackOwnership, requires_ownership

# Imports pour watermarking et validation
try:
    from utils.audio_processing import apply_watermark_and_trim, convert_to_mp3
    WATERMARK_AVAILABLE = True
except ImportError:
    WATERMARK_AVAILABLE = False

try:
    from utils.file_validator import validate_specific_audio_format, validate_stems_archive
    VALIDATION_AVAILABLE = True
except ImportError:
    VALIDATION_AVAILABLE = False

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

cud_tracks_api_bp = Blueprint('cud_tracks_api', __name__, url_prefix='/cud_tracks')

@cud_tracks_api_bp.route('/tracks', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def post_track():
    """
    API pour ajouter un nouveau track
    Reçoit les données en multipart/form-data
    """


    # Vérifier les quotas d'upload (tokens)
    can_upload, quota_message = current_user.can_upload_track()
    if not can_upload:
        current_app.logger.debug('post_track() l`utilisateur ne peut pas upload (manque de token ?)')
        return jsonify({
            'success': False,
            'error': quota_message or 'Upload impossible. Pas de token restant.'
        }), 403

    try:
        # Récupérer les données du formulaire
        title = request.form.get('title', '').strip()
        bpm_str = request.form.get('bpm', '').strip()
        key = request.form.get('key', '').strip()
        style = request.form.get('style', '').strip()

        # Validation des champs obligatoires
        if not title:
            return jsonify({'success': False, 'error': 'Le titre est obligatoire'}), 400
        if not bpm_str:
            return jsonify({'success': False, 'error': 'Le BPM est obligatoire'}), 400

        try:
            bpm = int(bpm_str)
            if bpm < 60 or bpm > 200:
                return jsonify({'success': False, 'error': 'le BPM doit être compris entre 60 et 200'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': 'le BPM doit être un nombre entier'}), 400

        # Prix avec valeurs par défaut
        try:
            price_mp3 = float(request.form.get('price_mp3', 9.99))
            price_wav = float(request.form.get('price_wav', 19.99))
            price_stems = float(request.form.get('price_stems', 49.99))
        except ValueError:
            return jsonify({'success': False, 'error': 'Prix invalides'}), 400

        # Pourcentage SACEM
        try:
            sacem_percentage_composer = int(request.form.get('sacem_percentage_composer', 50))
            if sacem_percentage_composer > 85 or sacem_percentage_composer < 0:
                return jsonify({'success': False, 'error': 'Le pourcentage SACEM doit être entre 0 et 85%'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': 'Pourcentage SACEM invalide'}), 400

        # Récupérer les fichiers
        file_mp3 = request.files.get('file_mp3')
        file_wav = request.files.get('file_wav')
        file_image = request.files.get('file_image')
        file_stems = request.files.get('file_stems') if current_user.is_premium else None

        # Validation du MP3 (obligatoire)
        if not file_mp3 or file_mp3.filename == '':
            return jsonify({'success': False, 'error': 'Le fichier MP3 est obligatoire'}), 400

        if not VALIDATION_AVAILABLE:
            return jsonify({'success': False, 'error': 'Service de validation non disponible'}), 500

        is_valid, error_message = validate_specific_audio_format(file_mp3, 'mp3')
        if not is_valid:
            return jsonify({'success': False, 'error': f'MP3 invalide: {error_message}'}), 400

        # Vérifier doublon via hash
        try:
            file_hash = Track.compute_file_hash(file_mp3)
            if Track.hash_exists(file_hash):
                return jsonify({'success': False, 'error': 'Ce beat a déjà été uploadé'}), 409
        except Exception as e:
            current_app.logger.error(f'Erreur vérification doublon: {e}')
            return jsonify({'success': False, 'error': 'Erreur de vérification du fichier'}), 500

        # Validation du WAV (optionnel)
        if file_wav and file_wav.filename != '':
            is_valid, error_message = validate_specific_audio_format(file_wav, 'wav')
            if not is_valid:
                return jsonify({'success': False, 'error': f'WAV invalide: {error_message}'}), 400

        # Validation de l'image (optionnel)
        if file_image and file_image.filename != '':
            is_valid, error_message = validate_image_file(file_image)
            if not is_valid:
                return jsonify({'success': False, 'error': f'Image invalide: {error_message}'}), 400

        # Validation des stems (optionnel, premium seulement)
        if file_stems and file_stems.filename != '' and current_user.is_premium:
            is_valid, error_message = validate_stems_archive(file_stems)
            if not is_valid:
                return jsonify({'success': False, 'error': f'Archive stems invalide: {error_message}'}), 400

        # Générer des noms de fichiers uniques
        unique_id = str(uuid.uuid4())[:8]

        # Validation du nom de fichier
        try:
            safe_title = secure_filename(title)[:30]
            safe_title = FileValidator.validate_filename(safe_title)
        except ValueError as e:
            return jsonify({'success': False, 'error': f'Nom de track invalide: {str(e)}'}), 400

        # Créer le dossier upload si nécessaire
        config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)

        # Traitement du MP3
        mp3_filename = f"{safe_title}_{unique_id}_full.mp3"
        mp3_disk_path = config.UPLOAD_FOLDER / mp3_filename
        file_mp3.save(mp3_disk_path)

        # Créer le preview watermarké
        preview_filename = f"{safe_title}_{unique_id}_preview.mp3"
        preview_disk_path = config.UPLOAD_FOLDER / preview_filename

        if WATERMARK_AVAILABLE:
            try:
                watermark_path = Path(current_app.root_path) / 'static' / 'audio' / 'watermark.mp3'
                apply_watermark_and_trim(
                    input_path=str(mp3_disk_path),
                    output_path=str(preview_disk_path),
                    watermark_path=str(watermark_path),
                    preview_duration=90,
                    watermark_positions=[20, 45]
                )
            except Exception as e:
                current_app.logger.error(f"Erreur watermark: {e}")
                shutil.copy(mp3_disk_path, preview_disk_path)
        else:
            shutil.copy(mp3_disk_path, preview_disk_path)

        # Traitement du WAV (optionnel)
        wav_filename = None
        if file_wav and file_wav.filename != '':
            wav_filename = f"{safe_title}_{unique_id}_full.wav"
            wav_disk_path = config.UPLOAD_FOLDER / wav_filename
            file_wav.save(wav_disk_path)

        # Traitement des stems (optionnel)
        stems_filename = None
        if file_stems and file_stems.filename != '':
            stems_filename = f"{safe_title}_{unique_id}_stems.zip"
            stems_disk_path = config.UPLOAD_FOLDER / stems_filename
            file_stems.save(stems_disk_path)

        # Traitement de l'image
        if file_image and file_image.filename != '':
            original_filename = secure_filename(file_image.filename)
            extension = Path(original_filename).suffix.lower()
            image_filename = f"{safe_title}_{unique_id}{extension}"

            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            image_disk_path = tracks_img_folder / image_filename
            file_image.save(image_disk_path)
        else:
            # Générer une image automatiquement
            image_filename = f"{safe_title}_{unique_id}.png"
            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            image_disk_path = tracks_img_folder / image_filename

            try:
                generate_track_image(title=title, scale=key, output_path=image_disk_path)
            except Exception as e:
                current_app.logger.error(f"Erreur génération image: {e}")
                image_filename = 'default_track.png'

        # Traitement des tags
        tag_ids_str = request.form.get('tag_ids', '')
        selected_tags = []

        if tag_ids_str:
            try:
                tag_ids = [int(tid) for tid in tag_ids_str.split(',') if tid.strip().isdigit()]
                selected_tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
            except Exception as e:
                current_app.logger.warning(f'Erreur parsing tag_ids: {e}')

        # Créer le track
        track = Track(
            title=title,
            bpm=bpm,
            key=key,
            style=style,
            price_mp3=price_mp3,
            price_wav=price_wav,
            price_stems=price_stems,
            sacem_percentage_composer=sacem_percentage_composer,
            composer_user=current_user,
            audio_file=mp3_filename,
            preview_file=preview_filename,
            wav_file=wav_filename,
            stems_file=stems_filename,
            image_file=image_filename,
            file_hash=file_hash,
            tags=selected_tags
        )

        db.session.add(track)
        db.session.commit()

        # Déduire le token d'upload
        current_user.upload_tokens -= 1
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Track uploadé avec succès',
            'track': {
                'id': track.id,
                'title': track.title,
                'bpm': track.bpm,
                'key': track.key,
                'style': track.style,
                'price_mp3': track.price_mp3,
                'price_wav': track.price_wav,
                'price_stems': track.price_stems,
                'is_approved': track.is_approved,
                'composer_user': {
                    'username': track.composer_user.username
                },
                'audio_file': track.audio_file,
                'image_file': track.image_file,
                'tags': [{'name': tag.name, 'category': tag.category_obj.name if tag.category_obj else 'other'} for tag in track.tags]
            }
        }), 201

    except Exception as e:
        current_app.logger.error(f'Erreur upload track: {e}', exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'error': 'Erreur interne du serveur. Contactez le support.'}), 500 

