"""
Blueprint MAIN API - Routes JSON pour le frontend Angular
Profile, Edit-profile, Notifications, Contact
"""
import re
import uuid
from pathlib import Path

from flask import Blueprint, request, current_app, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from werkzeug.utils import secure_filename
from email_validator import validate_email, EmailNotValidError
from sqlalchemy.orm import selectinload

import config
from extensions import db, csrf
from models import User, Notification, Track, PriceChangeRequest
from helpers import sanitize_html
from utils import email_service, notification_service
from utils.file_validator import validate_image_file

main_api_bp = Blueprint('main_api', __name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _track_payload(track):
    return {
        'id':            track.id,
        'title':         track.title,
        'bpm':           track.bpm,
        'key':           track.key,
        'style':         track.style,
        'image_file':    track.image_file,
        'audio_file':    track.audio_file,
        'price_mp3':     track.price_mp3,
        'price_wav':     track.price_wav,
        'price_stems':   track.price_stems,
        'is_approved':   track.is_approved,
        'purchase_count': track.purchase_count,
        'created_at':    track.created_at.isoformat(),
        'tags': [
            {'id': t.id, 'name': t.name,
             'category': t.category_obj.name if t.category_obj else None}
            for t in track.tags
        ],
    }


def _profile_payload(user, tracks, is_own=False):
    data = {
        'id':           user.id,
        'username':     user.username,
        'profile_image': user.profile_image,
        'bio':          user.bio,
        'instagram':    user.instagram,
        'twitter':      user.twitter,
        'youtube':      user.youtube,
        'soundcloud':   user.soundcloud,
        'signature':    user.signature,
        'roles': {
            'is_artist':             user.is_artist,
            'is_beatmaker':          user.is_beatmaker,
            'is_mix_engineer':       user.is_mix_engineer,
            'is_mixmaster_engineer': user.is_mixmaster_engineer,
        },
        'created_at': user.created_at.isoformat(),
        'tracks':     [_track_payload(t) for t in tracks],
    }
    if is_own:
        data['email'] = user.email
        data['oauth_provider'] = getattr(user, 'oauth_provider', None)
        data['has_password']   = bool(user.password_hash)
        data['mixmaster'] = {
            'reference_price':    user.mixmaster_reference_price,
            'price_min':          user.mixmaster_price_min,
            'bio':                user.mixmaster_bio,
            'sample_submitted':   user.mixmaster_sample_submitted,
        }
        data['is_certified_producer_arranger']    = getattr(user, 'is_certified_producer_arranger', False)
        data['producer_arranger_request_submitted'] = getattr(user, 'producer_arranger_request_submitted', False)
    return data


# ── GET /users/<username> ─────────────────────────────────────────────────────

@main_api_bp.route('/users/<username>', methods=['GET'])
@csrf.exempt
def get_profile(username):
    """Profil public d'un utilisateur (JWT optionnel pour le profil propre)"""

    current_user_id = None
    try:
        verify_jwt_in_request(optional=True)
        raw = get_jwt_identity()
        current_user_id = int(raw) if raw else None
    except Exception:
        pass

    user = db.session.query(User).filter_by(username=username).first()
    if not user:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Utilisateur introuvable.'}}), 404

    is_own = bool(current_user_id and current_user_id == user.id)

    tracks_q = (
        db.session.query(Track)
        .options(selectinload(Track.tags))
        .filter_by(composer_id=user.id)
    )
    if not is_own:
        tracks_q = tracks_q.filter_by(is_approved=True)
    tracks = tracks_q.order_by(Track.created_at.desc()).all()

    return jsonify({
        'success': True,
        'data': {'user': _profile_payload(user, tracks, is_own=is_own)},
    }), 200


# ── PUT /users/edit-profile ───────────────────────────────────────────────────

@main_api_bp.route('/users/edit-profile', methods=['PUT'])
@jwt_required()
@csrf.exempt
def edit_profile():
    """Mettre à jour les infos générales du profil (bio, réseaux, rôles, photo)"""

    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Utilisateur introuvable.'}}), 404

    # Accepte multipart/form-data (photo) ou JSON
    is_mp = bool(request.content_type and 'multipart/form-data' in request.content_type)

    def _f(key, default=''):
        return (request.form if is_mp else (request.json or {})).get(key, default)

    def _bool(key):
        val = _f(key)
        return val in (True, 'true', '1', 'on')

    bio              = sanitize_html(_f('bio').strip())
    instagram        = _f('instagram').strip()
    twitter          = _f('twitter').strip()
    youtube          = _f('youtube').strip()
    soundcloud       = _f('soundcloud').strip()
    signature        = _f('signature').strip()
    is_artist        = _bool('is_artist')
    is_beatmaker     = _bool('is_beatmaker')
    is_mix_engineer  = _bool('is_mix_engineer')

    newly_mix_engineer = is_mix_engineer and not user.is_mix_engineer

    user.bio            = bio or None
    user.instagram      = instagram or None
    user.twitter        = twitter or None
    user.youtube        = youtube or None
    user.soundcloud     = soundcloud or None
    user.signature      = signature or None
    user.is_artist      = is_artist
    user.is_beatmaker   = is_beatmaker
    user.is_mix_engineer = is_mix_engineer

    # ── Certification Producteur/Arrangeur ────────────────────────────────────
    if user.is_mixmaster_engineer:
        req_pa = _bool('request_producer_arranger')
        if (req_pa
                and not getattr(user, 'is_certified_producer_arranger', False)
                and not getattr(user, 'producer_arranger_request_submitted', False)):
            user.producer_arranger_request_submitted = True

    # ── Changement de prix (engineer certifié) ────────────────────────────────
    if user.is_mixmaster_engineer:
        ref_price_raw = _f('mixmaster_reference_price').strip()
        min_price_raw = _f('mixmaster_price_min').strip()

        if ref_price_raw or min_price_raw:
            try:
                if not (ref_price_raw and min_price_raw):
                    return jsonify({'success': False,
                                    'feedback': {'level': 'error',
                                                 'message': 'Fournissez les deux prix (référence et minimum).'}}), 422

                reference_price = round(float(ref_price_raw))
                price_min       = round(float(min_price_raw))

                if not (10 <= reference_price <= 500):
                    return jsonify({'success': False,
                                    'feedback': {'level': 'error',
                                                 'message': 'Prix de référence invalide (10€–500€).'}}), 422

                min_required = round(reference_price * 0.35)
                max_allowed  = round(reference_price * 0.65)

                if not (min_required <= price_min <= max_allowed):
                    return jsonify({'success': False,
                                    'feedback': {'level': 'error',
                                                 'message': f'Prix minimum invalide ({min_required}€–{max_allowed}€).'}}), 422

                if reference_price != user.mixmaster_reference_price or price_min != user.mixmaster_price_min:
                    if user.mixmaster_reference_price is None or user.mixmaster_price_min is None:
                        user.mixmaster_reference_price = reference_price
                        user.mixmaster_price_min       = price_min
                    else:
                        db.session.add(PriceChangeRequest(
                            engineer_id=user.id,
                            old_reference_price=user.mixmaster_reference_price,
                            old_price_min=user.mixmaster_price_min,
                            new_reference_price=reference_price,
                            new_price_min=price_min,
                            status='pending',
                        ))
            except (ValueError, TypeError):
                return jsonify({'success': False,
                                'feedback': {'level': 'error', 'message': 'Prix invalides.'}}), 422

    # ── Image de profil ───────────────────────────────────────────────────────
    picture = request.files.get('profile_picture') if is_mp else None
    if picture and picture.filename:
        is_valid, err_msg = validate_image_file(picture)
        if not is_valid:
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': f'Image invalide : {err_msg}'}}), 422

        ext = Path(secure_filename(picture.filename)).suffix.lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            ext = '.jpg'

        filename = f"user_{user.id}_{uuid.uuid4().hex[:12]}{ext}"
        config.PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)

        old = user.profile_image
        if old and old != 'images/default_profile.png' and old.startswith('images/profiles/'):
            old_path = config.IMAGES_FOLDER.parent / old
            if old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    pass

        picture.seek(0)
        picture.save(str(config.PROFILES_FOLDER / filename))
        user.profile_image = f"images/profiles/{filename}"

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'edit_profile error: {e}', exc_info=True)
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    next_step = 'submit-sample' if newly_mix_engineer and not user.mixmaster_sample_submitted else None

    return jsonify({
        'success':  True,
        'feedback': {'level': 'success', 'message': 'Profil mis à jour avec succès.'},
        'data': {
            'user': {
                'id':            user.id,
                'username':      user.username,
                'profile_image': user.profile_image,
                'bio':           user.bio,
                'instagram':     user.instagram,
                'twitter':       user.twitter,
                'youtube':       user.youtube,
                'soundcloud':    user.soundcloud,
                'signature':     user.signature,
                'roles': {
                    'is_artist':             user.is_artist,
                    'is_beatmaker':          user.is_beatmaker,
                    'is_mix_engineer':       user.is_mix_engineer,
                    'is_mixmaster_engineer': user.is_mixmaster_engineer,
                },
            },
            'next': next_step,
        },
    }), 200


