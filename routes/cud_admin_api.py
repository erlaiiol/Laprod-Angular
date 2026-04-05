"""
Admin CUD API — Create/Update/Delete endpoints pour l'administration
"""
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from pathlib import Path
from sqlalchemy import select
import uuid
import config

from extensions import db, csrf
from models import Track, User, Tag, Category, MixMasterRequest, PriceChangeRequest, Contract
from helpers import generate_track_image
from utils import email_service, notification_service

cud_admin_api_bp = Blueprint('cud_admin_api', __name__, url_prefix='/admin-api')


def _require_admin():
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)
    if not user.is_admin:
        return None, (jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès réservé aux administrateurs.'}}), 403)
    return user, None


# ── Tracks ────────────────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/tracks/<int:track_id>/approve', methods=['POST'])
@jwt_required()
@csrf.exempt
def approve_track(track_id):
    _, err = _require_admin()
    if err:
        return err

    track = db.get_or_404(Track, track_id)
    track.is_approved = True
    track.approved_at = datetime.now()
    db.session.commit()

    try:
        email_service.send_track_approved_email(track)
    except Exception as e:
        current_app.logger.warning(f"Email approbation track: {e}")
    try:
        notification_service.send_track_approved_notification(track)
    except Exception as e:
        current_app.logger.warning(f"Notif approbation track: {e}")

    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Track "{track.title}" approuvé.'}})


@cud_admin_api_bp.route('/tracks/<int:track_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
def reject_track(track_id):
    _, err = _require_admin()
    if err:
        return err

    track = db.get_or_404(Track, track_id)
    title = track.title

    try:
        email_service.send_track_rejected_email(track)
    except Exception:
        pass
    try:
        notification_service.send_track_rejected_notification(track)
    except Exception:
        pass

    db.session.delete(track)
    db.session.commit()

    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Track "{title}" supprimé.'}})


@cud_admin_api_bp.route('/tracks/<int:track_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
def edit_track(track_id):
    _, err = _require_admin()
    if err:
        return err

    track = db.get_or_404(Track, track_id)

    # Champs textuels (JSON ou multipart)
    data = request.get_json(silent=True) or request.form

    if 'title' in data:
        track.title = data['title']
    if 'bpm' in data:
        track.bpm = int(data['bpm'])
    if 'key' in data:
        track.key = data['key']
    if 'style' in data:
        track.style = data['style']
    if 'price_mp3' in data:
        track.price_mp3 = float(data['price_mp3'])
    if 'price_wav' in data:
        track.price_wav = float(data['price_wav'])
    if 'price_stems' in data and data['price_stems']:
        track.price_stems = float(data['price_stems'])

    # Tags
    tag_ids_str = data.get('tag_ids', '')
    if tag_ids_str:
        selected_tag_ids = [int(i.strip()) for i in tag_ids_str.split(',') if i.strip()]
        track.tags = db.session.scalars(select(Tag).where(Tag.id.in_(selected_tag_ids))).all()
    elif 'tag_ids' in data:
        track.tags = []

    # Image (multipart seulement)
    file_image = request.files.get('file_image')
    if file_image and file_image.filename:
        from utils.file_validator import validate_image_file
        is_valid, error_message = validate_image_file(file_image)
        if is_valid:
            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            ext = Path(secure_filename(file_image.filename)).suffix.lower()
            safe_title = secure_filename(track.title)[:30]
            new_img_filename = f"{safe_title}_{uuid.uuid4().hex[:8]}{ext}"
            new_img_path = tracks_img_folder / new_img_filename
            if track.image_file:
                old_name = track.image_file.replace('images/tracks/', '')
                if old_name and old_name != 'default_track.png':
                    old_path = tracks_img_folder / old_name
                    if old_path.exists():
                        old_path.unlink()
            file_image.save(new_img_path)
            track.image_file = f'images/tracks/{new_img_filename}'
        else:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Image invalide : {error_message}'}}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': str(e)}}), 500

    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Track "{track.title}" mis à jour.'}})


