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

tracks_bp = Blueprint('tracks', __name__)


# # ============================================
# # ROUTE 1 : AJOUTER UN TRACK
# # ============================================

# @tracks_bp.route('/add-track', methods=['GET', 'POST'])
# @limiter.limit("20 per hour")
# @login_required
# def add_track():
#     """Ajouter une nouvelle composition avec pourcentage SACEM"""

#     # OUTDATED WITH WALLETS
#     # Vérifier que l'utilisateur a configuré son compte de paiement
#     # if not current_user.can_receive_payments():
#     #     flash('Vous devez d\'abord configurer votre compte de paiement pour vendre des compositions', 'warning')
#     #     return redirect(url_for('stripe_connect.setup'))

#     # Vérifier les quotas d'upload (tokens)
#     can_upload, quota_message = current_user.can_upload_track()
#     if not can_upload:
#         flash(f'{quota_message}', 'error')
#         return redirect(url_for('main.index'))

#     def _rerender(field=None):
#         """Ré-affiche le formulaire en conservant les données saisies."""
#         return render_template('add_track.html', form_data=request.form, error_field=field)

#     if request.method == 'POST':
#         # Récupérer les données du formulaire
#         title = request.form.get('title')
#         bpm = request.form.get('bpm')
#         key = request.form.get('key')
#         style = request.form.get('style')
        
#         # Prix
#         price_mp3 = float(request.form.get('price_mp3', 9.99))
#         price_wav = float(request.form.get('price_wav', 19.99))
#         price_stems = float(request.form.get('price_stems', 49.99))
        
#         # Pourcentage SACEM (max 85% pour le compositeur, min 15% pour l'acheteur)
#         sacem_percentage_composer = int(request.form.get('sacem_percentage_composer', 50))

#         # Validation: bloquer à 85% maximum
#         if sacem_percentage_composer > 85:
#             flash('Le pourcentage SACEM compositeur ne peut pas dépasser 85% (minimum 15% pour l\'acheteur)', 'error')
#             return _rerender('sacem_percentage_composer')

#         if sacem_percentage_composer < 0:
#             flash('Le pourcentage SACEM doit être entre 0 et 85%', 'error')
#             return _rerender('sacem_percentage_composer')

#         # Récupérer les fichiers uploadés
#         file_mp3 = request.files.get('file_mp3')
#         file_wav = request.files.get('file_wav')

#         # Récupérer l'image (si proposée)
#         file_image = request.files.get('file_image')

#         if current_user.is_premium: 
#             file_stems = request.files.get('file_stems')

#         else:
#             file_stems = None

#         # ============================================
#         # VALIDATION SÉCURISÉE DES FICHIERS
#         # ============================================
        
#         # 1. Vérifier que le MP3 existe
#         if not file_mp3 or file_mp3.filename == '':
#             flash('Le fichier MP3 est obligatoire', 'danger')
#             return _rerender('file_mp3')
        
#         # 2. Valider le MIME type du MP3 (protection contre malware)
#         #  SÉCURITÉ CRITIQUE: python-magic est OBLIGATOIRE pour éviter les uploads malveillants
#         if not VALIDATION_AVAILABLE:
#             current_app.logger.error('CRITIQUE: Validation mime-type via python-magic indisponible')
#             flash('Erreur serveur: validation de sécurité non disponible. Contactez l\'administrateur.', 'error')
#             abort(500)

#         from utils.file_validator import validate_specific_audio_format
#         is_valid, error_message = validate_specific_audio_format(file_mp3, 'mp3')
#         if not is_valid:
#             flash(f'MP3 invalide : {error_message}', 'danger')
#             return _rerender('file_mp3')

#         # 2b. Vérifier doublon via hash MP3
#         try:
#             file_hash = Track.compute_file_hash(file_mp3)
#             if Track.hash_exists(file_hash):
#                 current_app.logger.warning(f'Tentative upload doublon par user {current_user.id} (hash: {file_hash[:16]}...)')
#                 flash('Ce beat a déjà été uploadé sur la plateforme.', 'danger')
#                 return _rerender('file_mp3')
#         except Exception as e:
#             current_app.logger.error(f'Erreur vérification doublon: {e}')
#             flash('Erreur lors de la vérification du fichier hash_exists().', 'danger')
#             return _rerender('file_mp3')

