"""
Dashboard API — GET endpoints pour les espaces Beatmaker, Artiste et Mix Engineer
"""
from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import select, func
from extensions import db, csrf, limiter
from models import User, Track, Purchase, Topline, MixMasterRequest, Favorite, ListeningHistory

dashboard_api_bp = Blueprint('dashboard_api', __name__, url_prefix='/dashboard')


# ─── Beatmaker ────────────────────────────────────────────────────────────────

@dashboard_api_bp.route('/beatmaker', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_beatmaker_dashboard():
    """Espace beatmaker : stats, liste des beats, historique des ventes."""
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)

    if not user.is_beatmaker:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé.'}}), 403

    # ── Tracks du compositeur ─────────────────────────────────────────────────
    tracks = db.session.scalars(
        select(Track).where(Track.composer_id == user_id).order_by(Track.created_at.desc())
    ).all()

    # ── Ventes (50 dernières) ─────────────────────────────────────────────────
    sales = db.session.scalars(
        select(Purchase)
        .join(Track, Purchase.track_id == Track.id)
        .where(Track.composer_id == user_id)
        .order_by(Purchase.created_at.desc())
        .limit(50)
    ).all()

    total_revenue = sum(s.composer_revenue for s in sales)
    sales_count   = len(sales)

    # ── Sales par track (count) ───────────────────────────────────────────────
    sales_by_track: dict[int, int] = {}
    for s in sales:
        sales_by_track[s.track_id] = sales_by_track.get(s.track_id, 0) + 1

    tracks_data = [
        {
            'id':           t.id,
            'title':        t.title,
            'image_file':   t.image_file,
            'is_approved':  t.is_approved,
            'created_at':   t.created_at.isoformat(),
            'bpm':          t.bpm,
            'key':          t.key,
            'style':        t.style,
            'price_mp3':    t.price_mp3,
            'price_wav':    t.price_wav,
            'price_stems':  t.price_stems,
            'has_mp3':      bool(t.file_mp3),
            'has_wav':      bool(t.file_wav),
            'has_stems':    bool(t.file_stems),
            'sales_count':  sales_by_track.get(t.id, 0),
            'stream_url':   f'/stream/tracks/{t.id}/preview',
        }
        for t in tracks
    ]

    sales_data = [
        {
            'id':               s.id,
            'track_id':         s.track_id,
            'track_title':      s.track.title if s.track else None,
            'track_image':      s.track.image_file if s.track else None,
            'buyer_name':       s.buyer_name,
            'format':           s.format_purchased,
            'price_paid':       s.price_paid,
            'track_price':      s.track_price,
            'contract_price':   s.contract_price,
            'platform_fee':     s.platform_fee,
            'composer_revenue': s.composer_revenue,
            'created_at':       s.created_at.isoformat(),
        }
        for s in sales
    ]

    return jsonify({
        'success': True,
        'data': {
            'stats': {
                'total_revenue':        round(total_revenue, 2),
                'sales_count':          sales_count,
                'tracks_count':         len(tracks),
                'tracks_approved':      sum(1 for t in tracks if t.is_approved),
                'tracks_pending':       sum(1 for t in tracks if not t.is_approved),
                'upload_tokens':        user.upload_track_tokens,
            },
            'tracks': tracks_data,
            'sales':  sales_data,
        },
    }), 200


# ─── Artiste ──────────────────────────────────────────────────────────────────