# ── PUT /users/edit-profile/security ─────────────────────────────────────────

@main_api_bp.route('/users/edit-profile/security', methods=['PUT'])
@jwt_required()
@csrf.exempt
def edit_profile_security():
    """Modifier username, mot de passe ou email"""

    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Utilisateur introuvable.'}}), 404

    data = request.json or {}

    # ── Cas OAuth : définir un premier mot de passe ──────────────────────────
    set_password = data.get('set_password', '')
    set_password_confirm = data.get('set_password_confirm', '')

    if set_password and getattr(user, 'oauth_provider', None) and not user.password_hash:
        if len(set_password) < 9:
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Mot de passe trop court (minimum 9 caractères).'}}), 422
        if set_password != set_password_confirm:
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Les mots de passe ne correspondent pas.'}}), 422
        if not all([re.search(r'[a-z]', set_password),
                    re.search(r'[A-Z]', set_password),
                    re.search(r'[0-9]', set_password)]):
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Le mot de passe doit contenir au moins une minuscule, une majuscule et un chiffre.'}}), 422
        user.set_password(set_password)
        db.session.commit()
        notification_service.send_notification(
            user_id=user.id,
            title='Mot de passe défini',
            message='Un mot de passe a été défini pour votre compte.',
            type='system',
        )
        return jsonify({
            'success':  True,
            'feedback': {'level': 'success', 'message': 'Mot de passe défini avec succès.'},
            'data':     {'has_password': True},
        }), 200

    # ── Vérification du mot de passe actuel ──────────────────────────────────
    if getattr(user, 'oauth_provider', None) and not user.password_hash:
        return jsonify({'success': False,
                        'feedback': {'level': 'warning',
                                     'message': "Vous devez d'abord définir un mot de passe."}}), 403

    current_password = data.get('current_password', '')
    if not user.check_password(current_password):
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Mot de passe actuel incorrect.'}}), 401

    has_changes = False
    messages    = []

    # ── Username ──────────────────────────────────────────────────────────────
    new_username = data.get('new_username', '').strip()
    if new_username and new_username != user.username:
        if len(new_username) < 3 or len(new_username) > 20:
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': "Nom d'utilisateur : 3–20 caractères requis."}}), 422
        if not re.match(r'^[\w]+$', new_username):
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': "Nom d'utilisateur : lettres, chiffres et underscore uniquement."}}), 422
        if db.session.query(User).filter_by(username=new_username).first():
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': "Ce nom d'utilisateur est déjà pris."}}), 409
        user.username = new_username
        has_changes   = True
        messages.append("Nom d'utilisateur mis à jour.")

    # ── Mot de passe ──────────────────────────────────────────────────────────
    new_password         = data.get('new_password', '')
    new_password_confirm = data.get('new_password_confirm', '')
    if new_password:
        if len(new_password) < 9:
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Nouveau mot de passe trop court (minimum 9 caractères).'}}), 422
        if new_password != new_password_confirm:
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Les nouveaux mots de passe ne correspondent pas.'}}), 422
        if not all([re.search(r'[a-z]', new_password),
                    re.search(r'[A-Z]', new_password),
                    re.search(r'[0-9]', new_password)]):
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Le mot de passe doit contenir minuscule, majuscule et chiffre.'}}), 422
        user.set_password(new_password)
        has_changes = True
        messages.append('Mot de passe mis à jour.')

    # ── Email ─────────────────────────────────────────────────────────────────
    new_email = data.get('new_email', '').strip()
    if new_email and new_email.lower() != user.email.lower():
        try:
            new_email = validate_email(new_email).email
        except EmailNotValidError:
            return jsonify({'success': False,
                            'feedback': {'level': 'error', 'message': 'Adresse email invalide.'}}), 422
        if db.session.query(User).filter_by(email=new_email).first():
            return jsonify({'success': False,
                            'feedback': {'level': 'error',
                                         'message': 'Cet email est déjà utilisé par un autre compte.'}}), 409
        email_service.send_email_change_verification_email(user=user, new_email=new_email)
        has_changes = True
        messages.append('Email : un lien de vérification a été envoyé à la nouvelle adresse.')

    if has_changes:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'edit_profile_security error: {e}', exc_info=True)
            return jsonify({'success': False,
                            'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    return jsonify({
        'success':  True,
        'feedback': {'level': 'success', 'message': ' '.join(messages) or 'Aucune modification détectée.'},
        'data':     {'username': user.username},
    }), 200


