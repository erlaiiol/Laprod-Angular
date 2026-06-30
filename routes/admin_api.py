"""
Blueprint ADMIN API — GET + CUD endpoints pour l'administration

GET    /api/admin/stats                         → tableau de bord
GET    /api/admin/tracks                        → liste tracks (pending/approved)
GET    /api/admin/users                         → liste utilisateurs
GET    /api/admin/engineers                     → liste ingénieurs
GET    /api/admin/engineers/all-mix             → tous les mix engineers
GET    /api/admin/contracts                     → liste contrats
GET    /api/admin/transactions                  → liste transactions mixmaster
GET    /api/admin/users/search                  → recherche utilisateurs
GET    /api/admin/tracks/search                 → recherche tracks
GET    /api/admin/categories                    → liste catégories/tags
GET    /api/admin/styles                        → liste styles distincts
POST   /api/admin/tracks/<id>/approve           → approuver un track
DELETE /api/admin/tracks/<id>                   → rejeter/supprimer un track
PUT    /api/admin/tracks/<id>                   → modifier un track
POST   /api/admin/users/<id>/toggle-status      → activer/désactiver utilisateur
POST   /api/admin/users/<id>/toggle-role/<role> → activer/désactiver un rôle
POST   /api/admin/users/<id>/add-track-tokens   → ajouter tokens upload
POST   /api/admin/users/<id>/add-topline-tokens → ajouter tokens topline
POST   /api/admin/users/<id>/toggle-premium     → activer/désactiver premium
POST   /api/admin/engineers/<id>/upload-sample  → uploader samples engineer
POST   /api/admin/engineers/<id>/set-info       → définir infos engineer
POST   /api/admin/engineers/<id>/certify        → certifier engineer
POST   /api/admin/engineers/<id>/revoke         → révoquer certification
POST   /api/admin/engineers/<id>/reject-sample  → rejeter demande
POST   /api/admin/engineers/<id>/update-prices  → MAJ prix engineer
POST   /api/admin/price-requests/<id>/approve   → approuver demande de prix
POST   /api/admin/price-requests/<id>/reject    → rejeter demande de prix
POST   /api/admin/producer-arranger/<id>/approve → approuver cert. prod/arr
POST   /api/admin/producer-arranger/<id>/revoke  → révoquer cert. prod/arr
POST   /api/admin/producer-arranger/<id>/reject  → rejeter demande prod/arr
POST   /api/admin/contracts/create              → créer contrat manuel
POST   /api/admin/categories                    → créer catégorie
PUT    /api/admin/categories/<id>               → modifier catégorie
DELETE /api/admin/categories/<id>               → supprimer catégorie
POST   /api/admin/tags                          → créer tag
PUT    /api/admin/tags/<id>                     → modifier tag
DELETE /api/admin/tags/<id>                     → supprimer tag
"""
from flask import Blueprint, request, current_app, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from pathlib import Path
from sqlalchemy import select, distinct
import uuid
import config

from extensions import db, csrf
from serializers import ok, err as ser_err, track_admin, user_admin, user_ref
from helpers import generate_track_image
from utils import email_service, notification_service
from utils.auth_helpers import require_admin
from models import (
    Track, User, Tag, Category, MixMasterRequest, Contract, PriceChangeRequest,
    ContractClauseGroup, ContractClause, UserContractValue, ClauseTypeEnum,
    ListenEvent, SimilarArtist,
)

admin_api_bp = Blueprint('admin_api', __name__, url_prefix='/api/admin')


# ── Dashboard stats ───────────────────────────────────────────────────────────

@admin_api_bp.route('/stats', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_stats(current_user):
    pending_tracks_count  = db.session.query(Track).filter_by(is_approved=False).count()
    approved_tracks_count = db.session.query(Track).filter_by(is_approved=True).count()
    total_tracks          = db.session.query(Track).count()

    total_users      = db.session.query(User).filter_by(account_status='active').count()
    premium_users    = db.session.query(User).filter(User.is_premium == True, User.account_status == 'active').count()
    beatmakers_count = db.session.query(User).filter_by(is_beatmaker=True, account_status='active').count()
    artists_count    = db.session.query(User).filter_by(is_artist=True, account_status='active').count()
    engineers_count  = db.session.query(User).filter_by(is_mixmaster_engineer=True, account_status='active').count()

    total_contracts     = db.session.query(Contract).count()
    exclusive_contracts = db.session.query(Contract).filter_by(is_exclusive=True).count()
    total_revenue       = db.session.scalar(select(db.func.sum(Contract.price))) or 0

    mm_in_progress = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.status.in_(['accepted', 'processing', 'delivered'])
    ).count()
    mm_completed = db.session.query(MixMasterRequest).filter_by(status='completed').count()
    mm_revenue   = db.session.scalar(
        select(db.func.sum(MixMasterRequest.total_price)).where(MixMasterRequest.status == 'completed')
    ) or 0

    recent_tracks = db.session.scalars(
        select(Track).where(Track.is_approved == True).order_by(Track.approved_at.desc()).limit(5)
    ).all()

    recent_users = db.session.scalars(
        select(User).where(User.account_status == 'active').order_by(User.created_at.desc()).limit(5)
    ).all()

    return ok({
        'tracks': {
            'pending':  pending_tracks_count,
            'approved': approved_tracks_count,
            'total':    total_tracks,
        },
        'users': {
            'total':      total_users,
            'premium':    premium_users,
            'beatmakers': beatmakers_count,
            'artists':    artists_count,
            'engineers':  engineers_count,
        },
        'contracts': {
            'total':     total_contracts,
            'exclusive': exclusive_contracts,
            'revenue':   float(total_revenue),
        },
        'mixmaster': {
            'in_progress': mm_in_progress,
            'completed':   mm_completed,
            'revenue':     float(mm_revenue),
        },
        'recent_tracks': [
            {
                'id':          t.id,
                'title':       t.title,
                'image_file':  t.image_file,
                'approved_at': t.approved_at.isoformat() if t.approved_at else None,
                'composer':    {'username': t.composer_user.username} if t.composer_user else None,
            }
            for t in recent_tracks
        ],
        'recent_users': [
            {
                'id':            u.id,
                'username':      u.username,
                'profile_image': u.profile_picture_url or u.profile_image,
                'created_at':    u.created_at.isoformat() if u.created_at else None,
            }
            for u in recent_users
        ],
    })


# ── Tracks (GET) ──────────────────────────────────────────────────────────────