#         # 3. Valider le WAV s'il est fourni (doit être un vrai WAV)
#         if file_wav and file_wav.filename != '':
#             # Validation déjà vérifiée disponible (abort 500 si non dispo)
#             from utils.file_validator import validate_specific_audio_format
#             is_valid, error_message = validate_specific_audio_format(file_wav, 'wav')
#             if not is_valid:
#                 flash(f'WAV invalide : {error_message}', 'danger')
#                 return _rerender('file_wav')

#         # 4b. Vérifier cohérence durée MP3/WAV (même beat)
#         if file_wav and file_wav.filename != '':
#             from utils.file_validator import validate_audio_duration_match
#             is_valid, error_message = validate_audio_duration_match(file_mp3, file_wav)
#             if not is_valid:
#                 flash(f'{error_message}', 'danger')
#                 return _rerender('file_wav')

#         # 5. Valider le STEMS s'il est fourni (archive ZIP/RAR avec seulement des FLAC)
#         if file_stems and file_stems.filename != '' and current_user.is_premium:
#             # Validation déjà vérifiée disponible (abort 500 si non dispo)
#             from utils.file_validator import validate_stems_archive
#             is_valid, error_message = validate_stems_archive(file_stems)
#             if not is_valid:
#                 flash(f'Archive stems invalide : {error_message}', 'danger')
#                 return _rerender('file_stems')

#         # 5b. Valider l'image AVANT toute sauvegarde de fichier sur disque
#         if file_image and file_image.filename != '':
#             from utils.file_validator import validate_image_file
#             is_valid, error_message = validate_image_file(file_image)
#             if not is_valid:
#                 flash(f'Image non valide : {error_message}', 'danger')
#                 current_app.logger.warning(f'Image invalide : {error_message}')
#                 return _rerender('file_image')

#         # Générer des noms de fichiers uniques
#         unique_id = str(uuid.uuid4())[:8]

#         #  SÉCURITÉ: Validation renforcée du nom de fichier (Path Traversal protection)
#         try:
#             from utils.file_validator import FileValidator
#             safe_title = secure_filename(title)[:30]
#             safe_title = FileValidator.validate_filename(safe_title)
#         except ValueError as e:
#             flash(f'Nom de track invalide : {str(e)}', 'danger')
#             current_app.logger.warning(f'Nom de track invalide : {str(e)}')
#             return redirect(url_for('tracks.add_track'))

#         # Créer le dossier upload si nécessaire
#         config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        
#         # ============================================
#         # TRAITEMENT MP3
#         # ============================================
        
#         # Sauvegarder le MP3 complet
#         mp3_filename = f"{safe_title}_{unique_id}_full.mp3"
#         mp3_disk_path = config.UPLOAD_FOLDER / mp3_filename
#         file_mp3.save(mp3_disk_path)

#         # Créer le preview watermarké
#         preview_filename = f"{safe_title}_{unique_id}_preview.mp3"
#         preview_disk_path = config.UPLOAD_FOLDER / preview_filename
        
#         if WATERMARK_AVAILABLE:
#             try:
#                 watermark_path = Path(current_app.root_path) / 'static' / 'audio' / 'watermark.mp3'
#                 apply_watermark_and_trim(
#                     input_path=str(mp3_disk_path),
#                     output_path=str(preview_disk_path),
#                     watermark_path=str(watermark_path),
#                     preview_duration=90,
#                     watermark_positions=[20, 45]
#                 )
#             except Exception as e:
#                 current_app.logger.error(f"Erreur lors du watermark: {e}", exc_info=True)
#                 shutil.copy(mp3_disk_path, preview_disk_path)
#         else:
#             shutil.copy(mp3_disk_path, preview_disk_path)
        
#         # ============================================
#         # TRAITEMENT WAV (optionnel)
#         # ============================================

#         wav_filename = None
#         wav_disk_path = None
#         if file_wav and file_wav.filename != '':
#             wav_filename = f"{safe_title}_{unique_id}_full.wav"
#             wav_disk_path = config.UPLOAD_FOLDER / wav_filename
#             file_wav.save(wav_disk_path)
        
