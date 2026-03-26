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
            'feedback' : {
                'level' : 'error',
                'message' : 'erreur : upload impossible(manque de token ?)'
            }
        }), 403

    try:
        # Récupérer les données du formulaire
        title = request.form.get('title', '').strip()
        bpm_str = request.form.get('bpm', '').strip()
        key = request.form.get('key', '').strip()
        style = request.form.get('style', '').strip()

        # Validation des champs obligatoires
        if not title:
            return jsonify({
                'success': False, 
                'feedback': {
                    'level':'warning',
                    'message' : 'Le titre est obligatoire'
                }
            }), 400
        if not bpm_str:
            return jsonify({
                'success': False, 
                'feedback': {
                    'level' : 'warning',
                    'message' : 'Le BPM est obligatoire'
                }
            }), 400

        try:
            bpm = int(bpm_str)
            if bpm < 60 or bpm > 200:
                return jsonify({
                    'success': False, 
                    'feedback' : {
                        'level' : 'warning',
                        'message': 'le BPM doit être compris entre 60 et 200'
                    }
                }), 400
        except ValueError:
            return jsonify({
                'success': False, 
                'feedback': {
                    'level' : 'warning',
                    'message' : 'le BPM doit être un nombre entier'
                }
            }), 400

        # Prix avec valeurs par défaut
        try:
            price_mp3 = float(request.form.get('price_mp3', 9.99))
            price_wav = float(request.form.get('price_wav', 19.99))
            price_stems = float(request.form.get('price_stems', 49.99))
        except ValueError:
            return jsonify({
                'success': False, 
                'feedback' : {
                    'level' : 'warning',
                    'message': 'Prix invalides'
                }
            }), 400

        # Pourcentage SACEM
        try:
            sacem_percentage_composer = int(request.form.get('sacem_percentage_composer', 50))
            if sacem_percentage_composer > 85 or sacem_percentage_composer < 0:
                return jsonify({
                    'success': False, 
                    'feedback': {
                        'level' : 'warning',
                        'message' : 'Le pourcentage SACEM doit être entre 0 et 85%'
                    }
                }), 400
        
        except ValueError:
            return jsonify({
                'success': False, 
                'feedback' : {
                    'level' : 'warning',
                    'message': 'Pourcentage SACEM invalide'
                    }
                }), 400

        # Récupérer les fichiers
        file_mp3 = request.files.get('file_mp3')
        file_wav = request.files.get('file_wav')
        file_image = request.files.get('file_image')
        file_stems = request.files.get('file_stems') if current_user.is_premium else None

        # Validation du MP3 (obligatoire)
        if not file_mp3 or file_mp3.filename == '':
            return jsonify({
                'success': False, 
                'feedback': {
                    'level' : 'warning',
                    'message' : 'Le fichier MP3 est obligatoire'
                }
            }), 400

        if not VALIDATION_AVAILABLE:
            return jsonify({
                'success': False, 
                'feedback' : {
                    'level' : 'error',
                    'message': 'Service de validation non disponible'
                }
            }), 500

        is_valid, error_message = validate_specific_audio_format(file_mp3, 'mp3')
        if not is_valid:
            return jsonify({
                'success': False, 
                'feedback' : {
                    'level' : 'error',
                    'message': f'MP3 invalide: {error_message}'
                }
            }), 400

        # Vérifier doublon via hash
        try:
            file_hash = Track.compute_file_hash(file_mp3)
            if Track.hash_exists(file_hash):
                return jsonify({
                    'success': False, 
                    'feedback' : {
                        'level' : 'error',
                        'message': 'Ce beat a déjà été uploadé'
                    }
                }), 409

        except Exception as e:
            current_app.logger.error(f'Erreur vérification doublon: {e}')
            return jsonify({
                'success': False, 
                'feedback': {
                    'level' : 'error',
                    'message' : 'Erreur de vérification du fichier'
                }
            }), 500

        # Validation du WAV (optionnel)
        if file_wav and file_wav.filename != '':
            is_valid, error_message = validate_specific_audio_format(file_wav, 'wav')
            if not is_valid:
                return jsonify({
                    'success': False, 
                    'feedback' : {
                        'level' : 'error',
                        'message': f'WAV invalide: {error_message}'
                    }
                }), 400

        # Validation de l'image (optionnel)
        if file_image and file_image.filename != '':
            is_valid, error_message = validate_image_file(file_image)
            if not is_valid:
                return jsonify({
                    'success': False, 
                    'feedback' : {
                        'level': 'error',
                        'message' : f'Image invalide: {error_message}'
                    }
                }), 400

        # Validation des stems (optionnel, premium seulement)
        if file_stems and file_stems.filename != '' and current_user.is_premium:
            is_valid, error_message = validate_stems_archive(file_stems)
            if not is_valid:
                return jsonify({
                    'success': False, 
                    'feedback' : {
                        'level' : 'error',
                        'message': f'Archive stems invalide: {error_message}'
                    }
                }), 400

        # Générer des noms de fichiers uniques
        unique_id = str(uuid.uuid4())[:8]

        # Validation du nom de fichier
        try:
            safe_title = secure_filename(title)[:30]
            safe_title = FileValidator.validate_filename(safe_title)
        except ValueError as e:
            return jsonify({
                'success': False, 
                'feedback': {
                    'level' : 'error',
                    'message' : f'Nom de track invalide: {str(e)}'
                }
            }), 400

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
            'feedback': {
                'level' : 'info',
                'message' : 'Track uploadé avec succès',
            },
            'data' : {
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
                    'tags': [
                        {'name': tag.name, 
                        'category': tag.category_obj.name if tag.category_obj else 'other'} for tag in track.tags
                    ]
                }
            }
        }), 201

    except Exception as e:
        current_app.logger.error(f'Erreur upload track: {e}', exc_info=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'feedback' : {
                'level' : 'error',
                'message': 'Erreur interne du serveur. Contactez le support.'
                }
            }), 500