@admin_api_bp.route('/tracks', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_tracks(current_user):
    status = request.args.get('status', 'pending')

    query = select(Track).order_by(Track.created_at.desc())
    if status == 'pending':
        query = query.where(Track.is_approved == False)
    elif status == 'approved':
        query = query.where(Track.is_approved == True)

    tracks         = db.session.scalars(query).all()
    pending_count  = db.session.query(Track).filter_by(is_approved=False).count()
    approved_count = db.session.query(Track).filter_by(is_approved=True).count()

    return ok({
        'tracks':        [track_admin(t) for t in tracks],
        'pending_count':  pending_count,
        'approved_count': approved_count,
    })


# ── Users (GET) ───────────────────────────────────────────────────────────────

@admin_api_bp.route('/users', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_users(current_user):
    user_type = request.args.get('user_type', 'all')

    query = select(User).order_by(User.created_at.desc())
    if user_type == 'beatmakers':
        query = query.where(User.is_beatmaker == True)
    elif user_type == 'artists':
        query = query.where(User.is_artist == True)
    elif user_type == 'engineers':
        query = query.where(User.is_mixmaster_engineer == True)

    users      = db.session.scalars(query).all()
    users_data = []
    for u in users:
        tracks_count    = db.session.query(Track).filter_by(composer_id=u.id).count()
        contracts_count = db.session.query(Contract).filter_by(client_id=u.id).count()
        mm_count        = db.session.query(MixMasterRequest).filter_by(engineer_id=u.id).count()
        users_data.append(user_admin(
            u,
            tracks_count=tracks_count,
            contracts_count=contracts_count,
            mm_count=mm_count,
        ))

    all_count        = db.session.query(User).count()
    beatmakers_count = db.session.query(User).filter_by(is_beatmaker=True).count()
    artists_count    = db.session.query(User).filter_by(is_artist=True).count()
    engineers_count  = db.session.query(User).filter_by(is_mixmaster_engineer=True).count()

    return ok({
        'users': users_data,
        'counts': {
            'all':        all_count,
            'beatmakers': beatmakers_count,
            'artists':    artists_count,
            'engineers':  engineers_count,
        },
    })


# ── Engineers (GET) ───────────────────────────────────────────────────────────

@admin_api_bp.route('/engineers', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_engineers(current_user):
    def _engineer_admin_dict(u):
        return {
            **user_ref(u),
            'email':                             u.email,
            'mixmaster_reference_price':         u.mixmaster_reference_price,
            'mixmaster_price_min':               u.mixmaster_price_min,
            'mixmaster_bio':                     u.mixmaster_bio,
            'mixmaster_sample_raw':              u.mixmaster_sample_raw,
            'mixmaster_sample_processed':        u.mixmaster_sample_processed,
            'is_certified_producer_arranger':    u.is_certified_producer_arranger,
            'producer_arranger_request_submitted': u.producer_arranger_request_submitted,
            'is_mixmaster_engineer':             u.is_mixmaster_engineer,
            'is_certified_master_engineer':      u.is_certified_master_engineer,
            'master_sample_raw':                 u.master_sample_raw,
            'master_sample_processed':           u.master_sample_processed,
            'master_sample_submitted':           u.master_sample_submitted,
            'created_at':                        u.created_at.isoformat() if u.created_at else None,
        }

    certified = db.session.scalars(
        select(User).where(User.is_mixmaster_engineer == True)
    ).all()

    pending = db.session.scalars(
        select(User).where(
            User.is_mix_engineer == True,
            User.mixmaster_sample_submitted == True,
            User.is_mixmaster_engineer == False,
        )
    ).all()

    pa_requests = db.session.scalars(
        select(User).where(
            User.is_mixmaster_engineer == True,
            User.producer_arranger_request_submitted == True,
            User.is_certified_producer_arranger == False,
        )
    ).all()

    master_pending = db.session.scalars(
        select(User).where(
            User.is_mixmaster_engineer == True,
            User.master_sample_submitted == True,
            User.is_certified_master_engineer == False,
        )
    ).all()

    price_requests = db.session.scalars(
        select(PriceChangeRequest).where(PriceChangeRequest.status == 'pending')
        .order_by(PriceChangeRequest.created_at.desc())
    ).all()

    return ok({
        'certified':       [_engineer_admin_dict(u) for u in certified],
        'pending':         [_engineer_admin_dict(u) for u in pending],
        'pa_requests':     [_engineer_admin_dict(u) for u in pa_requests],
        'master_pending':  [_engineer_admin_dict(u) for u in master_pending],
        'price_requests': [
            {
                'id':                      pr.id,
                'engineer_id':             pr.engineer_id,
                'engineer_username':       pr.engineer.username if pr.engineer else None,
                'current_reference_price': pr.engineer.mixmaster_reference_price if pr.engineer else None,
                'current_price_min':       pr.engineer.mixmaster_price_min if pr.engineer else None,
                'new_reference_price':     pr.new_reference_price,
                'new_price_min':           pr.new_price_min,
                'created_at':              pr.created_at.isoformat() if pr.created_at else None,
            }
            for pr in price_requests
        ],
    })


@admin_api_bp.route('/engineers/all-mix', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_all_mix_engineers(current_user):
    """Tous les utilisateurs avec is_mix_engineer=True — pour certification directe admin."""
    users = db.session.scalars(
        select(User).where(User.is_mix_engineer == True).order_by(User.username)
    ).all()

    def _u(u):
        return {
            'id':                             u.id,
            'username':                       u.username,
            'email':                          u.email,
            'profile_image':                  u.profile_picture_url or u.profile_image,
            'is_mixmaster_engineer':          u.is_mixmaster_engineer,
            'is_certified_producer_arranger': u.is_certified_producer_arranger,
            'mixmaster_reference_price':      u.mixmaster_reference_price,
            'mixmaster_price_min':            u.mixmaster_price_min,
            'mixmaster_bio':                  u.mixmaster_bio,
            'mixmaster_sample_raw':           u.mixmaster_sample_raw,
            'mixmaster_sample_processed':     u.mixmaster_sample_processed,
            'created_at':                     u.created_at.isoformat() if u.created_at else None,
        }

    return ok({'engineers': [_u(u) for u in users]})


# ── Contracts (GET) ───────────────────────────────────────────────────────────

@admin_api_bp.route('/contracts', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_contracts(current_user):
    contracts           = db.session.scalars(select(Contract).order_by(Contract.created_at.desc())).all()
    exclusive_count     = db.session.query(Contract).filter_by(is_exclusive=True).count()
    non_exclusive_count = db.session.query(Contract).filter_by(is_exclusive=False).count()
    total_revenue       = sum(c.price for c in contracts)

    return ok({
        'contracts': [
            {
                'id':           c.id,
                'price':        c.price,
                'is_exclusive': c.is_exclusive,
                'format':       c.format if hasattr(c, 'format') else None,
                'created_at':   c.created_at.isoformat() if c.created_at else None,
                'track': {
                    'id':    c.track.id,
                    'title': c.track.title,
                } if c.track else None,
                'client': {
                    'id':       c.client.id,
                    'username': c.client.username,
                } if c.client else None,
                'composer': {
                    'id':       c.composer.id,
                    'username': c.composer.username,
                } if hasattr(c, 'composer') and c.composer else None,
            }
            for c in contracts
        ],
        'exclusive_count':     exclusive_count,
        'non_exclusive_count': non_exclusive_count,
        'total_revenue':       float(total_revenue),
    })


# ── Transactions (GET) ────────────────────────────────────────────────────────

@admin_api_bp.route('/transactions', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_transactions(current_user):
    status = request.args.get('status', 'all')

    query = select(MixMasterRequest).order_by(MixMasterRequest.created_at.desc())
    if status == 'in_progress':
        query = query.where(MixMasterRequest.status.in_(['accepted', 'processing', 'delivered']))
    elif status == 'completed':
        query = query.where(MixMasterRequest.status == 'completed').order_by(MixMasterRequest.completed_at.desc())
    elif status == 'awaiting':
        query = query.where(MixMasterRequest.status == 'awaiting_acceptance')

    transactions      = db.session.scalars(query).all()
    awaiting_count    = db.session.query(MixMasterRequest).filter_by(status='awaiting_acceptance').count()
    in_progress_count = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.status.in_(['accepted', 'processing', 'delivered'])
    ).count()
    completed_count   = db.session.query(MixMasterRequest).filter_by(status='completed').count()
    all_count         = db.session.query(MixMasterRequest).count()
    total_revenue     = db.session.scalar(
        select(db.func.sum(MixMasterRequest.total_price)).where(MixMasterRequest.status == 'completed')
    ) or 0

    return ok({
        'transactions': [
            {
                'id':           t.id,
                'status':       t.status,
                'total_price':  t.total_price,
                'created_at':   t.created_at.isoformat() if t.created_at else None,
                'completed_at': t.completed_at.isoformat() if t.completed_at else None,
                'artist': {
                    'id':       t.artist_user.id,
                    'username': t.artist_user.username,
                } if t.artist_user else None,
                'engineer': {
                    'id':       t.engineer_user.id,
                    'username': t.engineer_user.username,
                } if t.engineer_user else None,
            }
            for t in transactions
        ],
        'counts': {
            'all':         all_count,
            'awaiting':    awaiting_count,
            'in_progress': in_progress_count,
            'completed':   completed_count,
        },
        'total_revenue': float(total_revenue),
    })


# ── Search ────────────────────────────────────────────────────────────────────

@admin_api_bp.route('/users/search', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def search_users(current_user):
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return ok({'users': []})

    users = db.session.scalars(
        select(User)
        .where(User.username.ilike(f'%{q}%'), User.account_status == 'active')
        .limit(10)
    ).all()

    return ok({'users': [
        {'id': u.id, 'username': u.username, 'email': u.email}
        for u in users
    ]})


@admin_api_bp.route('/tracks/search', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def search_tracks(current_user):
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return ok({'tracks': []})

    tracks = db.session.scalars(
        select(Track)
        .where(Track.title.ilike(f'%{q}%'), Track.is_approved == True)
        .limit(10)
    ).all()

    return ok({'tracks': [
        {
            'id':               t.id,
            'title':            t.title,
            'composer_username': t.composer_user.username if t.composer_user else None,
            'composer_id':      t.composer_id,
            'price_mp3':        t.price_mp3,
            'price_wav':        t.price_wav,
            'price_stems':      t.price_stems,
        }
        for t in tracks
    ]})


# ── Categories & Tags (GET) ───────────────────────────────────────────────────

@admin_api_bp.route('/categories', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_categories(current_user):
    categories      = db.session.scalars(select(Category)).all()
    categories_data = []
    for cat in categories:
        tags = db.session.scalars(select(Tag).where(Tag.category_id == cat.id)).all()
        categories_data.append({
            'id':          cat.id,
            'name':        cat.name,
            'color':       cat.color        if hasattr(cat, 'color')        and cat.color        else '#6b7280',
            'description': cat.description  if hasattr(cat, 'description') and cat.description  else None,
            'tags': [{'id': tag.id, 'name': tag.name} for tag in tags],
        })

    return ok({'categories': categories_data})


@admin_api_bp.route('/styles', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_styles(current_user):
    styles = db.session.execute(
        select(distinct(Track.style))
        .where(Track.style.isnot(None), Track.style != '')
        .order_by(Track.style)
    ).scalars().all()

    return ok({'styles': list(styles)})


# ── Tracks (CUD) ──────────────────────────────────────────────────────────────

@admin_api_bp.route('/tracks/<int:track_id>/approve', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def approve_track(track_id, current_user):
    track = db.get_or_404(Track, track_id)
    track.is_approved = True
    track.approved_at = datetime.now()
    db.session.commit()
    current_app.logger.info(
        "[AUDIT] approve_track — admin=%s (#%d) → track=%r (#%d)",
        current_user.username, current_user.id, track.title, track_id,
    )

    try:
        email_service.send_track_approved_email(track)
    except Exception as e:
        current_app.logger.warning(f"Email approbation track: {e}")
    try:
        notification_service.notify_track_approved(track)
    except Exception as e:
        current_app.logger.warning(f"Notif approbation track: {e}")

    return ok(message=f'Track "{track.title}" approuvé.', level='info')


@admin_api_bp.route('/tracks/<int:track_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
def reject_track(track_id, current_user):
    track = db.get_or_404(Track, track_id)
    title = track.title

    current_app.logger.info(
        "[AUDIT] reject_track — admin=%s (#%d) → track=%r (#%d)",
        current_user.username, current_user.id, title, track_id,
    )

    try:
        email_service.send_track_rejected_email(track)
    except Exception:
        pass
    try:
        notification_service.notify_track_rejected(track)
    except Exception:
        pass

    db.session.delete(track)
    db.session.commit()

    return ok(message=f'Track "{title}" supprimé.', level='info')


@admin_api_bp.route('/tracks/<int:track_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
def edit_track(track_id, current_user):
    track = db.get_or_404(Track, track_id)
    data  = request.get_json(silent=True) or request.form

    if 'title'       in data: track.title       = data['title']
    if 'bpm'         in data: track.bpm          = int(data['bpm'])
    if 'key'         in data: track.key          = data['key']
    if 'style'       in data: track.style        = data['style']
    if 'price_mp3'   in data: track.price_mp3    = float(data['price_mp3'])
    if 'price_wav'   in data: track.price_wav    = float(data['price_wav'])
    if 'price_stems' in data and data['price_stems']:
        track.price_stems = float(data['price_stems'])

    tag_ids_str = data.get('tag_ids', '')
    if tag_ids_str:
        selected_tag_ids = [int(i.strip()) for i in tag_ids_str.split(',') if i.strip()]
        track.tags = db.session.scalars(select(Tag).where(Tag.id.in_(selected_tag_ids))).all()
    elif 'tag_ids' in data:
        track.tags = []

    file_image = request.files.get('file_image')
    if file_image and file_image.filename:
        from utils.file_validator import validate_image_file
        is_valid, error_message = validate_image_file(file_image)
        if is_valid:
            tracks_img_folder = config.IMAGES_FOLDER / 'tracks'
            tracks_img_folder.mkdir(parents=True, exist_ok=True)
            ext              = Path(secure_filename(file_image.filename)).suffix.lower()
            safe_title       = secure_filename(track.title)[:30]
            new_img_filename = f"{safe_title}_{uuid.uuid4().hex[:8]}{ext}"
            new_img_path     = tracks_img_folder / new_img_filename
            if track.image_file:
                old_name = track.image_file.replace('images/tracks/', '')
                if old_name and old_name != 'default_track.png':
                    old_path = tracks_img_folder / old_name
                    if old_path.exists():
                        old_path.unlink()
            file_image.save(new_img_path)
            track.image_file = f'images/tracks/{new_img_filename}'
        else:
            return ser_err(f'Image invalide : {error_message}', status=400)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return ser_err(str(e), status=500)

    return ok(message=f'Track "{track.title}" mis à jour.', level='info')


# ── Users (CUD) ───────────────────────────────────────────────────────────────

@admin_api_bp.route('/users/<int:user_id>/resend-verification', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_resend_verification(user_id, current_user):
    """Admin renvoie l'email de vérification à un utilisateur non vérifié."""
    user = db.get_or_404(User, user_id)
    if user.email_verified:
        return ser_err('Cet utilisateur a déjà vérifié son email.')
    if not user.email:
        return ser_err('Cet utilisateur n\'a pas d\'adresse email.')
    try:
        email_service.send_verification_email(user)
    except Exception as e:
        current_app.logger.error(f'Admin resend verification user #{user_id}: {e}', exc_info=True)
        return ser_err('Erreur lors de l\'envoi de l\'email.', status=500)
    return ok(message=f'Email de vérification renvoyé à {user.email}.', level='info')


@admin_api_bp.route('/users/<int:user_id>/toggle-status', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def toggle_user_status(user_id, current_user):
    if current_user.id == user_id:
        return ser_err('Vous ne pouvez pas vous désactiver.')

    user = db.get_or_404(User, user_id)
    if user.account_status == 'active':
        user.account_status = 'deleted'
        msg = f'Utilisateur {user.username} désactivé.'
    else:
        user.account_status = 'active'
        msg = f'Utilisateur {user.username} activé.'

    db.session.commit()
    return ok({'account_status': user.account_status}, message=msg, level='info')


@admin_api_bp.route('/users/<int:user_id>/toggle-role/<string:role>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def toggle_user_role(user_id, role, current_user):
    user = db.get_or_404(User, user_id)

    if role == 'beatmaker':
        user.is_beatmaker = not user.is_beatmaker
        msg = f'Rôle Beatmaker {"activé" if user.is_beatmaker else "désactivé"} pour {user.username}.'
    elif role == 'artist':
        user.is_artist = not user.is_artist
        msg = f'Rôle Interprète {"activé" if user.is_artist else "désactivé"} pour {user.username}.'
    elif role == 'engineer':
        user.is_mixmaster_engineer = not user.is_mixmaster_engineer
        if not user.is_mixmaster_engineer:
            user.is_certified_master_engineer      = False
            user.is_certified_producer_arranger    = False
        msg = f'Certification Mix {"accordée" if user.is_mixmaster_engineer else "révoquée"} pour {user.username}.'
    elif role == 'master':
        if not user.is_mixmaster_engineer:
            return ser_err(f"{user.username} doit d'abord être certifié Mix Engineer.")
        user.is_certified_master_engineer = not user.is_certified_master_engineer
        msg = f'Certification Master {"accordée" if user.is_certified_master_engineer else "révoquée"} pour {user.username}.'
    elif role == 'producer_arranger':
        if not user.is_mixmaster_engineer:
            return ser_err(f"{user.username} doit d'abord être certifié Mix Engineer.")
        user.is_certified_producer_arranger = not user.is_certified_producer_arranger
        msg = f'Certification Producteur/Arrangeur {"accordée" if user.is_certified_producer_arranger else "révoquée"} pour {user.username}.'
    else:
        return ser_err('Rôle invalide.')

    db.session.commit()

    try:
        notification_service.notify_role_changed(user, role, granted=(msg.find('activé') != -1 or msg.find('accordée') != -1))
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f'Notif toggle_user_role: {e}')

    return ok(message=msg, level='info')


@admin_api_bp.route('/users/<int:user_id>/add-track-tokens', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def add_track_tokens(user_id, current_user):
    user   = db.get_or_404(User, user_id)
    data   = request.get_json(silent=True) or {}
    tokens = int(data.get('tokens', 0))

    if tokens <= 0:
        return ser_err('Le nombre de tokens doit être positif.')

    try:
        user.upload_track_tokens_promotion(tokens)
        db.session.commit()
    except Exception as e:
        return ser_err(str(e), status=500)

    try:
        notification_service.notify_tokens_added(user, 'track', tokens)
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f'Notif add_track_tokens: {e}')

    return ok({'upload_track_tokens': user.upload_track_tokens},
              message=f"{tokens} token(s) d'upload ajouté(s) à {user.username}.", level='info')


@admin_api_bp.route('/users/<int:user_id>/add-topline-tokens', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def add_topline_tokens(user_id, current_user):
    user   = db.get_or_404(User, user_id)
    data   = request.get_json(silent=True) or {}
    tokens = int(data.get('tokens', 0))

    if tokens <= 0:
        return ser_err('Le nombre de tokens doit être positif.')

    try:
        user.topline_tokens_promotion(tokens)
        db.session.commit()
    except Exception as e:
        return ser_err(str(e), status=500)

    try:
        notification_service.notify_tokens_added(user, 'topline', tokens)
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f'Notif add_topline_tokens: {e}')

    return ok({'topline_tokens': user.topline_tokens},
              message=f"{tokens} token(s) de topline ajouté(s) à {user.username}.", level='info')


@admin_api_bp.route('/users/<int:user_id>/toggle-premium', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def toggle_premium(user_id, current_user):
    """Toggle rapide free ↔ amateur (comportement admin existant conservé)."""
    user = db.get_or_404(User, user_id)

    old_plan = user.subscription_plan

    if not user.is_premium_active:
        user.subscription_plan  = 'amateur'
        user.premium_since      = datetime.now()
        user.premium_expires_at = datetime.now() + timedelta(days=30)
        new_plan = 'amateur'
        msg = f'Plan Amateur activé pour {user.username} (30 jours).'
    else:
        user.subscription_plan  = 'free'
        user.premium_expires_at = datetime.now()
        new_plan = 'free'
        msg = f'Abonnement désactivé pour {user.username}.'

    db.session.commit()

    try:
        notification_service.notify_plan_changed(
            user, new_plan, old_plan,
            expires_at=user.premium_expires_at,
            granted_by_admin=True,
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f'Notif toggle_premium: {e}')

    try:
        email_service.send_plan_changed_email(
            user, new_plan,
            expires_at=user.premium_expires_at if new_plan != 'free' else None,
            granted_by_admin=True,
        )
    except Exception as e:
        current_app.logger.warning(f'Email toggle_premium: {e}')

    return ok({'is_premium': user.is_premium, 'subscription_plan': user.subscription_plan}, message=msg, level='info')


@admin_api_bp.route('/users/<int:user_id>/set-plan', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def set_plan(user_id, current_user):
    """Définit le plan de l'utilisateur : free | amateur | pro (toujours 30 jours)."""
    import config as _cfg
    user = db.get_or_404(User, user_id)
    data = request.get_json(silent=True) or {}
    plan = data.get('plan', '').lower()
    if plan not in ('free', 'amateur', 'pro'):
        return err("Plan invalide. Valeurs : 'free', 'amateur', 'pro'.", 400)

    old_plan = user.subscription_plan

    if plan == 'free':
        user.subscription_plan  = 'free'
        user.premium_expires_at = datetime.now()
        user.premium_source     = None
        user.premium_price_paid = None
        msg = f'Plan Free appliqué pour {user.username}.'
    else:
        user.subscription_plan  = plan
        user.premium_since      = datetime.now()
        user.premium_expires_at = datetime.now() + timedelta(days=_cfg.PREMIUM_DURATION_DAYS)
        user.premium_source     = 'admin'
        user.premium_price_paid = None
        msg = f'Plan {plan.capitalize()} accordé à {user.username} (30 jours).'

    db.session.commit()

    try:
        notification_service.notify_plan_changed(
            user, plan, old_plan,
            expires_at=user.premium_expires_at,
            granted_by_admin=True,
        )
        db.session.commit()
    except Exception as e:
        current_app.logger.warning(f'Notif plan_changed: {e}')

    try:
        email_service.send_plan_changed_email(
            user, plan,
            expires_at=user.premium_expires_at if plan != 'free' else None,
            granted_by_admin=True,
        )
    except Exception as e:
        current_app.logger.warning(f'Email plan_changed: {e}')

    return ok({
        'is_premium':        user.is_premium,
        'subscription_plan': user.subscription_plan,
        'premium_expires_at': user.premium_expires_at.isoformat() if user.premium_expires_at else None,
    }, message=msg, level='info')


# ── Engineers (CUD) ───────────────────────────────────────────────────────────

@admin_api_bp.route('/engineers/<int:user_id>/upload-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_upload_engineer_sample(user_id, current_user):
    """Admin uploade les fichiers brut + traité pour un engineer (bypass du formulaire utilisateur)."""
    user = db.get_or_404(User, user_id)
    if not user.is_mix_engineer:
        return ser_err(f"{user.username} n'est pas un mix engineer.")

    samples_folder = Path(config.UPLOAD_FOLDER) / 'mixmaster_samples'
    samples_folder.mkdir(parents=True, exist_ok=True)

    file_raw  = request.files.get('sample_raw')
    file_proc = request.files.get('sample_processed')

    if not file_raw and not file_proc:
        return ser_err('Aucun fichier fourni.')

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
            return ser_err(errmsg)
        user.mixmaster_sample_raw = path

    if file_proc:
        path, errmsg = _save_audio(file_proc, 'processed')
        if errmsg:
            return ser_err(errmsg)
        user.mixmaster_sample_processed = path

    db.session.commit()
    return ok(
        {'sample_raw': user.mixmaster_sample_raw, 'sample_processed': user.mixmaster_sample_processed},
        message=f'Samples uploadés pour {user.username}.', level='info',
    )


@admin_api_bp.route('/engineers/<int:user_id>/set-info', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_set_engineer_info(user_id, current_user):
    """Admin définit les infos (prix, bio) d'un engineer pour certification directe."""
    user = db.get_or_404(User, user_id)
    data = request.get_json(silent=True) or {}

    if 'reference_price' in data:
        try:
            ref = round(float(data['reference_price']))
            if not (20 <= ref <= 500):
                return ser_err('Prix de référence entre 20€ et 500€.')
            user.mixmaster_reference_price = ref
        except (ValueError, TypeError):
            return ser_err('Prix invalide.')

    if 'price_min' in data:
        try:
            mn = round(float(data['price_min']))
            if not (20 <= mn <= 500):
                return ser_err('Prix min entre 20€ et 500€.')
            user.mixmaster_price_min = mn
        except (ValueError, TypeError):
            return ser_err('Prix invalide.')

    if 'bio' in data:
        user.mixmaster_bio = data['bio'].strip() or None

    db.session.commit()
    return ok(message=f'Infos mises à jour pour {user.username}.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/certify', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def certify_engineer(user_id, current_user):
    user = db.get_or_404(User, user_id)

    if not user.mixmaster_sample_processed:
        return ser_err(f'Un sample traité est requis avant de certifier {user.username}.')

    user.is_mixmaster_engineer       = True
    user.mixmaster_sample_submitted  = True
    db.session.commit()
    return ok(message=f'{user.username} certifié comme mix/master engineer.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/revoke', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def revoke_engineer(user_id, current_user):
    user = db.get_or_404(User, user_id)

    active_requests = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.engineer_id == user_id,
        MixMasterRequest.status.in_(['pending', 'processing', 'delivered'])
    ).count()

    if active_requests > 0:
        return ser_err(f'{user.username} a {active_requests} demande(s) en cours. Impossible de révoquer.')

    user.is_mixmaster_engineer = False
    db.session.commit()
    return ok(message=f'Certification de {user.username} révoquée.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/reject-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def reject_engineer_sample(user_id, current_user):
    user = db.get_or_404(User, user_id)
    user.mixmaster_sample_submitted  = False
    user.mixmaster_sample_raw        = None
    user.mixmaster_sample_processed  = None
    user.mixmaster_bio               = None
    user.mixmaster_reference_price   = None
    user.mixmaster_price_min         = None
    db.session.commit()
    return ok(message=f'Demande de certification de {user.username} rejetée.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/update-prices', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def update_engineer_prices(user_id, current_user):
    user = db.get_or_404(User, user_id)
    if not user.is_mixmaster_engineer:
        return ser_err(f"{user.username} n'est pas un mix/master engineer.")

    data = request.get_json(silent=True) or {}
    try:
        new_price_min       = round(float(data.get('price_min', 0)))
        new_reference_price = round(float(data.get('reference_price', 0)))
    except (ValueError, TypeError):
        return ser_err('Prix invalides.')

    if not (20 <= new_price_min <= 500):
        return ser_err('Le prix minimum doit être entre 20€ et 500€.')
    if not (20 <= new_reference_price <= 500):
        return ser_err('Le prix de référence doit être entre 20€ et 500€.')
    if new_price_min > new_reference_price:
        return ser_err('Le prix minimum ne peut pas être supérieur au prix de référence.')

    user.mixmaster_price_min        = new_price_min
    user.mixmaster_reference_price  = new_reference_price
    db.session.commit()

    return ok(message=f'Prix mis à jour pour {user.username}: {new_price_min}€ - {new_reference_price}€ (réf.)', level='info')


# ── Price change requests ─────────────────────────────────────────────────────

@admin_api_bp.route('/price-requests/<int:request_id>/approve', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def approve_price_change(request_id, current_user):
    pr = db.get_or_404(PriceChangeRequest, request_id)
    if pr.status != 'pending':
        return ser_err('Cette demande a déjà été traitée.')

    engineer = pr.engineer
    engineer.mixmaster_reference_price = round(pr.new_reference_price)
    engineer.mixmaster_price_min       = round(pr.new_price_min)
    pr.status       = 'approved'
    pr.processed_at = datetime.now()
    pr.processed_by = current_user.id
    db.session.commit()

    return ok(message=f'Prix approuvés pour {engineer.username}: {engineer.mixmaster_price_min}€ - {engineer.mixmaster_reference_price}€ (réf.)', level='info')


@admin_api_bp.route('/price-requests/<int:request_id>/reject', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def reject_price_change(request_id, current_user):
    pr = db.get_or_404(PriceChangeRequest, request_id)
    if pr.status != 'pending':
        return ser_err('Cette demande a déjà été traitée.')

    pr.status       = 'rejected'
    pr.processed_at = datetime.now()
    pr.processed_by = current_user.id
    db.session.commit()

    return ok(message=f'Demande de prix rejetée pour {pr.engineer.username}.', level='info')


# ── Producer/Arranger ─────────────────────────────────────────────────────────

@admin_api_bp.route('/producer-arranger/<int:user_id>/approve', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def approve_producer_arranger(user_id, current_user):
    user = db.get_or_404(User, user_id)
    if not user.producer_arranger_request_submitted:
        return ser_err(f"{user.username} n'a pas demandé la certification.")
    if not user.is_mixmaster_engineer:
        return ser_err(f"{user.username} doit d'abord être mix/master engineer.")

    user.is_certified_producer_arranger = True
    db.session.commit()
    return ok(message=f'{user.username} certifié comme producteur/arrangeur.', level='info')


@admin_api_bp.route('/producer-arranger/<int:user_id>/revoke', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def revoke_producer_arranger(user_id, current_user):
    user = db.get_or_404(User, user_id)
    user.is_certified_producer_arranger        = False
    user.producer_arranger_request_submitted   = False
    db.session.commit()
    return ok(message=f'Certification Producteur/Arrangeur de {user.username} révoquée.', level='info')


@admin_api_bp.route('/producer-arranger/<int:user_id>/reject', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def reject_producer_arranger(user_id, current_user):
    user = db.get_or_404(User, user_id)
    user.producer_arranger_request_submitted = False
    db.session.commit()
    return ok(message=f'Demande Producteur/Arrangeur de {user.username} rejetée.', level='info')


# ── Master Engineer ───────────────────────────────────────────────────────────

@admin_api_bp.route('/engineers/<int:user_id>/certify-master', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def certify_master_engineer(user_id, current_user):
    """Certifie un ingénieur comme 'Master Engineer' (mastering validé par admin)."""
    user = db.get_or_404(User, user_id)
    if not user.is_mixmaster_engineer:
        return ser_err(f"{user.username} doit d'abord être certifié Mix Engineer.")
    user.is_certified_master_engineer = True
    db.session.commit()
    return ok(message=f'{user.username} certifié comme Master Engineer.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/revoke-master', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def revoke_master_engineer(user_id, current_user):
    """Révoque la certification Master Engineer (admin-granted uniquement)."""
    user = db.get_or_404(User, user_id)
    user.is_certified_master_engineer = False
    db.session.commit()
    return ok(message=f'Certification Master Engineer de {user.username} révoquée.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/approve-master-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def approve_master_sample(user_id, current_user):
    """Approuve l'échantillon mastering → certifie is_certified_master_engineer."""
    user = db.get_or_404(User, user_id)
    if not user.master_sample_submitted:
        return ser_err(f"Aucune soumission mastering en attente pour {user.username}.")
    user.is_certified_master_engineer = True
    user.master_sample_submitted      = False
    db.session.commit()
    return ok(message=f'{user.username} certifié Master Engineer.', level='info')


@admin_api_bp.route('/engineers/<int:user_id>/reject-master-sample', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def reject_master_sample(user_id, current_user):
    """Rejette l'échantillon mastering et efface la soumission."""
    user = db.get_or_404(User, user_id)
    user.master_sample_submitted  = False
    user.master_sample_raw        = None
    user.master_sample_processed  = None
    db.session.commit()
    return ok(message=f'Soumission mastering de {user.username} rejetée.', level='info')


# ── Contracts (CUD) ───────────────────────────────────────────────────────────

@admin_api_bp.route('/contracts/create', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_create_contract(current_user):
    """Admin crée un contrat manuel entre un compositeur et un acheteur."""
    data = request.get_json(silent=True) or {}

    track_id     = data.get('track_id')
    client_id    = data.get('client_id')
    price        = data.get('price')
    is_exclusive = bool(data.get('is_exclusive', False))
    territory    = data.get('territory', 'France').strip()
    duration     = data.get('duration', '3 ans').strip()

    if not all([track_id, client_id, price is not None]):
        return ser_err('track_id, client_id et price sont requis.')

    track  = db.get_or_404(Track, track_id)
    client = db.get_or_404(User, client_id)

    if not track.composer_id:
        return ser_err("Ce track n'a pas de compositeur.")

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

    composer_name = track.composer_user.username if track.composer_user else '?'
    return ok(
        {'contract_id': contract.id},
        message=f'Contrat créé entre {composer_name} et {client.username} pour "{track.title}".',
        level='info',
    )


# ── Categories (CUD) ──────────────────────────────────────────────────────────

@admin_api_bp.route('/categories', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def create_category(current_user):
    data  = request.get_json(silent=True) or {}
    name  = data.get('name', '').strip()
    color = data.get('color', '#6b7280').strip()

    if not name:
        return ser_err('Le nom est requis.')

    cat = Category(name=name)
    if hasattr(cat, 'color'):
        cat.color = color
    db.session.add(cat)
    db.session.commit()

    return ok({'category': {'id': cat.id, 'name': cat.name, 'color': color, 'tags': []}},
              message=f'Catégorie "{name}" créée.', level='info')


@admin_api_bp.route('/categories/<int:cat_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
def edit_category(cat_id, current_user):
    cat  = db.get_or_404(Category, cat_id)
    data = request.get_json(silent=True) or {}

    if 'name'        in data: cat.name        = data['name'].strip()
    if 'color'       in data and hasattr(cat, 'color'):       cat.color       = data['color'].strip()
    if 'description' in data and hasattr(cat, 'description'): cat.description = data['description'] or None

    db.session.commit()
    return ok(message=f'Catégorie "{cat.name}" mise à jour.', level='info')


@admin_api_bp.route('/categories/<int:cat_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
def delete_category(cat_id, current_user):
    cat  = db.get_or_404(Category, cat_id)
    name = cat.name
    db.session.delete(cat)
    db.session.commit()
    return ok(message=f'Catégorie "{name}" supprimée.', level='info')


# ── Tags (CUD) ────────────────────────────────────────────────────────────────

@admin_api_bp.route('/tags', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def create_tag(current_user):
    data        = request.get_json(silent=True) or {}
    name        = data.get('name', '').strip()
    category_id = data.get('category_id')

    if not name:
        return ser_err('Le nom est requis.')

    tag = Tag(name=name, category_id=category_id)
    db.session.add(tag)
    db.session.commit()

    return ok({'tag': {'id': tag.id, 'name': tag.name}},
              message=f'Tag "{name}" créé.', level='info')


@admin_api_bp.route('/tags/<int:tag_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
def edit_tag(tag_id, current_user):
    tag  = db.get_or_404(Tag, tag_id)
    data = request.get_json(silent=True) or {}

    if 'name'        in data: tag.name        = data['name'].strip()
    if 'category_id' in data: tag.category_id = data['category_id']

    db.session.commit()
    return ok(message=f'Tag "{tag.name}" mis à jour.', level='info')


@admin_api_bp.route('/tags/<int:tag_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
def delete_tag(tag_id, current_user):
    tag  = db.get_or_404(Tag, tag_id)
    name = tag.name
    db.session.delete(tag)
    db.session.commit()
    return ok(message=f'Tag "{name}" supprimé.', level='info')


# =============================================================================
# SIMILAR ARTISTS — Admin CRUD
# =============================================================================

@admin_api_bp.route('/similar-artists', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_similar_artists(current_user):
    artists = db.session.query(SimilarArtist).order_by(SimilarArtist.scene, SimilarArtist.name).all()
    by_scene: dict[str, list] = {}
    for a in artists:
        by_scene.setdefault(a.scene, []).append({'id': a.id, 'name': a.name})
    scenes = [{'name': s, 'artists': lst} for s, lst in sorted(by_scene.items())]
    return ok({'scenes': scenes, 'total': len(artists)})


@admin_api_bp.route('/similar-artists', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def create_similar_artist(current_user):
    data = request.get_json(silent=True) or {}
    name  = (data.get('name') or '').strip()
    scene = (data.get('scene') or '').strip()
    if not name or not scene:
        return err('Le nom et la scène sont requis.')
    if db.session.query(SimilarArtist).filter_by(name=name).first():
        return err(f'L\'artiste "{name}" existe déjà.')
    artist = SimilarArtist(name=name, scene=scene)
    db.session.add(artist)
    db.session.commit()
    return ok({'id': artist.id, 'name': artist.name, 'scene': artist.scene},
              message=f'Artiste "{name}" ajouté.')


@admin_api_bp.route('/similar-artists/<int:artist_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
def update_similar_artist(artist_id, current_user):
    artist = db.get_or_404(SimilarArtist, artist_id)
    data   = request.get_json(silent=True) or {}
    if 'name' in data:
        artist.name  = (data['name'] or '').strip() or artist.name
    if 'scene' in data:
        artist.scene = (data['scene'] or '').strip() or artist.scene
    db.session.commit()
    return ok({'id': artist.id, 'name': artist.name, 'scene': artist.scene})


@admin_api_bp.route('/similar-artists/<int:artist_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
def delete_similar_artist(artist_id, current_user):
    artist = db.get_or_404(SimilarArtist, artist_id)
    name   = artist.name
    db.session.delete(artist)
    db.session.commit()
    return ok(message=f'Artiste "{name}" supprimé.', level='info')


# =============================================================================
# CONTRACT BUILDER — Admin CRUD (groupes et clauses)
# =============================================================================

def _cb_group_dto(g, include_clauses=False) -> dict:
    d = {
        'id':          g.id,
        'name':        g.name,
        'description': g.description,
        'tooltip':     g.tooltip,
        'sort_order':  g.sort_order,
        'is_active':   g.is_active,
    }
    if include_clauses:
        d['clauses'] = [_cb_clause_dto(c) for c in g.clauses]
    return d


def _cb_clause_dto(c) -> dict:
    return {
        'id':                    c.id,
        'group_id':              c.group_id,
        'name':                  c.name,
        'description':           c.description,
        'tooltip_short':         c.tooltip_short,
        'tooltip_long':          c.tooltip_long,
        'clause_type':           c.clause_type.value,
        'options':               c.options,
        'default_value':         c.default_value,
        'is_required':           c.is_required,
        'is_enabled_by_default': c.is_enabled_by_default,
        'sort_order':            c.sort_order,
        'is_active':             c.is_active,
        'legal_reference':       c.legal_reference,
        'example_text':          c.example_text,
        'tooltip_plain':         c.tooltip_plain,
    }


# ── Groupes ───────────────────────────────────────────────────────────────────

@admin_api_bp.route('/contract-builder/groups', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_list_groups(current_user):
    groups = (
        db.session.query(ContractClauseGroup)
        .order_by(ContractClauseGroup.sort_order)
        .all()
    )
    return jsonify({'success': True, 'data': {'groups': [_cb_group_dto(g, include_clauses=True) for g in groups]}})


@admin_api_bp.route('/contract-builder/groups', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_create_group(current_user):
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le nom est requis.'}}), 400

    max_order = db.session.query(db.func.max(ContractClauseGroup.sort_order)).scalar() or -1
    g = ContractClauseGroup(
        name        = name,
        description = data.get('description'),
        tooltip     = data.get('tooltip'),
        sort_order  = max_order + 1,
        is_active   = data.get('is_active', True),
    )
    db.session.add(g)
    db.session.commit()
    return jsonify({'success': True, 'data': {'group': _cb_group_dto(g)}}), 201


@admin_api_bp.route('/contract-builder/groups/<int:group_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_update_group(current_user, group_id):
    g = db.get_or_404(ContractClauseGroup, group_id)
    data = request.get_json(silent=True) or {}
    if 'name' in data:
        g.name = (data['name'] or '').strip() or g.name
    if 'description' in data:
        g.description = data['description']
    if 'tooltip' in data:
        g.tooltip = data['tooltip']
    if 'sort_order' in data:
        g.sort_order = int(data['sort_order'])
    if 'is_active' in data:
        g.is_active = bool(data['is_active'])
    db.session.commit()
    return jsonify({'success': True, 'data': {'group': _cb_group_dto(g)}})


@admin_api_bp.route('/contract-builder/groups/<int:group_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_delete_group(current_user, group_id):
    g = db.get_or_404(ContractClauseGroup, group_id)
    # Soft delete si des valeurs utilisateur référencent les clauses du groupe
    has_refs = (
        db.session.query(UserContractValue)
        .join(ContractClause, UserContractValue.clause_id == ContractClause.id)
        .filter(ContractClause.group_id == group_id)
        .first()
    )
    if has_refs:
        g.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'feedback': {'level': 'info', 'message': 'Groupe désactivé (des contrats y font référence).'}})
    db.session.delete(g)
    db.session.commit()
    return jsonify({'success': True})


@admin_api_bp.route('/contract-builder/groups/reorder', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_reorder_groups(current_user):
    items = request.get_json(silent=True) or []
    for item in items:
        g = db.session.get(ContractClauseGroup, item.get('id'))
        if g:
            g.sort_order = int(item.get('sort_order', g.sort_order))
    db.session.commit()
    return jsonify({'success': True})


# ── Clauses ───────────────────────────────────────────────────────────────────

@admin_api_bp.route('/contract-builder/groups/<int:group_id>/clauses', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_list_clauses(current_user, group_id):
    db.get_or_404(ContractClauseGroup, group_id)
    clauses = (
        db.session.query(ContractClause)
        .filter_by(group_id=group_id)
        .order_by(ContractClause.sort_order)
        .all()
    )
    return jsonify({'success': True, 'data': {'clauses': [_cb_clause_dto(c) for c in clauses]}})


@admin_api_bp.route('/contract-builder/groups/<int:group_id>/clauses', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_create_clause(current_user, group_id):
    db.get_or_404(ContractClauseGroup, group_id)
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Le nom est requis.'}}), 400

    try:
        ctype = ClauseTypeEnum(data.get('clause_type', 'text'))
    except ValueError:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Type de clause invalide.'}}), 400

    max_order = (
        db.session.query(db.func.max(ContractClause.sort_order))
        .filter_by(group_id=group_id).scalar()
    ) or -1

    c = ContractClause(
        group_id              = group_id,
        name                  = name,
        description           = data.get('description'),
        tooltip_short         = data.get('tooltip_short'),
        tooltip_long          = data.get('tooltip_long'),
        clause_type           = ctype,
        options               = data.get('options'),
        default_value         = data.get('default_value'),
        is_required           = bool(data.get('is_required', False)),
        is_enabled_by_default = bool(data.get('is_enabled_by_default', True)),
        sort_order            = max_order + 1,
        is_active             = bool(data.get('is_active', True)),
        legal_reference       = data.get('legal_reference'),
        tooltip_plain         = data.get('tooltip_plain'),
    )
    db.session.add(c)
    db.session.commit()
    return jsonify({'success': True, 'data': {'clause': _cb_clause_dto(c)}}), 201


@admin_api_bp.route('/contract-builder/clauses/<int:clause_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_update_clause(current_user, clause_id):
    c = db.get_or_404(ContractClause, clause_id)
    data = request.get_json(silent=True) or {}

    if 'name' in data:
        c.name = (data['name'] or '').strip() or c.name
    if 'description' in data:
        c.description = data['description']
    if 'tooltip_short' in data:
        c.tooltip_short = data['tooltip_short']
    if 'tooltip_long' in data:
        c.tooltip_long = data['tooltip_long']
    if 'clause_type' in data:
        try:
            c.clause_type = ClauseTypeEnum(data['clause_type'])
        except ValueError:
            pass
    if 'options' in data:
        c.options = data['options']
    if 'default_value' in data:
        c.default_value = data['default_value']
    if 'is_required' in data:
        c.is_required = bool(data['is_required'])
    if 'is_enabled_by_default' in data:
        c.is_enabled_by_default = bool(data['is_enabled_by_default'])
    if 'sort_order' in data:
        c.sort_order = int(data['sort_order'])
    if 'is_active' in data:
        c.is_active = bool(data['is_active'])
    if 'legal_reference' in data:
        c.legal_reference = data['legal_reference']
    if 'example_text' in data:
        c.example_text = data['example_text'] or None
    if 'tooltip_plain' in data:
        c.tooltip_plain = data['tooltip_plain'] or None

    db.session.commit()
    return jsonify({'success': True, 'data': {'clause': _cb_clause_dto(c)}})


@admin_api_bp.route('/contract-builder/clauses/<int:clause_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_delete_clause(current_user, clause_id):
    c = db.get_or_404(ContractClause, clause_id)
    has_refs = db.session.query(UserContractValue).filter_by(clause_id=clause_id).first()
    if has_refs:
        c.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'feedback': {'level': 'info', 'message': 'Clause désactivée (des contrats y font référence).'}})
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})


@admin_api_bp.route('/recommendation-stats', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def get_recommendation_stats(current_user):
    """Statistiques de l'algorithme de recommandation — lisibles depuis l'admin."""
    from collections import defaultdict
    from extensions import redis_client

    seven_days_ago = datetime.now() - timedelta(days=7)

    total_events = db.session.query(ListenEvent).count()
    active_users = (
        db.session.query(distinct(ListenEvent.user_id))
        .filter(ListenEvent.created_at >= seven_days_ago)
        .count()
    )

    # Top keys (par nombre d'écoutes positives)
    key_counts: dict[str, int] = defaultdict(int)
    tag_counts: dict[str, int] = defaultdict(int)
    for ev in db.session.query(ListenEvent).filter(ListenEvent.completion_ratio >= 0.30).all():
        if ev.track and ev.track.key:
            key_counts[ev.track.key] += 1
        if ev.track:
            for tag in ev.track.tags:
                tag_counts[tag.name] += 1

    top_keys = sorted(key_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Top corrélations clés depuis Redis
    top_correlations = []
    if redis_client:
        try:
            for redis_key in redis_client.scan_iter('laprod:reco:key_corr:*'):
                parts = redis_key.split(':', maxsplit=4)
                if len(parts) == 5:
                    prob = float(redis_client.get(redis_key) or 0)
                    top_correlations.append({
                        'from': parts[3],
                        'to': parts[4],
                        'probability': round(prob, 3),
                    })
        except Exception:
            pass
    top_correlations.sort(key=lambda x: x['probability'], reverse=True)
    top_correlations = top_correlations[:20]

    # Top artistes similaires (par écoutes positives)
    artist_counts: dict[str, int] = defaultdict(int)
    for ev in db.session.query(ListenEvent).filter(ListenEvent.completion_ratio >= 0.30).all():
        if ev.track:
            for a in ev.track.similar_artists:
                artist_counts[a.name] += 1
    top_artists = sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    # Corrélations artiste→artiste depuis Redis
    artist_correlations = []
    if redis_client:
        try:
            for redis_key in redis_client.scan_iter('laprod:reco:similar_artist_corr:*'):
                parts = redis_key.split(':', maxsplit=5)
                if len(parts) == 6:
                    prob = float(redis_client.get(redis_key) or 0)
                    artist_correlations.append({
                        'from': parts[4],
                        'to': parts[5],
                        'probability': round(prob, 3),
                    })
        except Exception:
            pass
    artist_correlations.sort(key=lambda x: x['probability'], reverse=True)
    artist_correlations = artist_correlations[:20]

    return ok({
        'total_listen_events': total_events,
        'active_users_last_7d': active_users,
        'top_keys': top_keys,
        'top_tags': top_tags,
        'top_correlations': top_correlations,
        'top_artists': top_artists,
        'artist_correlations': artist_correlations,
    })


@admin_api_bp.route('/contract-builder/clauses/reorder', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_admin
def cb_reorder_clauses(current_user):
    items = request.get_json(silent=True) or []
    for item in items:
        c = db.session.get(ContractClause, item.get('id'))
        if c:
            c.sort_order = int(item.get('sort_order', c.sort_order))
    db.session.commit()
    return jsonify({'success': True})