#         # ============================================
#         # TRAITEMENT STEMS (optionnel)
#         # ============================================

#         stems_filename = None
#         stems_disk_path = None
#         if file_stems and file_stems.filename != '':
#             stems_filename = f"{safe_title}_{unique_id}_stems.zip"
#             stems_disk_path = config.UPLOAD_FOLDER / stems_filename
#             file_stems.save(stems_disk_path)
        
#         # =========================================================
#         # GÉNÉRATION IMAGE ET TRAITEMENT SI FOURNIE PAR L'UTILISATEUR
#         # ==========================================================
#         if file_image and file_image.filename !='': 

#             from utils.file_validator import validate_image_file
#             original_filename = secure_filename(file_image.filename)
#             extension = Path(original_filename).suffix.lower()
#             is_valid, error_message = validate_image_file(file_image)
#             if not is_valid:
#                 flash(f'Image non valide : {error_message}', 'danger')
#                 current_app.logger.warning(f'Image invalide : {error_message}')
#                 return _rerender('file_image')

#             image_filename = f"{safe_title}_{unique_id}{extension}"
        
#             tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
#             tracks_img_folder.mkdir(parents=True, exist_ok=True)

#             image_disk_path = tracks_img_folder / image_filename

#             try:
#                 file_image.save(image_disk_path)
#             except Exception as e:
#                 current_app.logger.error(f"Erreur à la sauvegarde de l'image: {e}", exc_info=True)
#                 image_filename = 'default_track.png'

#         # ==================================================
#         # IMAGE NON FOURNIE PAR L'UTILISATEUR
#         # ==================================================
#         else:
#             image_filename = f"{safe_title}_{unique_id}.png"

#             # Créer le dossier si nécessaire
#             tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
#             tracks_img_folder.mkdir(parents=True, exist_ok=True)

#             image_disk_path = tracks_img_folder / image_filename

#             try:
#                 generate_track_image(title=title, scale=key, output_path=image_disk_path)
#             except Exception as e:
#                 current_app.logger.error(f"Erreur génération image: {e}", exc_info=True)
#                 image_filename = 'default_track.png'


#         # ============================================
#         # TRAITEMENT DES TAGS
#         # ============================================
        
#         tag_ids_str = request.form.get('tag_ids', '')
#         selected_tags = []
        
#         if tag_ids_str:
#             tag_ids = [int(tid) for tid in tag_ids_str.split(',') if tid.strip().isdigit()]
#             selected_tags = db.session.query(Tag).filter(Tag.id.in_(tag_ids)).all()
        
#         # ============================================
#         # CRÉER LE TRACK
#         # ============================================
        
#         track = Track(
#             title=title,
#             composer_id=current_user.id,
#             file_hash=file_hash,
#             audio_file=f'audio/{preview_filename}',
#             file_mp3=f'audio/{mp3_filename}',
#             file_wav=f'audio/{wav_filename}' if wav_filename else None,
#             file_stems=f'audio/{stems_filename}' if stems_filename else None,
#             image_file=f'images/tracks/{image_filename}',
#             bpm=int(bpm),
#             key=key,
#             style=style if style else None,
#             price_mp3=price_mp3,
#             price_wav=price_wav,
#             price_stems=price_stems,
#             sacem_percentage_composer=sacem_percentage_composer,
#             #CHANGE IN V2 PROD TO FALSE
#             is_approved=True
#         )
        
#         track.tags = selected_tags

#         db.session.add(track)
#         current_user.consume_upload_token()
#         try:
#             db.session.commit()
#             flash(f'Track "{title}" ajouté avec succès ! SACEM: {sacem_percentage_composer}% compositeur | {current_user.upload_track_tokens} token(s) restant(s)', 'success')
#             return redirect(url_for('main.profile', username=current_user.username))

#         except Exception as e:
#             db.session.rollback()
#             if mp3_disk_path and mp3_disk_path.exists():
#                 mp3_disk_path.unlink()

#             if wav_disk_path and wav_disk_path.exists():
#                 wav_disk_path.unlink()

#             if stems_disk_path and stems_disk_path.exists():
#                 stems_disk_path.unlink()

#             if image_disk_path and image_disk_path.exists():
#                 image_disk_path.unlink()