# ── GET /notifications ────────────────────────────────────────────────────────

@main_api_bp.route('/notifications', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_notifications():
    """Notifications non lues de l'utilisateur courant"""
    user_id = int(get_jwt_identity())

    try:
        notifs = (
            db.session.query(Notification)
            .filter_by(user_id=user_id, is_read=False)
            .order_by(Notification.created_at.desc())
            .all()
        )
    except Exception as e:
        current_app.logger.error(f'get_notifications error: {e}', exc_info=True)
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    return jsonify({
        'success': True,
        'data': {
            'notifications': [
                {
                    'id':         n.id,
                    'type':       n.type,
                    'title':      n.title,
                    'message':    n.message,
                    'link':       n.link,
                    'is_read':    n.is_read,
                    'created_at': n.created_at.isoformat(),
                }
                for n in notifs
            ]
        },
    }), 200


# ── POST /notifications/<id>/read ─────────────────────────────────────────────

@main_api_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@jwt_required()
@csrf.exempt
def mark_notification_read(notif_id):
    """Marquer une notification comme lue et renvoyer son lien"""
    user_id = int(get_jwt_identity())
    notif   = db.session.get(Notification, notif_id)

    if not notif:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Notification introuvable.'}}), 404
    if notif.user_id != user_id:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Accès refusé.'}}), 403

    notif.mark_as_read()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'mark_notification_read error: {e}', exc_info=True)
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    return jsonify({
        'success':  True,
        'feedback': {'level': 'info', 'message': 'Notification lue.'},
        'data':     {'link': notif.link},
    }), 200