@dashboard_api_bp.route('/artist', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_artist_dashboard():
    """Espace artiste : toplines soumises, favoris, historique d'écoute, tokens."""
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)

    if not user.is_artist:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé.'}}), 403

    # ── Toplines ──────────────────────────────────────────────────────────────
    toplines = db.session.scalars(
        select(Topline)
        .where(Topline.artist_id == user_id)
        .order_by(Topline.created_at.desc())
    ).all()

    toplines_data = [
        {
            'id':           tl.id,
            'track_id':     tl.track_id,
            'track_title':  tl.track.title if tl.track else None,
            'track_image':  tl.track.image_file if tl.track else None,
            'description':  tl.description,
            'is_published': tl.is_published,
            'created_at':   tl.created_at.isoformat(),
            'stream_url':   f'/stream/toplines/{tl.id}',
        }
        for tl in toplines
    ]

    # ── Favoris ───────────────────────────────────────────────────────────────
    favorites = db.session.scalars(
        select(Favorite)
        .where(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
    ).all()

    favorites_data = [
        {
            'id':           fav.track_id,
            'title':        fav.track.title if fav.track else None,
            'image_file':   fav.track.image_file if fav.track else None,
            'composer':     fav.track.composer_user.username if fav.track and fav.track.composer_user else None,
            'stream_url':   f'/stream/tracks/{fav.track_id}/preview',
            'favorited_at': fav.created_at.isoformat(),
        }
        for fav in favorites
        if fav.track
    ]

    # ── Historique d'écoute (10 derniers uniques) ─────────────────────────────
    history = db.session.scalars(
        select(ListeningHistory)
        .where(ListeningHistory.user_id == user_id)
        .order_by(ListeningHistory.listened_at.desc())
        .limit(10)
    ).all()

    history_data = [
        {
            'id':          h.track_id,
            'title':       h.track.title if h.track else None,
            'image_file':  h.track.image_file if h.track else None,
            'composer':    h.track.composer_user.username if h.track and h.track.composer_user else None,
            'stream_url':  f'/stream/tracks/{h.track_id}/preview',
            'listened_at': h.listened_at.isoformat(),
        }
        for h in history
        if h.track
    ]

    return jsonify({
        'success': True,
        'data': {
            'stats': {
                'toplines_count':     len(toplines),
                'toplines_published': sum(1 for tl in toplines if tl.is_published),
                'favorites_count':    len(favorites_data),
                'topline_tokens':     user.topline_tokens,
            },
            'toplines':  toplines_data,
            'favorites': favorites_data,
            'history':   history_data,
        },
    }), 200


# ─── Mix Engineer ─────────────────────────────────────────────────────────────

@dashboard_api_bp.route('/mix-engineer', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_mix_engineer_dashboard():
    """Espace mix engineer : commandes par statut, stats revenus."""
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)

    if not user.is_mix_engineer:
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Accès refusé.'}}), 403

    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.engineer_id == user_id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()

    ACTIVE_STATUSES    = {'accepted', 'processing', 'delivered'}
    REVISION_STATUSES  = {'revision1', 'revision2'}
    COMPLETED_STATUSES = {'completed'}
    REFUSED_STATUSES   = {'rejected', 'refunded'}

    def order_dict(o: MixMasterRequest) -> dict:
        return {
            'id':              o.id,
            'title':           o.title,
            'artist_username': o.artist.username if o.artist else None,
            'artist_image':    o.artist.profile_image if o.artist else None,
            'status':          o.status,
            'total_price':     o.total_price,
            'deposit_amount':  o.deposit_amount,
            'engineer_revenue': o.engineer_revenue,
            'services': {
                'cleaning':  o.service_cleaning,
                'effects':   o.service_effects,
                'artistic':  o.service_artistic,
                'mastering': o.service_mastering,
            },
            'created_at':      o.created_at.isoformat(),
            'accepted_at':     o.accepted_at.isoformat() if o.accepted_at else None,
            'deadline':        o.deadline.isoformat() if o.deadline else None,
            'delivered_at':    o.delivered_at.isoformat() if o.delivered_at else None,
            'completed_at':    o.completed_at.isoformat() if o.completed_at else None,
        }

    completed_orders  = [o for o in orders if o.status in COMPLETED_STATUSES]
    total_revenue     = sum(o.engineer_revenue or 0 for o in completed_orders)

    return jsonify({
        'success': True,
        'data': {
            'stats': {
                'total_revenue':    round(total_revenue, 2),
                'completed_count':  len(completed_orders),
                'active_count':     sum(1 for o in orders if o.status in ACTIVE_STATUSES),
                'pending_count':    sum(1 for o in orders if o.status == 'awaiting_acceptance'),
                'reference_price':  user.mixmaster_reference_price,
                'price_min':        user.mixmaster_price_min,
            },
            'orders': {
                'awaiting':  [order_dict(o) for o in orders if o.status == 'awaiting_acceptance'],
                'active':    [order_dict(o) for o in orders if o.status in ACTIVE_STATUSES],
                'revisions': [order_dict(o) for o in orders if o.status in REVISION_STATUSES],
                'completed': [order_dict(o) for o in orders if o.status in COMPLETED_STATUSES],
                'refused':   [order_dict(o) for o in orders if o.status in REFUSED_STATUSES],
            },
        },
    }), 200
