"""
Blueprint MAIN API - Routes JSON pour le frontend Angular
Profile, Edit-profile, Notifications, Contact
"""
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, verify_jwt_in_request, get_jwt_identity, get_jwt
from werkzeug.utils import secure_filename
from email_validator import validate_email, EmailNotValidError
from sqlalchemy.orm import selectinload

import config
from extensions import db, csrf
from models import User, Notification, Track, PriceChangeRequest, TokenBlocklist
from serializers import ok, err, track_card as ser_track_card, capabilities_dict
from helpers import sanitize_html, revoke_all_refresh_tokens
from utils import email_service, notification_service
from utils.file_validator import validate_image_file
from utils.image_variants import generate_variants, delete_variants
from utils.auth_helpers import require_user

main_api_bp = Blueprint('main_api', __name__, url_prefix='/api/main')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile_payload(user, tracks, is_own=False):
    data = {
        'id':            user.id,
        'username':      user.username,
        'profile_image': user.profile_picture_url or user.profile_image,
        'bio':           user.bio,
        'instagram':     user.instagram,
        'twitter':       user.twitter,
        'youtube':       user.youtube,
        'soundcloud':    user.soundcloud,
        'signature':     user.signature,
        'roles': {
            'is_admin':                       user.is_admin,
            'is_artist':                      user.is_artist,
            'is_beatmaker':                   user.is_beatmaker,
            'is_mix_engineer':                user.is_mix_engineer,
            'is_mixmaster_engineer':          user.is_mixmaster_engineer,
            'is_certified_producer_arranger': getattr(user, 'is_certified_producer_arranger', False),
        },
        'created_at': user.created_at.isoformat(),
        'tracks': [{**ser_track_card(t), 'purchase_count': t.purchase_count} for t in tracks],
    }
    if is_own:
        data['email'] = user.email
        data['oauth_provider'] = getattr(user, 'oauth_provider', None)
        data['has_password']   = bool(user.password_hash)
        data['mixmaster'] = {
            'reference_price':  user.mixmaster_reference_price,
            'price_min':        user.mixmaster_price_min,
            'bio':              user.mixmaster_bio,
            'sample_submitted': user.mixmaster_sample_submitted,
        }
        data['is_certified_producer_arranger']      = getattr(user, 'is_certified_producer_arranger', False)
        data['producer_arranger_request_submitted'] = getattr(user, 'producer_arranger_request_submitted', False)
        data['is_certified_master_engineer']        = getattr(user, 'is_certified_master_engineer', False)
        data['master_sample_submitted']             = getattr(user, 'master_sample_submitted', False)
        data['subscription_plan']                   = user.plan
        # Capacités calculées côté serveur : le front les lit, il ne les redérive
        # pas. Une règle d'autorisation dupliquée dans Angular finit toujours par
        # se désynchroniser de celle qui protège réellement l'API.
        data['capabilities'] = capabilities_dict(user)
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
        return err('Utilisateur introuvable.', status=404)

    is_own = bool(current_user_id and current_user_id == user.id)

    tracks_q = (
        db.session.query(Track)
        .options(selectinload(Track.tags))
        .filter_by(composer_id=user.id)
    )
    if not is_own:
        tracks_q = tracks_q.filter_by(is_approved=True)
    tracks = tracks_q.order_by(Track.created_at.desc()).all()

    return ok({'user': _profile_payload(user, tracks, is_own=is_own)})


# ── PUT /users/edit-profile ───────────────────────────────────────────────────