# ── Users ─────────────────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@jwt_required()
@csrf.exempt
def toggle_user_status(user_id):
    current, err = _require_admin()
    if err:
        return err

    if current.id == user_id:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Vous ne pouvez pas vous désactiver.'}}), 400

    user = db.get_or_404(User, user_id)
    if user.account_status == 'active':
        user.account_status = 'deleted'
        msg = f'Utilisateur {user.username} désactivé.'
    else:
        user.account_status = 'active'
        msg = f'Utilisateur {user.username} activé.'

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': msg}, 'data': {'account_status': user.account_status}})


@cud_admin_api_bp.route('/users/<int:user_id>/toggle-role/<string:role>', methods=['POST'])
@jwt_required()
@csrf.exempt
def toggle_user_role(user_id, role):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)

    if role == 'beatmaker':
        user.is_beatmaker = not user.is_beatmaker
        msg = f'Rôle Beatmaker {"activé" if user.is_beatmaker else "désactivé"} pour {user.username}.'
    elif role == 'artist':
        user.is_artist = not user.is_artist
        msg = f'Rôle Interprète {"activé" if user.is_artist else "désactivé"} pour {user.username}.'
    elif role == 'engineer':
        user.is_mixmaster_engineer = not user.is_mixmaster_engineer
        msg = f'Rôle Engineer {"activé" if user.is_mixmaster_engineer else "désactivé"} pour {user.username}.'
    elif role == 'producer_arranger':
        if not user.is_mixmaster_engineer:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'{user.username} doit d\'abord être Engineer.'}}), 400
        user.is_certified_producer_arranger = not user.is_certified_producer_arranger
        msg = f'Certification Producteur/Arrangeur {"activée" if user.is_certified_producer_arranger else "désactivée"} pour {user.username}.'
    else:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Rôle invalide.'}}), 400

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': msg}})


@cud_admin_api_bp.route('/users/<int:user_id>/add-track-tokens', methods=['POST'])
@jwt_required()
@csrf.exempt
def add_track_tokens(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    data = request.get_json(silent=True) or {}
    tokens = int(data.get('tokens', 0))

    if tokens <= 0:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le nombre de tokens doit être positif.'}}), 400

    try:
        user.upload_track_tokens_promotion(tokens)
        db.session.commit()
    except Exception as e:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': str(e)}}), 500

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'{tokens} token(s) d\'upload ajouté(s) à {user.username}.'},
        'data': {'upload_track_tokens': user.upload_track_tokens},
    })


@cud_admin_api_bp.route('/users/<int:user_id>/add-topline-tokens', methods=['POST'])
@jwt_required()
@csrf.exempt
def add_topline_tokens(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    data = request.get_json(silent=True) or {}
    tokens = int(data.get('tokens', 0))

    if tokens <= 0:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le nombre de tokens doit être positif.'}}), 400

    try:
        user.topline_tokens_promotion(tokens)
        db.session.commit()
    except Exception as e:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': str(e)}}), 500

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'{tokens} token(s) de topline ajouté(s) à {user.username}.'},
        'data': {'topline_tokens': user.topline_tokens},
    })


@cud_admin_api_bp.route('/users/<int:user_id>/toggle-premium', methods=['POST'])
@jwt_required()
@csrf.exempt
def toggle_premium(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)

    if not user.is_premium:
        user.is_premium = True
        user.premium_since = datetime.now()
        user.premium_expires_at = datetime.now() + timedelta(days=30)
        msg = f'Premium activé pour {user.username} (30 jours).'
    else:
        user.is_premium = False
        user.premium_expires_at = datetime.now()
        msg = f'Premium désactivé pour {user.username}.'

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': msg}, 'data': {'is_premium': user.is_premium}})