# ── POST /notifications/mark-all-read ────────────────────────────────────────

@main_api_bp.route('/notifications/mark-all-read', methods=['POST'])
@jwt_required()
@csrf.exempt
def mark_all_notifications_read():
    """Marquer toutes les notifications comme lues"""
    user_id = int(get_jwt_identity())

    try:
        notification_service.mark_all_as_read(user_id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'mark_all_notifications_read error: {e}', exc_info=True)
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500

    return jsonify({
        'success':  True,
        'feedback': {'level': 'success', 'message': 'Toutes les notifications ont été marquées comme lues.'},
    }), 200


# ── POST /contact ─────────────────────────────────────────────────────────────

@main_api_bp.route('/contact', methods=['POST'])
@jwt_required()
@csrf.exempt
def contact():
    """Envoyer un message au support (JWT requis)"""
    user_id = int(get_jwt_identity())
    user    = db.session.get(User, user_id)
    if not user:
        return jsonify({'success': False,
                        'feedback': {'level': 'error', 'message': 'Utilisateur introuvable.'}}), 404

    data    = request.json or {}
    subject = data.get('subject', '').strip()
    message = data.get('message', '').strip()
    ref     = data.get('ref', '').strip()

    if not subject or not message:
        return jsonify({'success': False,
                        'feedback': {'level': 'error',
                                     'message': 'Sujet et message sont requis.'}}), 422

    sent = email_service.send_contact_support_email(
        user=user, subject=subject, message=message, ref=ref,
    )
    if sent:
        return jsonify({
            'success':  True,
            'feedback': {'level': 'success',
                         'message': 'Message envoyé. Vous recevrez une confirmation par email.'},
        }), 200

    return jsonify({
        'success':  False,
        'feedback': {'level': 'error',
                     'message': "Erreur lors de l'envoi. Réessayez ou écrivez à contact@laprod.net."},
    }), 500