@cud_tracks_api_bp.route('/track/<int:track_id>', methods=['PUT'])
@login_required
@limiter.limit("30 per hour")
def put_track(track_id):
    """
    API pour modifier un track existant
    Reçoit les données en multipart/form-data
    Réservé au compositeur du track ou à un admin
    """

    track = db.get_or_404(Track, track_id)

    # Vérifier la propriété (compositeur ou admin)
    if not (current_user.id == track.composer_id or current_user.is_admin):
        current_app.logger.warning(f'put_track() accès refusé user #{current_user.id} sur track #{track_id}')
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': 'Accès refusé : vous n\'êtes pas le compositeur de ce track'}
        }), 403

    try:
        title   = request.form.get('title',  '').strip()
        bpm_str = request.form.get('bpm',    '').strip()
        key     = request.form.get('key',    '').strip()
        style   = request.form.get('style',  '').strip()

        if not title:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le titre est obligatoire'}}), 400

        if not bpm_str:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le BPM est obligatoire'}}), 400

        try:
            bpm = int(bpm_str)
            if bpm < 60 or bpm > 200:
                return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le BPM doit être entre 60 et 200'}}), 400
        except ValueError:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Le BPM doit être un nombre entier'}}), 400

        try:
            price_mp3   = float(request.form.get('price_mp3',   track.price_mp3))
            price_wav   = float(request.form.get('price_wav',   track.price_wav))
            price_stems = float(request.form.get('price_stems', track.price_stems or 0))
        except ValueError:
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'Prix invalides'}}), 400

        # Gestion de la nouvelle image (optionnel)
        file_image = request.files.get('file_image')
        if file_image and file_image.filename != '':
            from utils.file_validator import validate_image_file
            is_valid, error_message = validate_image_file(file_image)
            if not is_valid:
                return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Image invalide: {error_message}'}}), 400

            # Supprimer l'ancienne image (sauf l'image par défaut)
            if track.image_file and track.image_file != 'default_track.png':
                old_img_path = config.IMAGES_FOLDER / 'tracks' / track.image_file
                if old_img_path.exists():
                    old_img_path.unlink()

            original_filename = secure_filename(file_image.filename)
            extension = Path(original_filename).suffix.lower()
            safe_title = secure_filename(title)[:30]
            new_img_filename = f"{safe_title}_{str(uuid.uuid4())[:8]}{extension}"

            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            new_img_path = tracks_img_folder / new_img_filename

            try:
                file_image.save(new_img_path)
                track.image_file = new_img_filename
            except Exception as e:
                current_app.logger.error(f'Erreur sauvegarde image: {e}')
                return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors du téléchargement de l\'image'}}), 500

        # Gestion des tags
        tag_ids_str = request.form.get('tag_ids', '')
        if tag_ids_str:
            try:
                tag_ids = [int(tid) for tid in tag_ids_str.split(',') if tid.strip().isdigit()]
                track.tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
            except Exception as e:
                current_app.logger.warning(f'Erreur parsing tag_ids: {e}')
        else:
            track.tags = []

        # Appliquer les modifications
        track.title     = title
        track.bpm       = bpm
        track.key       = key
        track.style     = style
        track.price_mp3 = price_mp3
        track.price_wav = price_wav
        if track.stems_file:
            track.price_stems = price_stems

        db.session.commit()

        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': 'Track mis à jour avec succès'},
            'data': {
                'track': {
                    'id':          track.id,
                    'title':       track.title,
                    'bpm':         track.bpm,
                    'key':         track.key,
                    'style':       track.style,
                    'price_mp3':   track.price_mp3,
                    'price_wav':   track.price_wav,
                    'price_stems': track.price_stems,
                    'is_approved': track.is_approved,
                    'image_file':  track.image_file,
                    'tags': [
                        {'name': tag.name, 'category': tag.category_obj.name if tag.category_obj else 'other'}
                        for tag in track.tags
                    ]
                }
            }
        }), 200

    except Exception as e:
        current_app.logger.error(f'Erreur édition track #{track_id}: {e}', exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur interne du serveur. Contactez le support.'}}), 500


@cud_tracks_api_bp.route('/track/<int:track_id>', methods=['DELETE'])
@login_required
def delete_track(track_id):
    """
    API pour supprimer un track et ses fichiers associés
    Réservé au compositeur ou à un admin
    Bloqué si le track a déjà été acheté (intégrité contrats)
    """

    track = db.get_or_404(Track, track_id)

    # Vérifier la propriété (compositeur ou admin)
    if not (current_user.id == track.composer_id or current_user.is_admin):
        current_app.logger.warning(f'delete_track() accès refusé user #{current_user.id} sur track #{track_id}')
        return jsonify({
            'success': False,
            'feedback': {'level': 'error', 'message': 'Accès refusé : vous n\'êtes pas le compositeur de ce track'}
        }), 403

    # Bloquer si le track a déjà été acheté
    from models import Purchase
    purchase_count = db.session.query(Purchase).filter_by(track_id=track.id).count()
    if purchase_count > 0:
        return jsonify({
            'success': False,
            'feedback': {
                'level': 'error',
                'message': (f'Impossible de supprimer ce track : il a été acheté {purchase_count} fois. '
                            f'Les acheteurs doivent pouvoir accéder à leurs fichiers et contrats.')
            }
        }), 403

    title = track.title

    try:
        # Supprimer les fichiers audio du disque
        for filename in [track.audio_file, track.preview_file, track.wav_file, track.stems_file]:
            if filename:
                file_path = config.UPLOAD_FOLDER / filename
                if file_path.exists():
                    file_path.unlink()

        # Supprimer l'image (sauf l'image par défaut)
        if track.image_file and track.image_file != 'default_track.png':
            image_path = config.IMAGES_FOLDER / 'tracks' / track.image_file
            if image_path.exists():
                image_path.unlink()

        db.session.delete(track)
        db.session.commit()

        current_app.logger.info(f'Track #{track_id} "{title}" supprimé par user #{current_user.id}')
        return jsonify({
            'success': True,
            'feedback': {'level': 'info', 'message': f'Track "{title}" supprimé avec succès'}
        }), 200

    except Exception as e:
        current_app.logger.error(f'Erreur suppression track #{track_id}: {e}', exc_info=True)
        db.session.rollback()
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur lors de la suppression'}}), 500