# ── Engineers ─────────────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/engineers/<int:user_id>/upload-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
def admin_upload_engineer_sample(user_id):
    """Admin uploade les fichiers brut + traité pour un engineer (bypass du formulaire utilisateur)."""
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    if not user.is_mix_engineer:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'{user.username} n\'est pas un mix engineer.'}}), 400

    samples_folder = Path(config.UPLOAD_FOLDER) / 'mixmaster_samples'
    samples_folder.mkdir(parents=True, exist_ok=True)

    file_raw  = request.files.get('sample_raw')
    file_proc = request.files.get('sample_processed')

    if not file_raw and not file_proc:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Aucun fichier fourni.'}}), 400

    def _save_audio(f, label):
        ext = Path(secure_filename(f.filename)).suffix.lower()
        if ext not in ('.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'):
            return None, f'Format non supporté pour {label}.'
        fname = f'sample_{label}_{user_id}_{uuid.uuid4().hex[:8]}{ext}'
        f.save(samples_folder / fname)
        return f'mixmaster_samples/{fname}', None

    if file_raw:
        path, errmsg = _save_audio(file_raw, 'raw')
        if errmsg:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': errmsg}}), 400
        user.mixmaster_sample_raw = path

    if file_proc:
        path, errmsg = _save_audio(file_proc, 'processed')
        if errmsg:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': errmsg}}), 400
        user.mixmaster_sample_processed = path

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Samples uploadés pour {user.username}.'},
                    'data': {'sample_raw': user.mixmaster_sample_raw, 'sample_processed': user.mixmaster_sample_processed}})


@cud_admin_api_bp.route('/engineers/<int:user_id>/set-info', methods=['POST'])
@jwt_required()
@csrf.exempt
def admin_set_engineer_info(user_id):
    """Admin définit les infos (prix, bio) d'un engineer pour certification directe."""
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    data = request.get_json(silent=True) or {}

    if 'reference_price' in data:
        try:
            ref = round(float(data['reference_price']))
            if not (20 <= ref <= 500):
                return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Prix de référence entre 20€ et 500€.'}}), 400
            user.mixmaster_reference_price = ref
        except (ValueError, TypeError):
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Prix invalide.'}}), 400

    if 'price_min' in data:
        try:
            mn = round(float(data['price_min']))
            if not (20 <= mn <= 500):
                return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Prix min entre 20€ et 500€.'}}), 400
            user.mixmaster_price_min = mn
        except (ValueError, TypeError):
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Prix invalide.'}}), 400

    if 'bio' in data:
        user.mixmaster_bio = data['bio'].strip() or None

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Infos mises à jour pour {user.username}.'}})


@cud_admin_api_bp.route('/engineers/<int:user_id>/certify', methods=['POST'])
@jwt_required()
@csrf.exempt
def certify_engineer(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)

    if not user.mixmaster_sample_processed:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Un sample traité est requis avant de certifier {user.username}.'}}), 400

    user.is_mixmaster_engineer = True
    user.mixmaster_sample_submitted = True
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'{user.username} certifié comme mix/master engineer.'}})


@cud_admin_api_bp.route('/engineers/<int:user_id>/revoke', methods=['POST'])
@jwt_required()
@csrf.exempt
def revoke_engineer(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)

    active_requests = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.engineer_id == user_id,
        MixMasterRequest.status.in_(['pending', 'processing', 'delivered'])
    ).count()

    if active_requests > 0:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'{user.username} a {active_requests} demande(s) en cours. Impossible de révoquer.'}}), 400

    user.is_mixmaster_engineer = False
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Certification de {user.username} révoquée.'}})


@cud_admin_api_bp.route('/engineers/<int:user_id>/reject-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
def reject_engineer_sample(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    user.mixmaster_sample_submitted = False
    user.mixmaster_sample_raw = None
    user.mixmaster_sample_processed = None
    user.mixmaster_bio = None
    user.mixmaster_reference_price = None
    user.mixmaster_price_min = None
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Demande de certification de {user.username} rejetée.'}})


@cud_admin_api_bp.route('/engineers/<int:user_id>/update-prices', methods=['POST'])
@jwt_required()
@csrf.exempt
def update_engineer_prices(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    if not user.is_mixmaster_engineer:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'{user.username} n\'est pas un mix/master engineer.'}}), 400

    data = request.get_json(silent=True) or {}
    try:
        new_price_min       = round(float(data.get('price_min', 0)))
        new_reference_price = round(float(data.get('reference_price', 0)))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Prix invalides.'}}), 400

    if not (20 <= new_price_min <= 500):
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le prix minimum doit être entre 20€ et 500€.'}}), 400
    if not (20 <= new_reference_price <= 500):
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le prix de référence doit être entre 20€ et 500€.'}}), 400
    if new_price_min > new_reference_price:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le prix minimum ne peut pas être supérieur au prix de référence.'}}), 400

    user.mixmaster_price_min = new_price_min
    user.mixmaster_reference_price = new_reference_price
    db.session.commit()

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'Prix mis à jour pour {user.username}: {new_price_min}€ - {new_reference_price}€ (réf.)'},
    })


