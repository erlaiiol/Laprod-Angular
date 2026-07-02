"""
Dashboard API — GET endpoints pour les espaces Beatmaker, Artiste et Mix Engineer
"""
from flask import Blueprint
from flask_jwt_extended import jwt_required
from sqlalchemy import select
from extensions import db, csrf
from models import Track, Purchase, Topline, MixMasterRequest, Favorite, ListeningHistory
from serializers import ok, err, mix_order_full as ser_order_full
from utils.auth_helpers import require_user

dashboard_api_bp = Blueprint('dashboard_api', __name__, url_prefix='/api/dashboard')


# ─── Beatmaker ────────────────────────────────────────────────────────────────

@dashboard_api_bp.route('/beatmaker', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_beatmaker_dashboard(current_user):
    """Espace beatmaker : stats, liste des beats, historique des ventes."""
    if not current_user.is_beatmaker:
        return err('Accès refusé.', status=403)

    # ── Tracks du compositeur ─────────────────────────────────────────────────
    tracks = db.session.scalars(
        select(Track).where(Track.composer_id == current_user.id).order_by(Track.created_at.desc())
    ).all()

    # ── Ventes (50 dernières) ─────────────────────────────────────────────────
    sales = db.session.scalars(
        select(Purchase)
        .join(Track, Purchase.track_id == Track.id)
        .where(Track.composer_id == current_user.id)
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
            'id':              t.id,
            'title':           t.title,
            'image_file':      t.image_file,
            'is_approved':     t.is_approved,
            'is_ai_suggested': getattr(t, 'is_ai_suggested', False),
            'created_at':      t.created_at.isoformat(),
            'bpm':          t.bpm,
            'key':          t.key,
            'style':        t.style,
            'price_mp3':    float(t.price_mp3)   if t.price_mp3   is not None else None,
            'price_wav':    float(t.price_wav)   if t.price_wav   is not None else None,
            'price_stems':  float(t.price_stems) if t.price_stems is not None else None,
            'has_mp3':      bool(t.file_mp3),
            'has_wav':      bool(t.file_wav),
            'has_stems':    bool(t.file_stems),
            'sales_count':  sales_by_track.get(t.id, 0),
            'stream_url':   f'/api/stream/tracks/{t.id}/preview',
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
            'price_paid':       float(s.price_paid)       if s.price_paid       is not None else None,
            'track_price':      float(s.track_price)      if s.track_price      is not None else None,
            'contract_price':   float(s.contract_price)   if s.contract_price   is not None else None,
            'platform_fee':     float(s.platform_fee)     if s.platform_fee     is not None else None,
            'composer_revenue': float(s.composer_revenue) if s.composer_revenue is not None else None,
            'created_at':       s.created_at.isoformat(),
        }
        for s in sales
    ]

    return ok({
        'stats': {
            'total_revenue':   float(round(total_revenue, 2)),
            'sales_count':     sales_count,
            'tracks_count':    len(tracks),
            'tracks_approved': sum(1 for t in tracks if t.is_approved),
            'tracks_pending':  sum(1 for t in tracks if not t.is_approved),
            'upload_tokens':   current_user.upload_track_tokens,
        },
        'tracks': tracks_data,
        'sales':  sales_data,
    })


# ─── Artiste ──────────────────────────────────────────────────────────────────