@main_api_bp.route('/users/edit-profile', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_user
def edit_profile(current_user):
    """Mettre à jour les infos générales du profil (bio, réseaux, rôles, photo)"""
    is_mp = bool(request.content_type and 'multipart/form-data' in request.content_type)

    def _f(key, default=''):
        return (request.form if is_mp else (request.json or {})).get(key, default)

    def _bool(key):
        val = _f(key)
        return val in (True, 'true', '1', 'on')

    bio             = sanitize_html(_f('bio').strip())
    instagram       = _f('instagram').strip()
    twitter         = _f('twitter').strip()
    youtube         = _f('youtube').strip()
    soundcloud      = _f('soundcloud').strip()
    signature       = _f('signature').strip()
    is_artist       = _bool('is_artist')
    is_beatmaker    = _bool('is_beatmaker')
    is_mix_engineer = _bool('is_mix_engineer')
    is_producer     = _bool('is_producer')

    newly_mix_engineer = is_mix_engineer and not current_user.is_mix_engineer

    current_user.bio             = bio or None
    current_user.instagram       = instagram or None
    current_user.twitter         = twitter or None
    current_user.youtube         = youtube or None
    current_user.soundcloud      = soundcloud or None
    current_user.signature       = signature or None
    current_user.is_artist       = is_artist
    current_user.is_beatmaker    = is_beatmaker
    current_user.is_mix_engineer = is_mix_engineer
    current_user.is_producer     = is_producer

    # ── Certification Producteur/Arrangeur ────────────────────────────────────
    if current_user.is_mixmaster_engineer:
        req_pa = _bool('request_producer_arranger')
        if (req_pa
                and not getattr(current_user, 'is_certified_producer_arranger', False)
                and not getattr(current_user, 'producer_arranger_request_submitted', False)):
            current_user.producer_arranger_request_submitted = True

    # ── Changement de prix (engineer certifié) ────────────────────────────────
    if current_user.is_mixmaster_engineer:
        ref_price_raw = _f('mixmaster_reference_price').strip()
        min_price_raw = _f('mixmaster_price_min').strip()

        if ref_price_raw or min_price_raw:
            try:
                if not (ref_price_raw and min_price_raw):
                    return err('Fournissez les deux prix (référence et minimum).', status=422)

                reference_price = round(float(ref_price_raw))
                price_min       = round(float(min_price_raw))

                if not (10 <= reference_price <= 500):
                    return err('Prix de référence invalide (10€–500€).', status=422)

                min_required = round(reference_price * 0.35)
                max_allowed  = round(reference_price * 0.80)

                if not (min_required <= price_min <= max_allowed):
                    return err(f'Prix minimum invalide ({min_required}€–{max_allowed}€).', status=422)

                if reference_price != current_user.mixmaster_reference_price or price_min != current_user.mixmaster_price_min:
                    if current_user.mixmaster_reference_price is None or current_user.mixmaster_price_min is None:
                        current_user.mixmaster_reference_price = reference_price
                        current_user.mixmaster_price_min       = price_min
                    else:
                        db.session.add(PriceChangeRequest(
                            engineer_id=current_user.id,
                            old_reference_price=current_user.mixmaster_reference_price,
                            old_price_min=current_user.mixmaster_price_min,
                            new_reference_price=reference_price,
                            new_price_min=price_min,
                            status='pending',
                        ))
            except (ValueError, TypeError):
                return err('Prix invalides.', status=422)

    # ── Image de profil ───────────────────────────────────────────────────────
    picture = request.files.get('profile_picture') if is_mp else None
    if picture and picture.filename:
        is_valid, err_msg = validate_image_file(picture)
        if not is_valid:
            return err(f'Image invalide : {err_msg}', status=422)

        ext = Path(secure_filename(picture.filename)).suffix.lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            ext = '.jpg'

        filename = f"user_{current_user.id}_{uuid.uuid4().hex[:12]}{ext}"
        config.PROFILES_FOLDER.mkdir(parents=True, exist_ok=True)

        old = current_user.profile_image
        if old and old != 'images/default_profile.png' and old.startswith('images/profiles/'):
            old_path = config.IMAGES_FOLDER.parent / old
            if old_path.exists():
                try:
                    old_path.unlink()
                except OSError:
                    pass
            delete_variants(old_path)

        picture.seek(0)
        picture.save(str(config.PROFILES_FOLDER / filename))
        generate_variants(config.PROFILES_FOLDER / filename)
        current_user.profile_image       = f"images/profiles/{filename}"
        current_user.profile_picture_url = None

    if newly_mix_engineer:
        notification_service.notify_mix_sample_pending(current_user.id)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'edit_profile error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    if newly_mix_engineer:
        try:
            email_service.send_mix_sample_pending_email(current_user)
        except Exception as e:
            current_app.logger.error(f"Erreur email mix_sample_pending user #{current_user.id}: {e}")

    next_step = 'submit-sample' if newly_mix_engineer and not current_user.mixmaster_sample_submitted else None

    return ok({
        'user': {
            'id':            current_user.id,
            'username':      current_user.username,
            'profile_image': current_user.profile_picture_url or current_user.profile_image,
            'bio':           current_user.bio,
            'instagram':     current_user.instagram,
            'twitter':       current_user.twitter,
            'youtube':       current_user.youtube,
            'soundcloud':    current_user.soundcloud,
            'signature':     current_user.signature,
            'roles': {
                'is_admin':                       current_user.is_admin,
                'is_artist':                      current_user.is_artist,
                'is_beatmaker':                   current_user.is_beatmaker,
                'is_mix_engineer':                current_user.is_mix_engineer,
                'is_mixmaster_engineer':          current_user.is_mixmaster_engineer,
                'is_certified_producer_arranger': getattr(current_user, 'is_certified_producer_arranger', False),
                'mixmaster_sample_submitted':     current_user.mixmaster_sample_submitted,
            },
        },
        'next': next_step,
    }, message='Profil mis à jour avec succès.')


# ── PUT /users/edit-profile/security ─────────────────────────────────────────

@main_api_bp.route('/users/edit-profile/security', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_user
def edit_profile_security(current_user):
    """Modifier username, mot de passe ou email"""
    data = request.json or {}

    # ── Cas OAuth : définir un premier mot de passe ──────────────────────────
    set_password         = data.get('set_password', '')
    set_password_confirm = data.get('set_password_confirm', '')

    if set_password and getattr(current_user, 'oauth_provider', None) and not current_user.password_hash:
        if len(set_password) < 9:
            return err('Mot de passe trop court (minimum 9 caractères).', status=422)
        if set_password != set_password_confirm:
            return err('Les mots de passe ne correspondent pas.', status=422)
        if not all([re.search(r'[a-z]', set_password),
                    re.search(r'[A-Z]', set_password),
                    re.search(r'[0-9]', set_password)]):
            return err('Le mot de passe doit contenir au moins une minuscule, une majuscule et un chiffre.', status=422)
        current_user.set_password(set_password)
        db.session.commit()
        notification_service.send_notification(
            user_id=current_user.id,
            title='Mot de passe défini',
            message='Un mot de passe a été défini pour votre compte.',
            type='system',
        )
        return ok({'has_password': True}, message='Mot de passe défini avec succès.')

    if getattr(current_user, 'oauth_provider', None) and not current_user.password_hash:
        return err("Vous devez d'abord définir un mot de passe.", level='warning', status=403)

    current_password = data.get('current_password', '')
    if not current_user.check_password(current_password):
        return err('Mot de passe actuel incorrect.', status=401)

    has_changes = False
    messages    = []

    # ── Username ──────────────────────────────────────────────────────────────
    new_username = data.get('new_username', '').strip()
    if new_username and new_username != current_user.username:
        if len(new_username) < 3 or len(new_username) > 20:
            return err("Nom d'utilisateur : 3–20 caractères requis.", status=422)
        if not re.match(r'^[\w]+$', new_username):
            return err("Nom d'utilisateur : lettres, chiffres et underscore uniquement.", status=422)
        if db.session.query(User).filter_by(username=new_username).first():
            return err("Ce nom d'utilisateur est déjà pris.", status=409)
        current_user.username = new_username
        has_changes           = True
        messages.append("Nom d'utilisateur mis à jour.")

    # ── Mot de passe ──────────────────────────────────────────────────────────
    new_password         = data.get('new_password', '')
    new_password_confirm = data.get('new_password_confirm', '')
    if new_password:
        if len(new_password) < 9:
            return err('Nouveau mot de passe trop court (minimum 9 caractères).', status=422)
        if new_password != new_password_confirm:
            return err('Les nouveaux mots de passe ne correspondent pas.', status=422)
        if not all([re.search(r'[a-z]', new_password),
                    re.search(r'[A-Z]', new_password),
                    re.search(r'[0-9]', new_password)]):
            return err('Le mot de passe doit contenir minuscule, majuscule et chiffre.', status=422)
        current_user.set_password(new_password)
        has_changes = True
        messages.append('Mot de passe mis à jour.')

    # ── Email ─────────────────────────────────────────────────────────────────
    new_email = data.get('new_email', '').strip()
    if new_email and new_email.lower() != current_user.email.lower():
        try:
            new_email = validate_email(new_email).email
        except EmailNotValidError:
            return err('Adresse email invalide.', status=422)
        if db.session.query(User).filter_by(email=new_email).first():
            return err('Cet email est déjà utilisé par un autre compte.', status=409)
        email_service.send_email_change_verification_email(user=current_user, new_email=new_email)
        has_changes = True
        messages.append('Email : un lien de vérification a été envoyé à la nouvelle adresse.')

    if has_changes:
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'edit_profile_security error: {e}', exc_info=True)
            return err('Erreur serveur.', status=500)

    return ok({'username': current_user.username},
              message=' '.join(messages) or 'Aucune modification détectée.')


# ── DELETE /users/me ──────────────────────────────────────────────────────────

@main_api_bp.route('/users/me', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_user
def delete_own_account(current_user):
    """
    Suppression RGPD self-service (miroir de admin_api.delete_user, mais déclenchée
    par l'utilisateur lui-même). Compte immédiatement bloqué (pending_deletion),
    anonymisation complète par le job nuit après 30 jours (voir utils/gdpr_purge.py).
    """
    data = request.json or {}

    if current_user.account_status == 'pending_deletion':
        return err('Votre compte est déjà en attente de suppression.', status=409)

    # Compte OAuth sans mot de passe local : rien à vérifier, le JWT valide suffit.
    if current_user.password_hash:
        current_password = data.get('current_password', '')
        if not current_user.check_password(current_password):
            return err('Mot de passe incorrect.', status=401)

    current_user.account_status = 'pending_deletion'
    current_user.deleted_at     = datetime.now(timezone.utc)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'delete_own_account error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    # Révoque la session courante — même mécanisme que /api/auth/logout.
    jwt_data = get_jwt()
    jti      = jwt_data.get('jti') if jwt_data else None
    if jti:
        try:
            db.session.add(TokenBlocklist(jti=jti, created_at=datetime.utcnow()))
            db.session.commit()
            revoke_all_refresh_tokens(current_user.id)
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f'delete_own_account blocklist error: {e}')

    current_app.logger.info(
        f'Utilisateur #{current_user.id} ({current_user.username}) a demandé la suppression de son compte.'
    )
    return ok(message='Votre compte a été désactivé. Vos données seront anonymisées sous 30 jours.', level='info')


# ── GET /notifications ────────────────────────────────────────────────────────

@main_api_bp.route('/notifications', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_notifications(current_user):
    """Notifications non lues de l'utilisateur courant"""
    try:
        notifs = (
            db.session.query(Notification)
            .filter_by(user_id=current_user.id, is_read=False)
            .order_by(Notification.created_at.desc())
            .all()
        )
    except Exception as e:
        current_app.logger.error(f'get_notifications error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    return ok({
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
        ],
    })