# ── Price change requests ─────────────────────────────────────────────────────

@cud_admin_api_bp.route('/price-requests/<int:request_id>/approve', methods=['POST'])
@jwt_required()
@csrf.exempt
def approve_price_change(request_id):
    _, err = _require_admin()
    if err:
        return err

    pr = db.get_or_404(PriceChangeRequest, request_id)
    if pr.status != 'pending':
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Cette demande a déjà été traitée.'}}), 400

    admin_id = int(get_jwt_identity())
    engineer = pr.engineer
    engineer.mixmaster_reference_price = round(pr.new_reference_price)
    engineer.mixmaster_price_min = round(pr.new_price_min)
    pr.status = 'approved'
    pr.processed_at = datetime.now()
    pr.processed_by = admin_id
    db.session.commit()

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'Prix approuvés pour {engineer.username}: {engineer.mixmaster_price_min}€ - {engineer.mixmaster_reference_price}€ (réf.)'},
    })


@cud_admin_api_bp.route('/price-requests/<int:request_id>/reject', methods=['POST'])
@jwt_required()
@csrf.exempt
def reject_price_change(request_id):
    _, err = _require_admin()
    if err:
        return err

    pr = db.get_or_404(PriceChangeRequest, request_id)
    if pr.status != 'pending':
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Cette demande a déjà été traitée.'}}), 400

    admin_id = int(get_jwt_identity())
    pr.status = 'rejected'
    pr.processed_at = datetime.now()
    pr.processed_by = admin_id
    db.session.commit()

    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Demande de prix rejetée pour {pr.engineer.username}.'}})


# ── Producer/Arranger ─────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/producer-arranger/<int:user_id>/approve', methods=['POST'])
@jwt_required()
@csrf.exempt
def approve_producer_arranger(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    if not user.producer_arranger_request_submitted:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'{user.username} n\'a pas demandé la certification.'}}), 400
    if not user.is_mixmaster_engineer:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'{user.username} doit d\'abord être mix/master engineer.'}}), 400

    user.is_certified_producer_arranger = True
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'{user.username} certifié comme producteur/arrangeur.'}})


@cud_admin_api_bp.route('/producer-arranger/<int:user_id>/revoke', methods=['POST'])
@jwt_required()
@csrf.exempt
def revoke_producer_arranger(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    user.is_certified_producer_arranger = False
    user.producer_arranger_request_submitted = False
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Certification Producteur/Arrangeur de {user.username} révoquée.'}})


@cud_admin_api_bp.route('/producer-arranger/<int:user_id>/reject', methods=['POST'])
@jwt_required()
@csrf.exempt
def reject_producer_arranger(user_id):
    _, err = _require_admin()
    if err:
        return err

    user = db.get_or_404(User, user_id)
    user.producer_arranger_request_submitted = False
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Demande Producteur/Arrangeur de {user.username} rejetée.'}})


# ── Contracts ─────────────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/contracts/create', methods=['POST'])
@jwt_required()
@csrf.exempt
def admin_create_contract():
    """Admin crée un contrat manuel entre un compositeur et un acheteur."""
    _, err = _require_admin()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    track_id    = data.get('track_id')
    client_id   = data.get('client_id')
    price       = data.get('price')
    is_exclusive = bool(data.get('is_exclusive', False))
    territory   = data.get('territory', 'France').strip()
    duration    = data.get('duration', '3 ans').strip()

    if not all([track_id, client_id, price is not None]):
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'track_id, client_id et price sont requis.'}}), 400

    track = db.get_or_404(Track, track_id)
    client = db.get_or_404(User, client_id)

    if not track.composer_id:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Ce track n\'a pas de compositeur.'}}), 400

    from datetime import date
    today = date.today().strftime('%d/%m/%Y')

    contract = Contract(
        track_id=track_id,
        composer_id=track.composer_id,
        client_id=client_id,
        composer_email=track.composer_user.email if track.composer_user else '',
        client_email=client.email,
        is_exclusive=is_exclusive,
        start_date=today,
        end_date=duration,
        duration_text=duration,
        territory=territory,
        mechanical_reproduction=True,
        public_show=False,
        streaming=True,
        arrangement=False,
        sacem_percentage_composer=70,
        sacem_percentage_buyer=30,
        price=int(float(price)),
        percentage=30,
        signature_date=today,
    )
    db.session.add(contract)
    db.session.commit()

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'Contrat créé entre {track.composer_user.username if track.composer_user else "?"} et {client.username} pour "{track.title}".'},
        'data': {'contract_id': contract.id},
    })