@dashboard_api_bp.route('/artist', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_artist_dashboard(current_user):
    """Espace artiste : toplines soumises, favoris, historique d'écoute, tokens."""
    if not current_user.is_artist:
        return err('Accès refusé.', status=403)

    # ── Toplines ──────────────────────────────────────────────────────────────
    toplines = db.session.scalars(
        select(Topline)
        .where(Topline.artist_id == current_user.id)
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
            'stream_url':   f'/api/stream/toplines/{tl.id}',
        }
        for tl in toplines
    ]

    # ── Favoris ───────────────────────────────────────────────────────────────
    favorites = db.session.scalars(
        select(Favorite)
        .where(Favorite.user_id == current_user.id)
        .order_by(Favorite.created_at.desc())
    ).all()

    favorites_data = [
        {
            'id':           fav.track_id,
            'title':        fav.track.title if fav.track else None,
            'image_file':   fav.track.image_file if fav.track else None,
            'composer':     fav.track.composer_user.username if fav.track and fav.track.composer_user else None,
            'stream_url':   f'/api/stream/tracks/{fav.track_id}/preview',
            'favorited_at': fav.created_at.isoformat(),
        }
        for fav in favorites
        if fav.track
    ]

    # ── Historique d'écoute (10 derniers uniques) ─────────────────────────────
    history = db.session.scalars(
        select(ListeningHistory)
        .where(ListeningHistory.user_id == current_user.id)
        .order_by(ListeningHistory.listened_at.desc())
        .limit(10)
    ).all()

    history_data = [
        {
            'id':          h.track_id,
            'title':       h.track.title if h.track else None,
            'image_file':  h.track.image_file if h.track else None,
            'composer':    h.track.composer_user.username if h.track and h.track.composer_user else None,
            'stream_url':  f'/api/stream/tracks/{h.track_id}/preview',
            'listened_at': h.listened_at.isoformat(),
        }
        for h in history
        if h.track
    ]

    # ── Demandes mix/master en tant qu'artiste ────────────────────────────────
    mm_requests = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.artist_id == current_user.id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()

    return ok({
        'stats': {
            'toplines_count':     len(toplines),
            'toplines_published': sum(1 for tl in toplines if tl.is_published),
            'favorites_count':    len(favorites_data),
            'topline_tokens':     current_user.topline_tokens,
            'mm_requests_count':  len(mm_requests),
            'mm_active_count':    sum(1 for o in mm_requests if o.status in ('awaiting_acceptance', 'accepted', 'processing', 'delivered', 'revision1', 'revision2')),
        },
        'toplines':    toplines_data,
        'favorites':   favorites_data,
        'history':     history_data,
        'mm_requests': [ser_order_full(o, 'artist') for o in mm_requests],
    })


# ─── Mix Engineer ─────────────────────────────────────────────────────────────

@dashboard_api_bp.route('/mix-engineer', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_mix_engineer_dashboard(current_user):
    """Espace mix engineer : commandes par statut, stats revenus."""
    if not current_user.is_mix_engineer:
        return err('Accès refusé.', status=403)

    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.engineer_id == current_user.id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()

    ACTIVE_STATUSES    = {'accepted', 'processing', 'delivered'}
    REVISION_STATUSES  = {'revision1', 'revision2'}
    COMPLETED_STATUSES = {'completed'}
    REFUSED_STATUSES   = {'rejected', 'refunded'}

    completed_orders = [o for o in orders if o.status in COMPLETED_STATUSES]
    total_revenue    = sum(o.engineer_revenue or 0 for o in completed_orders)

    return ok({
        'stats': {
            'total_revenue':    round(total_revenue, 2),
            'completed_count':  len(completed_orders),
            'active_count':     sum(1 for o in orders if o.status in ACTIVE_STATUSES),
            'pending_count':    sum(1 for o in orders if o.status == 'awaiting_acceptance'),
            'reference_price':  current_user.mixmaster_reference_price,
            'price_min':        current_user.mixmaster_price_min,
            'sample_submitted': current_user.mixmaster_sample_submitted,
            'producer_arranger_request_submitted': current_user.producer_arranger_request_submitted,
            'is_mixmaster_engineer':          current_user.is_mixmaster_engineer,
            'is_certified_producer_arranger': current_user.is_certified_producer_arranger,
            'is_certified_master_engineer':   current_user.is_certified_master_engineer,
            'master_sample_submitted':        current_user.master_sample_submitted,
        },
        'orders': {
            'awaiting':  [ser_order_full(o, 'engineer') for o in orders if o.status == 'awaiting_acceptance'],
            'active':    [ser_order_full(o, 'engineer') for o in orders if o.status in ACTIVE_STATUSES],
            'revisions': [ser_order_full(o, 'engineer') for o in orders if o.status in REVISION_STATUSES],
            'completed': [ser_order_full(o, 'engineer') for o in orders if o.status in COMPLETED_STATUSES],
            'refused':   [ser_order_full(o, 'engineer') for o in orders if o.status in REFUSED_STATUSES],
        },
    })
