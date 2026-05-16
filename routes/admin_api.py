"""
Admin API — GET endpoints pour l'administration
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import select
from extensions import db, csrf
from models import (
    Track, User, Tag, Category, MixMasterRequest, Contract, PriceChangeRequest,
    ContractClauseGroup, ContractClause, UserContractValue, ClauseTypeEnum,
)

admin_api_bp = Blueprint('admin_api', __name__, url_prefix='/api/admin')


def _require_admin():
    """Retourne l'utilisateur admin ou lève une réponse 403."""
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)
    if not user.is_admin:
        return None, (jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès réservé aux administrateurs.'}}), 403)
    return user, None


# ── Dashboard stats ───────────────────────────────────────────────────────────

@admin_api_bp.route('/stats', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_stats():
    user, err = _require_admin()
    if err:
        return err

    pending_tracks_count  = db.session.query(Track).filter_by(is_approved=False).count()
    approved_tracks_count = db.session.query(Track).filter_by(is_approved=True).count()
    total_tracks          = db.session.query(Track).count()

    total_users     = db.session.query(User).filter_by(account_status='active').count()
    premium_users   = db.session.query(User).filter_by(is_premium=True, account_status='active').count()
    beatmakers_count = db.session.query(User).filter_by(is_beatmaker=True, account_status='active').count()
    artists_count   = db.session.query(User).filter_by(is_artist=True, account_status='active').count()
    engineers_count = db.session.query(User).filter_by(is_mixmaster_engineer=True, account_status='active').count()

    total_contracts    = db.session.query(Contract).count()
    exclusive_contracts = db.session.query(Contract).filter_by(is_exclusive=True).count()
    total_revenue      = db.session.scalar(
        select(db.func.sum(Contract.price))
    ) or 0

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

    return jsonify({
        'success': True,
        'data': {
            'tracks': {
                'pending':  pending_tracks_count,
                'approved': approved_tracks_count,
                'total':    total_tracks,
            },
            'users': {
                'total':     total_users,
                'premium':   premium_users,
                'beatmakers': beatmakers_count,
                'artists':   artists_count,
                'engineers': engineers_count,
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
                    'profile_image': u.profile_image,
                    'created_at':    u.created_at.isoformat() if u.created_at else None,
                }
                for u in recent_users
            ],
        }
    })


# ── Tracks ────────────────────────────────────────────────────────────────────

@admin_api_bp.route('/tracks', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_tracks():
    user, err = _require_admin()
    if err:
        return err

    status = request.args.get('status', 'pending')

    query = select(Track).order_by(Track.created_at.desc())
    if status == 'pending':
        query = query.where(Track.is_approved == False)
    elif status == 'approved':
        query = query.where(Track.is_approved == True)

    tracks = db.session.scalars(query).all()

    pending_count  = db.session.query(Track).filter_by(is_approved=False).count()
    approved_count = db.session.query(Track).filter_by(is_approved=True).count()

    return jsonify({
        'success': True,
        'data': {
            'tracks': [
                {
                    'id':             t.id,
                    'title':          t.title,
                    'bpm':            t.bpm,
                    'key':            t.key,
                    'style':          t.style,
                    'image_file':     t.image_file,
                    'stream_url':     t.stream_url,
                    'price_mp3':      t.price_mp3,
                    'price_wav':      t.price_wav,
                    'price_stems':    t.price_stems,
                    'is_approved':    t.is_approved,
                    'purchase_count': t.purchase_count,
                    'created_at':     t.created_at.isoformat() if t.created_at else None,
                    'approved_at':    t.approved_at.isoformat() if t.approved_at else None,
                    'composer': {
                        'id':            t.composer_user.id,
                        'username':      t.composer_user.username,
                        'profile_image': t.composer_user.profile_image,
                    } if t.composer_user else None,
                    'tags': [
                        {'id': tag.id, 'name': tag.name, 'category': tag.category_obj.name if tag.category_obj else None}
                        for tag in t.tags
                    ],
                }
                for t in tracks
            ],
            'pending_count':  pending_count,
            'approved_count': approved_count,
        }
    })


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_api_bp.route('/users', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_users():
    user, err = _require_admin()
    if err:
        return err

    user_type = request.args.get('user_type', 'all')

    query = select(User).order_by(User.created_at.desc())
    if user_type == 'beatmakers':
        query = query.where(User.is_beatmaker == True)
    elif user_type == 'artists':
        query = query.where(User.is_artist == True)
    elif user_type == 'engineers':
        query = query.where(User.is_mixmaster_engineer == True)

    users = db.session.scalars(query).all()

    users_data = []
    for u in users:
        tracks_count    = db.session.query(Track).filter_by(composer_id=u.id).count()
        contracts_count = db.session.query(Contract).filter_by(client_id=u.id).count()
        mm_count        = db.session.query(MixMasterRequest).filter_by(engineer_id=u.id).count()
        users_data.append({
            'id':              u.id,
            'username':        u.username,
            'email':           u.email,
            'profile_image':   u.profile_image,
            'account_status':  u.account_status,
            'is_admin':        u.is_admin,
            'is_beatmaker':    u.is_beatmaker,
            'is_artist':       u.is_artist,
            'is_mix_engineer': u.is_mix_engineer,
            'is_mixmaster_engineer': u.is_mixmaster_engineer,
            'is_certified_producer_arranger': u.is_certified_producer_arranger,
            'producer_arranger_request_submitted': u.producer_arranger_request_submitted,
            'is_premium':      u.is_premium,
            'upload_track_tokens': u.upload_track_tokens,
            'topline_tokens':  u.topline_tokens,
            'created_at':      u.created_at.isoformat() if u.created_at else None,
            'tracks_count':    tracks_count,
            'contracts_count': contracts_count,
            'mm_count':        mm_count,
        })

    all_count        = db.session.query(User).count()
    beatmakers_count = db.session.query(User).filter_by(is_beatmaker=True).count()
    artists_count    = db.session.query(User).filter_by(is_artist=True).count()
    engineers_count  = db.session.query(User).filter_by(is_mixmaster_engineer=True).count()

    return jsonify({
        'success': True,
        'data': {
            'users': users_data,
            'counts': {
                'all':        all_count,
                'beatmakers': beatmakers_count,
                'artists':    artists_count,
                'engineers':  engineers_count,
            },
        }
    })


# ── Engineers ─────────────────────────────────────────────────────────────────

@admin_api_bp.route('/engineers', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_engineers():
    user, err = _require_admin()
    if err:
        return err

    def _user_dict(u):
        return {
            'id':              u.id,
            'username':        u.username,
            'email':           u.email,
            'profile_image':   u.profile_image,
            'mixmaster_reference_price': u.mixmaster_reference_price,
            'mixmaster_price_min':       u.mixmaster_price_min,
            'mixmaster_bio':             u.mixmaster_bio,
            'mixmaster_sample_raw':      u.mixmaster_sample_raw,
            'mixmaster_sample_processed': u.mixmaster_sample_processed,
            'is_certified_producer_arranger': u.is_certified_producer_arranger,
            'producer_arranger_request_submitted': u.producer_arranger_request_submitted,
            'is_mixmaster_engineer': u.is_mixmaster_engineer,
            'created_at': u.created_at.isoformat() if u.created_at else None,
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

    price_requests = db.session.scalars(
        select(PriceChangeRequest).where(PriceChangeRequest.status == 'pending')
        .order_by(PriceChangeRequest.created_at.desc())
    ).all()

    return jsonify({
        'success': True,
        'data': {
            'certified':   [_user_dict(u) for u in certified],
            'pending':     [_user_dict(u) for u in pending],
            'pa_requests': [_user_dict(u) for u in pa_requests],
            'price_requests': [
                {
                    'id':                    pr.id,
                    'engineer_id':           pr.engineer_id,
                    'engineer_username':     pr.engineer.username if pr.engineer else None,
                    'current_reference_price': pr.engineer.mixmaster_reference_price if pr.engineer else None,
                    'current_price_min':       pr.engineer.mixmaster_price_min if pr.engineer else None,
                    'new_reference_price':   pr.new_reference_price,
                    'new_price_min':         pr.new_price_min,
                    'created_at':            pr.created_at.isoformat() if pr.created_at else None,
                }
                for pr in price_requests
            ],
        }
    })


# ── Contracts ─────────────────────────────────────────────────────────────────

@admin_api_bp.route('/contracts', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_contracts():
    user, err = _require_admin()
    if err:
        return err

    contracts = db.session.scalars(
        select(Contract).order_by(Contract.created_at.desc())
    ).all()

    exclusive_count     = db.session.query(Contract).filter_by(is_exclusive=True).count()
    non_exclusive_count = db.session.query(Contract).filter_by(is_exclusive=False).count()
    total_revenue       = sum(c.price for c in contracts)

    return jsonify({
        'success': True,
        'data': {
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
        }
    })


# ── Transactions (Mix/Master) ─────────────────────────────────────────────────

@admin_api_bp.route('/transactions', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_transactions():
    user, err = _require_admin()
    if err:
        return err

    status = request.args.get('status', 'all')

    query = select(MixMasterRequest).order_by(MixMasterRequest.created_at.desc())
    if status == 'in_progress':
        query = query.where(MixMasterRequest.status.in_(['accepted', 'processing', 'delivered']))
    elif status == 'completed':
        query = query.where(MixMasterRequest.status == 'completed').order_by(MixMasterRequest.completed_at.desc())
    elif status == 'awaiting':
        query = query.where(MixMasterRequest.status == 'awaiting_acceptance')

    transactions = db.session.scalars(query).all()

    awaiting_count   = db.session.query(MixMasterRequest).filter_by(status='awaiting_acceptance').count()
    in_progress_count = db.session.query(MixMasterRequest).filter(
        MixMasterRequest.status.in_(['accepted', 'processing', 'delivered'])
    ).count()
    completed_count  = db.session.query(MixMasterRequest).filter_by(status='completed').count()
    all_count        = db.session.query(MixMasterRequest).count()
    total_revenue    = db.session.scalar(
        select(db.func.sum(MixMasterRequest.total_price)).where(MixMasterRequest.status == 'completed')
    ) or 0

    return jsonify({
        'success': True,
        'data': {
            'transactions': [
                {
                    'id':          t.id,
                    'status':      t.status,
                    'total_price': t.total_price,
                    'created_at':  t.created_at.isoformat() if t.created_at else None,
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
        }
    })


# ── Engineer search (direct certification tab) ────────────────────────────────

@admin_api_bp.route('/engineers/all-mix', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_all_mix_engineers():
    """Tous les utilisateurs avec is_mix_engineer=True (certifiés ou non) — pour certification directe admin."""
    _, err = _require_admin()
    if err:
        return err

    users = db.session.scalars(
        select(User).where(User.is_mix_engineer == True).order_by(User.username)
    ).all()

    def _u(u):
        return {
            'id':              u.id,
            'username':        u.username,
            'email':           u.email,
            'profile_image':   u.profile_image,
            'is_mixmaster_engineer': u.is_mixmaster_engineer,
            'is_certified_producer_arranger': u.is_certified_producer_arranger,
            'mixmaster_reference_price': u.mixmaster_reference_price,
            'mixmaster_price_min':       u.mixmaster_price_min,
            'mixmaster_bio':             u.mixmaster_bio,
            'mixmaster_sample_raw':      u.mixmaster_sample_raw,
            'mixmaster_sample_processed': u.mixmaster_sample_processed,
            'created_at': u.created_at.isoformat() if u.created_at else None,
        }

    return jsonify({'success': True, 'data': {'engineers': [_u(u) for u in users]}})


# ── Search (for contract creation) ────────────────────────────────────────────

@admin_api_bp.route('/users/search', methods=['GET'])
@jwt_required()
@csrf.exempt
def search_users():
    _, err = _require_admin()
    if err:
        return err

    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'success': True, 'data': {'users': []}})

    users = db.session.scalars(
        select(User)
        .where(User.username.ilike(f'%{q}%'), User.account_status == 'active')
        .limit(10)
    ).all()

    return jsonify({'success': True, 'data': {'users': [
        {'id': u.id, 'username': u.username, 'email': u.email}
        for u in users
    ]}})


@admin_api_bp.route('/tracks/search', methods=['GET'])
@jwt_required()
@csrf.exempt
def search_tracks():
    _, err = _require_admin()
    if err:
        return err

    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify({'success': True, 'data': {'tracks': []}})

    tracks = db.session.scalars(
        select(Track)
        .where(Track.title.ilike(f'%{q}%'), Track.is_approved == True)
        .limit(10)
    ).all()

    return jsonify({'success': True, 'data': {'tracks': [
        {
            'id':    t.id,
            'title': t.title,
            'composer_username': t.composer_user.username if t.composer_user else None,
            'composer_id': t.composer_id,
            'price_mp3':   t.price_mp3,
            'price_wav':   t.price_wav,
            'price_stems': t.price_stems,
        }
        for t in tracks
    ]}})


# ── Categories & Tags ─────────────────────────────────────────────────────────

@admin_api_bp.route('/categories', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_categories():
    user, err = _require_admin()
    if err:
        return err

    categories = db.session.scalars(select(Category)).all()

    categories_data = []
    for cat in categories:
        tags = db.session.scalars(select(Tag).where(Tag.category_id == cat.id)).all()
        categories_data.append({
            'id':    cat.id,
            'name':  cat.name,
            'color': cat.color if hasattr(cat, 'color') and cat.color else '#6b7280',
            'tags': [
                {'id': tag.id, 'name': tag.name}
                for tag in tags
            ],
        })

    return jsonify({
        'success': True,
        'data': {'categories': categories_data}
    })


# ── Styles ────────────────────────────────────────────────────────────────────

@admin_api_bp.route('/styles', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_styles():
    user, err = _require_admin()
    if err:
        return err

    from models import Track
    from sqlalchemy import distinct

    styles = db.session.execute(
        select(distinct(Track.style))
        .where(Track.style.isnot(None), Track.style != '')
        .order_by(Track.style)
    ).scalars().all()

    return jsonify({'success': True, 'data': {'styles': list(styles)}})


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
def cb_list_groups():
    _, err = _require_admin()
    if err:
        return err
    groups = (
        db.session.query(ContractClauseGroup)
        .order_by(ContractClauseGroup.sort_order)
        .all()
    )
    return jsonify({'success': True, 'data': {'groups': [_cb_group_dto(g, include_clauses=True) for g in groups]}})


@admin_api_bp.route('/contract-builder/groups', methods=['POST'])
@jwt_required()
@csrf.exempt
def cb_create_group():
    _, err = _require_admin()
    if err:
        return err
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
def cb_update_group(group_id):
    _, err = _require_admin()
    if err:
        return err
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
def cb_delete_group(group_id):
    _, err = _require_admin()
    if err:
        return err
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
def cb_reorder_groups():
    _, err = _require_admin()
    if err:
        return err
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
def cb_list_clauses(group_id):
    _, err = _require_admin()
    if err:
        return err
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
def cb_create_clause(group_id):
    _, err = _require_admin()
    if err:
        return err
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
def cb_update_clause(clause_id):
    _, err = _require_admin()
    if err:
        return err
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
def cb_delete_clause(clause_id):
    _, err = _require_admin()
    if err:
        return err
    c = db.get_or_404(ContractClause, clause_id)
    has_refs = db.session.query(UserContractValue).filter_by(clause_id=clause_id).first()
    if has_refs:
        c.is_active = False
        db.session.commit()
        return jsonify({'success': True, 'feedback': {'level': 'info', 'message': 'Clause désactivée (des contrats y font référence).'}})
    db.session.delete(c)
    db.session.commit()
    return jsonify({'success': True})


@admin_api_bp.route('/contract-builder/clauses/reorder', methods=['POST'])
@jwt_required()
@csrf.exempt
def cb_reorder_clauses():
    _, err = _require_admin()
    if err:
        return err
    items = request.get_json(silent=True) or []
    for item in items:
        c = db.session.get(ContractClause, item.get('id'))
        if c:
            c.sort_order = int(item.get('sort_order', c.sort_order))
    db.session.commit()
    return jsonify({'success': True})