# ── POST /notifications/<id>/read ─────────────────────────────────────────────

@main_api_bp.route('/notifications/<int:notif_id>/read', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def mark_notification_read(notif_id, current_user):
    """Marquer une notification comme lue et renvoyer son lien"""
    notif = db.session.get(Notification, notif_id)

    if not notif:
        return err('Notification introuvable.', status=404)
    if notif.user_id != current_user.id:
        return err('Accès refusé.', status=403)

    notif.mark_as_read()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'mark_notification_read error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    return ok({'link': notif.link}, message='Notification lue.', level='info')


# ── POST /notifications/mark-all-read ────────────────────────────────────────

@main_api_bp.route('/notifications/mark-all-read', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def mark_all_notifications_read(current_user):
    """Marquer toutes les notifications comme lues"""
    try:
        notification_service.mark_all_as_read(current_user.id)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'mark_all_notifications_read error: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)

    return ok(message='Toutes les notifications ont été marquées comme lues.')


# ── POST /contact ─────────────────────────────────────────────────────────────

@main_api_bp.route('/contact', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def contact(current_user):
    """Envoyer un message au support (JWT requis)"""
    data    = request.json or {}
    subject = data.get('subject', '').strip()
    message = data.get('message', '').strip()
    ref     = data.get('ref', '').strip()

    if not subject or not message:
        return err('Sujet et message sont requis.', status=422)

    sent = email_service.send_contact_support_email(
        user=current_user, subject=subject, message=message, ref=ref,
    )
    if sent:
        return ok(message='Message envoyé. Vous recevrez une confirmation par email.')

    return err("Erreur lors de l'envoi. Réessayez ou écrivez à contact@laprod.net.", status=500)


# ── PATCH /users/preferences ──────────────────────────────────────────────────

@main_api_bp.route('/users/preferences', methods=['PATCH'])
@jwt_required()
@csrf.exempt
@require_user
def update_preferences(current_user):
    """Mettre à jour les préférences d'affichage de l'utilisateur."""
    data = request.get_json() or {}

    if 'preferred_tag_category' in data:
        value = data['preferred_tag_category']
        if value is not None and not isinstance(value, str):
            return err('Valeur invalide.', level='warning')
        if value and len(value) > 50:
            return err('Valeur trop longue.', level='warning')
        current_user.preferred_tag_category = value

    db.session.commit()
    return ok({'preferred_tag_category': current_user.preferred_tag_category})
