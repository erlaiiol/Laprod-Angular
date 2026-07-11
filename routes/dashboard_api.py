"""
Dashboard API — GET endpoints pour les espaces Beatmaker, Artiste et Mix Engineer
"""
from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from sqlalchemy import select, func
from datetime import datetime, timedelta
import json
from extensions import db, csrf, redis_client
from models import Track, Purchase, Topline, MixMasterRequest, Favorite, ListeningHistory, TrackView, ListenEvent
from utils.image_variants import variant_or_original
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
            'image_file':      variant_or_original(t.image_file, 'thumb'),
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
            'track_image':      variant_or_original(s.track.image_file, 'thumb') if s.track else None,
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


# ─── Beatmaker — Analytics ────────────────────────────────────────────────────

@dashboard_api_bp.route('/beatmaker/analytics', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_beatmaker_analytics(current_user):
    """
    Endpoint analytics beatmaker.
    Query param : period = '7d' | '30d' | '90d' (default '30d')

    Retourne :
      - time_series : vues / écoutes / revenus par jour
      - per_track   : stats agrégées par beat + taux de conversion
      - recommendations : conseils générés automatiquement
    Mis en cache Redis 30 min par (user_id, period).
    """
    if not current_user.is_beatmaker:
        return err('Accès refusé.', status=403)

    period = request.args.get('period', '30d')
    if period not in ('7d', '30d', '90d'):
        period = '30d'
    days = int(period[:-1])

    cache_key = f"dash:bm:{current_user.id}:{period}"
    try:
        cached = redis_client.get(cache_key)
        if cached:
            return ok(json.loads(cached))
    except Exception:
        pass

    cutoff = datetime.utcnow() - timedelta(days=days)

    # ── IDs des tracks du beatmaker ───────────────────────────────────────────
    track_ids = [
        r[0] for r in db.session.query(Track.id)
        .filter_by(composer_id=current_user.id).all()
    ]

    if not track_ids:
        payload = {'time_series': {'views': [], 'plays': [], 'revenues': []}, 'per_track': [], 'recommendations': []}
        return ok(payload)

    # ── Séries temporelles — vues ─────────────────────────────────────────────
    views_ts = db.session.query(
        func.date(TrackView.created_at).label('day'),
        func.count(TrackView.id).label('count'),
    ).filter(
        TrackView.track_id.in_(track_ids),
        TrackView.created_at >= cutoff,
    ).group_by(func.date(TrackView.created_at)).order_by('day').all()

    # ── Séries temporelles — écoutes ──────────────────────────────────────────
    plays_ts = db.session.query(
        func.date(ListenEvent.created_at).label('day'),
        func.count(ListenEvent.id).label('count'),
    ).filter(
        ListenEvent.track_id.in_(track_ids),
        ListenEvent.created_at >= cutoff,
    ).group_by(func.date(ListenEvent.created_at)).order_by('day').all()

    # ── Séries temporelles — revenus ──────────────────────────────────────────
    revenues_ts = db.session.query(
        func.date(Purchase.created_at).label('day'),
        func.sum(Purchase.composer_revenue).label('revenue'),
    ).join(Track, Purchase.track_id == Track.id).filter(
        Track.composer_id == current_user.id,
        Purchase.created_at >= cutoff,
    ).group_by(func.date(Purchase.created_at)).order_by('day').all()

    # ── Stats par track ───────────────────────────────────────────────────────
    tracks = db.session.query(Track).filter(Track.id.in_(track_ids)).all()

    views_by_track = dict(
        db.session.query(TrackView.track_id, func.count(TrackView.id))
        .filter(TrackView.track_id.in_(track_ids), TrackView.created_at >= cutoff)
        .group_by(TrackView.track_id).all()
    )
    unique_listeners_by_track = dict(
        db.session.query(TrackView.track_id, func.count(func.distinct(TrackView.ip_hash)))
        .filter(TrackView.track_id.in_(track_ids))
        .group_by(TrackView.track_id).all()
    )
    plays_by_track = dict(
        db.session.query(ListenEvent.track_id, func.count(ListenEvent.id))
        .filter(ListenEvent.track_id.in_(track_ids), ListenEvent.created_at >= cutoff)
        .group_by(ListenEvent.track_id).all()
    )
    completion_by_track = dict(
        db.session.query(ListenEvent.track_id, func.avg(ListenEvent.completion_ratio))
        .filter(ListenEvent.track_id.in_(track_ids))
        .group_by(ListenEvent.track_id).all()
    )
    sales_by_track = dict(
        db.session.query(Purchase.track_id, func.count(Purchase.id))
        .join(Track, Purchase.track_id == Track.id)
        .filter(Track.composer_id == current_user.id)
        .group_by(Purchase.track_id).all()
    )
    revenue_by_track = dict(
        db.session.query(Purchase.track_id, func.sum(Purchase.composer_revenue))
        .join(Track, Purchase.track_id == Track.id)
        .filter(Track.composer_id == current_user.id)
        .group_by(Purchase.track_id).all()
    )
    toplines_by_track = dict(
        db.session.query(Topline.track_id, func.count(Topline.id))
        .filter(Topline.track_id.in_(track_ids), Topline.is_published == True)
        .group_by(Topline.track_id).all()
    )

    per_track = []
    for t in tracks:
        v  = views_by_track.get(t.id, 0)
        ul = unique_listeners_by_track.get(t.id, 0)
        s  = sales_by_track.get(t.id, 0)
        conv = round(s / ul, 3) if ul > 0 else 0.0
        per_track.append({
            'track_id':           t.id,
            'title':              t.title,
            'image_file':         variant_or_original(t.image_file, 'thumb'),
            'bpm':                t.bpm,
            'tags':               [tg.name for tg in t.tags],
            'views':              v,
            'plays':              plays_by_track.get(t.id, 0),
            'play_completion_avg': round(float(completion_by_track.get(t.id) or 0), 2),
            'unique_listeners':   ul,
            'sales_count':        s,
            'revenue':            round(float(revenue_by_track.get(t.id) or 0), 2),
            'toplines_count':     toplines_by_track.get(t.id, 0),
            'conversion_rate':    conv,
        })

    # ── Recommandations intelligentes ─────────────────────────────────────────
    recommendations = []

    if per_track:
        converting = [p for p in per_track if p['conversion_rate'] > 0]
        if converting:
            avg_conv = sum(p['conversion_rate'] for p in per_track if p['unique_listeners'] > 0) / max(1, sum(1 for p in per_track if p['unique_listeners'] > 0))
            best = sorted(converting, key=lambda x: x['conversion_rate'], reverse=True)
            if best and best[0]['conversion_rate'] > avg_conv * 1.5:
                bpms = [p['bpm'] for p in best[:3] if p['bpm']]
                if bpms:
                    bpm_hint = f"{min(bpms)}–{max(bpms)}" if len(set(bpms)) > 1 else str(bpms[0])
                    recommendations.append(f"Tes beats les plus convertissants tournent autour de {bpm_hint} BPM. Produis dans cette plage.")

        top_tags: dict[str, int] = {}
        for p in per_track:
            if p['sales_count'] > 0:
                for tag in p['tags']:
                    top_tags[tag] = top_tags.get(tag, 0) + p['sales_count']
        if top_tags:
            best_tag = max(top_tags, key=lambda k: top_tags[k])
            if top_tags[best_tag] > 1:
                recommendations.append(f"Le tag #{best_tag} génère le plus de ventes. Utilise-le davantage dans tes descriptions.")

        incomplete = [p for p in per_track if p['unique_listeners'] > 10 and p['sales_count'] == 0]
        if incomplete:
            recommendations.append(f"{len(incomplete)} beat(s) avec plus de 10 écoutes uniques mais 0 vente — vérifie leur prix ou leurs tags.")

        low_comp = [p for p in per_track if 0 < p['play_completion_avg'] < 0.35]
        if low_comp:
            recommendations.append(f"{len(low_comp)} beat(s) ont un taux d'écoute moyen < 35%. Raccourcis l'intro ou relance l'énergie plus vite.")

    payload = {
        'time_series': {
            'views':    [{'date': str(r.day), 'count': r.count}     for r in views_ts],
            'plays':    [{'date': str(r.day), 'count': r.count}     for r in plays_ts],
            'revenues': [{'date': str(r.day), 'revenue': round(float(r.revenue), 2)} for r in revenues_ts],
        },
        'per_track':       sorted(per_track, key=lambda x: x['views'], reverse=True),
        'recommendations': recommendations,
    }

    try:
        redis_client.setex(cache_key, 1800, json.dumps(payload))
    except Exception:
        pass

    return ok(payload)


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
            'track_image':  variant_or_original(tl.track.image_file, 'thumb') if tl.track else None,
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
            'image_file':   variant_or_original(fav.track.image_file, 'thumb') if fav.track else None,
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
            'image_file':  variant_or_original(h.track.image_file, 'thumb') if h.track else None,
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