#             flash(f'Erreur lors de la sauvegarde du track: {str(e)}', 'error')
#             current_app.logger.error(f"Erreur à la sauvegarde du track: {e}", exc_info=True)
#             return redirect(url_for('tracks.add_track'))
    
#     categories = db.session.query(Category).all()
#     return render_template('add_track.html', categories=categories)





# ============================================
# ROUTE 3 : ÉDITER UN TRACK
# ============================================

@tracks_bp.route('/track/<int:track_id>/edit', methods=['GET', 'POST'])
@login_required
@requires_ownership(TrackOwnership)
def edit_track(track_id, track=None):
    """Éditer un track avec sélection de tags"""

    if request.method == 'POST':
        track.title = request.form.get('title')
        track.bpm = int(request.form.get('bpm'))
        track.key = request.form.get('key')
        track.style = request.form.get('style')
        track.price_mp3 = float(request.form.get('price_mp3'))
        track.price_wav = float(request.form.get('price_wav'))
        if track.file_stems and request.form.get('price_stems'):
            track.price_stems = float(request.form.get('price_stems'))

        # Traiter les tags sélectionnés
        tag_ids_str = request.form.get('tag_ids', '')
        if tag_ids_str:
            selected_tag_ids = [int(id.strip()) for id in tag_ids_str.split(',') if id.strip()]
            tags = db.session.query(Tag).filter(Tag.id.in_(selected_tag_ids)).all()
            track.tags = tags
        else:
            track.tags = []
        
        try:
            db.session.commit()
            flash('Track mis à jour avec succès!', 'success')
            return redirect(url_for('main.profile', username=current_user.username))
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Erreur lors de l'édition d'un beat: {e}", exc_info=True)
            flash(f'Erreur lors de la mise à jour: {str(e)}', 'danger')
    
    # GET : afficher le formulaire
    existing_tags = [
        {
            'id': tag.id,
            'name': tag.name,
            'category': tag.category_obj.name if tag.category_obj else 'other'
        }
        for tag in track.tags
    ]
    
    return render_template('edit_track.html', track=track, existing_tags=existing_tags)

# ============================================
# ROUTE 4: SUPPRIMER UN TRACK
# ============================================

@tracks_bp.route('/track/<int:track_id>/delete', methods=['POST'])
@login_required
@requires_ownership(TrackOwnership)
def delete_track(track_id, track=None):
    """Supprimer un track et ses fichiers associés"""

    # IMPORTANT : Vérifier si le track a déjà été acheté
    from models import Purchase
    purchase_count = db.session.query(Purchase).filter_by(track_id=track.id).count()

    if purchase_count > 0:
        flash(
            f'Impossible de supprimer ce track : il a déjà été acheté {purchase_count} fois. '
            f'Les acheteurs doivent pouvoir accéder à leurs fichiers et contrats.',
            'danger'
        )
        return redirect(url_for('main.track_detail', track_id=track.id))

    # Sauvegarder le titre pour le message
    title = track.title

    try:
        # Supprimer les fichiers audio du disque
        if track.file_mp3:
            mp3_path = config.UPLOAD_FOLDER / track.file_mp3
            if mp3_path.exists():
                mp3_path.unlink()

        if track.preview_file:
            preview_path = config.UPLOAD_FOLDER / track.preview_file
            if preview_path.exists():
                preview_path.unlink()

        if track.file_wav:
            wav_path = config.UPLOAD_FOLDER / track.file_wav
            if wav_path.exists():
                wav_path.unlink()

        if track.file_stems:
            stems_path = config.UPLOAD_FOLDER / track.file_stems
            if stems_path.exists():
                stems_path.unlink()

        # Supprimer l'image (sauf l'image par défaut)
        if track.image_filename and track.image_filename != 'default_track.png':
            image_path = config.IMAGES_FOLDER / 'tracks' / track.image_filename
            if image_path.exists():
                image_path.unlink()

        # Supprimer le track de la base de données
        db.session.delete(track)
        db.session.commit()

        flash(f' Track "{title}" supprimé avec succès !', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur lors de la suppression d'un beat: {e}", exc_info=True)
        flash(f' Erreur lors de la suppression : {str(e)}', 'danger')

    return redirect(url_for('main.profile', username=current_user.username))