# ── Categories ────────────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/categories', methods=['POST'])
@jwt_required()
@csrf.exempt
def create_category():
    _, err = _require_admin()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name  = data.get('name', '').strip()
    color = data.get('color', '#6b7280').strip()

    if not name:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le nom est requis.'}}), 400

    cat = Category(name=name)
    if hasattr(cat, 'color'):
        cat.color = color
    db.session.add(cat)
    db.session.commit()

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'Catégorie "{name}" créée.'},
        'data': {'category': {'id': cat.id, 'name': cat.name, 'color': color, 'tags': []}},
    })


@cud_admin_api_bp.route('/categories/<int:cat_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
def edit_category(cat_id):
    _, err = _require_admin()
    if err:
        return err

    cat  = db.get_or_404(Category, cat_id)
    data = request.get_json(silent=True) or {}

    if 'name' in data:
        cat.name = data['name'].strip()
    if 'color' in data and hasattr(cat, 'color'):
        cat.color = data['color'].strip()

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Catégorie "{cat.name}" mise à jour.'}})


@cud_admin_api_bp.route('/categories/<int:cat_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
def delete_category(cat_id):
    _, err = _require_admin()
    if err:
        return err

    cat = db.get_or_404(Category, cat_id)
    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Catégorie "{name}" supprimée.'}})


# ── Tags ──────────────────────────────────────────────────────────────────────

@cud_admin_api_bp.route('/tags', methods=['POST'])
@jwt_required()
@csrf.exempt
def create_tag():
    _, err = _require_admin()
    if err:
        return err

    data        = request.get_json(silent=True) or {}
    name        = data.get('name', '').strip()
    category_id = data.get('category_id')

    if not name:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le nom est requis.'}}), 400

    tag = Tag(name=name, category_id=category_id)
    db.session.add(tag)
    db.session.commit()

    return jsonify({
        'success': True,
        'feedback': {'level': 'info', 'message': f'Tag "{name}" créé.'},
        'data': {'tag': {'id': tag.id, 'name': tag.name}},
    })


@cud_admin_api_bp.route('/tags/<int:tag_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
def edit_tag(tag_id):
    _, err = _require_admin()
    if err:
        return err

    tag  = db.get_or_404(Tag, tag_id)
    data = request.get_json(silent=True) or {}

    if 'name' in data:
        tag.name = data['name'].strip()
    if 'category_id' in data:
        tag.category_id = data['category_id']

    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Tag "{tag.name}" mis à jour.'}})


@cud_admin_api_bp.route('/tags/<int:tag_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
def delete_tag(tag_id):
    _, err = _require_admin()
    if err:
        return err

    tag = db.get_or_404(Tag, tag_id)
    name = tag.name
    db.session.delete(tag)
    db.session.commit()
    return jsonify({'success': True, 'feedback': {'level': 'info', 'message': f'Tag "{name}" supprimé.'}})
