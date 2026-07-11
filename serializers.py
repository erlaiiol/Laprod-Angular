"""
serializers.py — LaProd
=======================
Source unique de vérité pour la sérialisation JSON des modèles SQLAlchemy.

Convention de nommage :
  user_ref(u)               → dict minimal pour références imbriquées (composer_user, artist_user)
  user_auth(u, notif_count) → réponses d'authentification (login, /me)
  user_admin(u, **counts)   → table admin (inclut les compteurs de tracks/contrats/mm)
  tag(t)                    → Tag avec catégorie et couleur
  track_card(t)             → card catalogue / player card
  track_detail(t)           → page détail (SACEM, fichiers, toplines à ajouter par le routeur)
  track_admin(t)            → table admin (clé 'composer' au lieu de 'composer_user')
  topline(tl)               → topline publiée ou personnelle
  mix_engineer(eng)         → fiche ingénieur certifié (liste + détail)
  mix_order_full(o, pers.)  → commande mix/master complète
  wallet_transaction(t)     → transaction wallet
  notification(n)           → notification
  purchase(p)               → achat de beat
  ok(data, msg, status)     → réponse succès JSON
  err(msg, level, code, st) → réponse erreur JSON

Usage dans un blueprint :
    from serializers import ok, err, track_card, user_ref
"""

from flask import jsonify
from sqlalchemy import func

from utils.image_variants import variant_or_original


# =============================================================================
# Response envelope helpers
# =============================================================================

def ok(data=None, message: str = '', status: int = 200, level: str = 'success', code: str | None = None):
    """Réponse succès standard. `message` affiché uniquement s'il n'est pas vide."""
    body: dict = {'success': True}
    if message:
        body['feedback'] = {'level': level, 'message': message}
    if code:
        body['code'] = code
    if data is not None:
        body['data'] = data
    return jsonify(body), status


def err(message: str, level: str = 'error', code: str | None = None, status: int = 400, data=None):
    """Réponse erreur standard."""
    body: dict = {'success': False, 'feedback': {'level': level, 'message': message}}
    if code:
        body['code'] = code
    if data is not None:
        body['data'] = data
    return jsonify(body), status


# =============================================================================
# User serializers
# =============================================================================

def user_ref(u) -> dict | None:
    """
    Référence minimale imbriquée dans un autre objet (composer_user, artist_user…).
    Retourne None si u est None pour ne pas casser les réponses avec des relations nulles.
    """
    if not u:
        return None
    return {
        'id':            u.id,
        'username':      u.username,
        # Avatar affiché petit partout → variante thumb si dispo. Les URLs
        # externes (profile_picture_url OAuth) passent au travers inchangées.
        'profile_image': variant_or_original(u.profile_picture_url or u.profile_image, 'thumb'),
    }


def user_auth(u, notif_count: int = 0) -> dict:
    """
    Dict utilisateur pour les réponses d'authentification (login, /me, register).
    Inclut les rôles sous forme de sous-objet `roles` (shape attendue par Angular AuthService).
    `notif_count` est passé par le routeur (évite l'import circulaire de notification_service).
    """
    return {
        'id':            u.id,
        'username':      u.username,
        'email':         u.email,
        'profile_image': u.profile_picture_url or u.profile_image,
        'roles': {
            'is_admin':                       u.is_admin,
            'is_beatmaker':                   u.is_beatmaker,
            'is_mix_engineer':                u.is_mix_engineer,
            'is_artist':                      u.is_artist,
            'is_mixmaster_engineer':          u.is_mixmaster_engineer,
            'is_certified_producer_arranger': u.is_certified_producer_arranger,
        },
        'user_type_selected':  u.user_type_selected,
        'email_verified':      u.email_verified,
        'notif_count':         notif_count,
        'upload_track_tokens':   u.upload_track_tokens,
        'topline_tokens':        u.topline_tokens,
        'is_premium':            bool(u.is_premium_active),
        'subscription_plan':     u.subscription_plan,
        'preferred_tag_category':   u.preferred_tag_category,
        'instagram': u.instagram,
        'twitter':   u.twitter,
        'youtube':   u.youtube,
        'stripe_onboarding_complete': bool(u.stripe_onboarding_complete),
    }


def user_admin(u, tracks_count: int = 0, contracts_count: int = 0, mm_count: int = 0) -> dict:
    """
    Fiche utilisateur pour la table admin. Les compteurs sont passés par le routeur
    car ils nécessitent des requêtes DB additionnelles.
    """
    return {
        'id':              u.id,
        'username':        u.username,
        'email':           u.email,
        'profile_image':   u.profile_picture_url or u.profile_image,
        'account_status':  u.account_status,
        'is_admin':        u.is_admin,
        'is_beatmaker':    u.is_beatmaker,
        'is_artist':       u.is_artist,
        'is_mix_engineer': u.is_mix_engineer,
        'is_mixmaster_engineer':             u.is_mixmaster_engineer,
        'is_certified_master_engineer':      u.is_certified_master_engineer,
        'is_certified_producer_arranger':    u.is_certified_producer_arranger,
        'producer_arranger_request_submitted': u.producer_arranger_request_submitted,
        'is_premium':           u.is_premium,
        'subscription_plan':    u.subscription_plan,
        'premium_since':        u.premium_since.isoformat()      if u.premium_since      else None,
        'premium_expires_at':   u.premium_expires_at.isoformat() if u.premium_expires_at else None,
        'premium_source':       u.premium_source,
        'premium_price_paid':   float(u.premium_price_paid) if u.premium_price_paid else None,
        'email_verified':       u.email_verified,
        'user_type_selected':   u.user_type_selected,
        'auth_method':          u.oauth_provider or 'local',
        'upload_track_tokens':  u.upload_track_tokens,
        'topline_tokens':       u.topline_tokens,
        'created_at':           u.created_at.isoformat() if u.created_at else None,
        'deleted_at':           u.deleted_at.isoformat()  if u.deleted_at  else None,
        'tracks_count':    tracks_count,
        'contracts_count': contracts_count,
        'mm_count':        mm_count,
    }


# =============================================================================
# Tag serializer
# =============================================================================

def tag(t) -> dict:
    """Tag avec catégorie et couleur hexadécimale."""
    return {
        'id':       t.id,
        'name':     t.name,
        'category': t.category_obj.name  if t.category_obj else 'other',
        'color':    t.category_obj.color if t.category_obj else '#6b7280',
    }


# =============================================================================
# SimilarArtist serializer
# =============================================================================

def similar_artist(a) -> dict:
    return {'id': a.id, 'name': a.name, 'scene': a.scene}


# =============================================================================
# Track serializers
# =============================================================================

def track_card(t, playlist_counts: dict | None = None, playlist_images: dict | None = None) -> dict:
    """
    Card catalogue / player card.
    Shape minimal exposé sur la home page, le catalogue, et le player.
    `composer_user` inclut id + profile_image pour permettre les liens de profil
    sans second appel API.

    playlist_counts et playlist_images sont des dicts pré-calculés (id → valeur)
    passés par l'appelant pour éviter le N+1. Si absents, les champs valent 0 / None.
    """
    return {
        'id':          t.id,
        'title':       t.title,
        'bpm':         t.bpm,
        'key':         t.key,
        'style':       t.style,
        'image_file':  t.image_file,
        # Variantes WebP redimensionnées — fallback : l'original tant que la
        # migration scripts/generate_image_variants.py n'a pas tourné.
        'image_thumb': variant_or_original(t.image_file, 'thumb'),
        'image_large': variant_or_original(t.image_file, 'large'),
        'stream_url':      f'/api/stream/tracks/{t.id}/preview',
        'full_stream_url': f'/api/stream/tracks/{t.id}/full' if t.file_mp3 else None,
        'price_mp3':   float(t.price_mp3)   if t.price_mp3   else None,
        'price_wav':   float(t.price_wav)   if t.price_wav   else None,
        'price_stems': float(t.price_stems) if t.price_stems else None,
        'is_approved': t.is_approved,
        'created_at':  t.created_at.isoformat() if t.created_at else None,
        'composer_user': user_ref(t.composer_user),
        'tags':          [tag(tg) for tg in t.tags],
        'similar_artists': [similar_artist(a) for a in (t.similar_artists or [])],
        # Données playlist (champ toujours présent, 0 / None si non renseigné)
        'playlist_count':       (playlist_counts or {}).get(t.id, 0),
        'first_playlist_image': variant_or_original((playlist_images or {}).get(t.id), 'thumb'),
    }


def playlist_stats_for_tracks(track_ids: list[int]) -> tuple[dict, dict]:
    """
    Retourne (counts_dict, first_images_dict) pour une liste de track IDs.
    Une seule passe SQL par dict, sans N+1.
    Doit être appelé depuis un contexte Flask avec db disponible.
    """
    if not track_ids:
        return {}, {}
    from extensions import db
    from models import playlist_track, Playlist

    counts = dict(
        db.session.query(playlist_track.c.track_id, func.count(playlist_track.c.playlist_id))
        .filter(playlist_track.c.track_id.in_(track_ids))
        .group_by(playlist_track.c.track_id)
        .all()
    )
    subq = (
        db.session.query(
            playlist_track.c.track_id,
            Playlist.image_file,
            func.row_number().over(
                partition_by=playlist_track.c.track_id,
                order_by=playlist_track.c.playlist_id,
            ).label('rn'),
        )
        .join(Playlist, Playlist.id == playlist_track.c.playlist_id)
        .filter(playlist_track.c.track_id.in_(track_ids))
        .subquery()
    )
    images = dict(
        db.session.query(subq.c.track_id, subq.c.image_file)
        .filter(subq.c.rn == 1)
        .all()
    )
    return counts, images


def track_detail(t) -> dict:
    """
    Page détail du beat — étend track_card avec les fichiers, SACEM,
    et purchase_count. Les toplines sont ajoutées par le routeur (requête séparée).
    contract_prices est ajouté par le routeur (nécessite current_app.config).
    """
    return {
        **track_card(t),
        'audio_file':  t.audio_file,
        'file_mp3':    t.file_mp3,
        'file_wav':    t.file_wav,
        'file_stems':  t.file_stems,
        'approved_at': t.approved_at.isoformat() if t.approved_at else None,
        'sacem_percentage_composer': t.sacem_percentage_composer,
        'sacem_percentage_buyer':    t.get_sacem_percentage_buyer(),
        'purchase_count':    t.purchase_count,
        'is_exclusive_sold': t.is_exclusive_sold,
    }


def track_admin(t) -> dict:
    """
    Ligne de table admin. Identique à track_detail mais :
    - clé `composer` au lieu de `composer_user` (attendu par le composant Angular AdminComponent)
    - `purchase_count` et `approved_at` inclus
    """
    d = {
        'id':               t.id,
        'title':            t.title,
        'bpm':              t.bpm,
        'key':              t.key,
        'style':            t.style,
        'image_file':       t.image_file,
        'stream_url':       f'/api/stream/tracks/{t.id}/preview',
        'price_mp3':        float(t.price_mp3)   if t.price_mp3   else None,
        'price_wav':        float(t.price_wav)   if t.price_wav   else None,
        'price_stems':      float(t.price_stems) if t.price_stems else None,
        'is_approved':      t.is_approved,
        'is_exclusive_sold': t.is_exclusive_sold,
        'exclusive_sold_at': t.exclusive_sold_at.isoformat() if t.exclusive_sold_at else None,
        'exclusive_buyer':  user_ref(t.exclusive_buyer) if t.exclusive_buyer else None,
        'purchase_count':   t.purchase_count,
        'created_at':       t.created_at.isoformat() if t.created_at else None,
        'approved_at':      t.approved_at.isoformat() if t.approved_at else None,
        'composer': user_ref(t.composer_user),
        'tags': [tag(tg) for tg in t.tags],
    }
    return d


# =============================================================================
# Topline serializer
# =============================================================================

def topline(tl) -> dict:
    """
    Topline publiée ou personnelle (my_toplines).
    `stream_url` utilise le proxy JWT /api/stream/toplines/:id.
    """
    return {
        'id':               tl.id,
        'artist_id':        tl.artist_id,
        'guest_session_id': tl.guest_session_id,
        'stream_url':       f'/api/stream/toplines/{tl.id}',
        'description':      tl.description,
        'is_published':     tl.is_published,
        'is_mobile_processed': tl.is_mobile_processed,
        'created_at':       tl.created_at.isoformat() if tl.created_at else None,
        'artist_user':      user_ref(tl.artist_user) if tl.artist_user else None,
    }


# =============================================================================
# Mixmaster serializers
# =============================================================================

def mix_engineer(eng) -> dict:
    """
    Fiche ingénieur certifié — liste publique et page détail.
    Inclut les prix calculés, les slots disponibles, et les URLs d'échantillons.
    """
    from models import MixMasterRequest  # import local pour éviter les imports circulaires
    ref = float(eng.mixmaster_reference_price or 0)
    if ref:
        # Services toujours disponibles pour tout mix engineer
        max_pct = 0.35 + 0.45 + 0.20   # cleaning + effects + stems
        # Mastering : certifié admin OU abonnement Pro actif
        if eng.can_do_mastering:
            max_pct += 0.20
        # Intervention artistique : certifié producteur/arrangeur
        if eng.is_certified_producer_arranger:
            max_pct += 0.60
        price_max = round(ref * max_pct, 2)
    else:
        price_max = 0

    active = MixMasterRequest.get_active_requests_count(eng.id)
    return {
        'id':                            eng.id,
        'username':                      eng.username,
        'profile_image':                 eng.profile_picture_url or eng.profile_image,
        'mixmaster_bio':                 eng.mixmaster_bio,
        'mixmaster_reference_price':     eng.mixmaster_reference_price,
        'mixmaster_price_min':           eng.mixmaster_price_min,
        'price_max':                     price_max,
        'is_certified_producer_arranger':  eng.is_certified_producer_arranger,
        'is_certified_master_engineer':    eng.is_certified_master_engineer,
        'subscription_plan':               eng.subscription_plan,
        'sample_raw_url':       f'/{eng.mixmaster_sample_raw}'       if eng.mixmaster_sample_raw       else None,
        'sample_processed_url': f'/{eng.mixmaster_sample_processed}' if eng.mixmaster_sample_processed else None,
        'stripe_ready': bool(
            eng.mixmaster_reference_price
            and eng.mixmaster_price_min
        ),
        'active_orders':   active,
        'slots_available': max(0, 5 - active),
    }


def mix_order_full(o, perspective: str = 'artist') -> dict:
    """
    Commande de mix/master complète.
    `perspective` : 'artist' expose l'ingénieur, 'engineer' expose l'artiste.
    Inclut les champs financiers, le briefing, les fichiers, et les dates.
    """
    can_rev, _ = o.can_request_revision()
    return {
        'id':                    o.id,
        'title':                 o.title,
        'status':                o.status,
        'stripe_payment_status': o.stripe_payment_status,
        'total_price':           o.total_price,
        'deposit_amount':        o.deposit_amount,
        'remaining_amount':      o.remaining_amount,
        'engineer_revenue':      o.engineer_revenue,
        'revision_count':        o.revision_count,
        'revision1_message':     o.revision1_message,
        'revision2_message':     o.revision2_message,
        'can_request_revision':  can_rev,
        'is_expired':            o.is_expired(),
        # Finances
        'total_transferred':     o.get_total_transferred_to_engineer(),
        'final_transfer_amount': o.get_final_transfer_amount(),
        'refund_amount':         o.get_refund_amount(),
        # Intervenants (flat keys pour compatibilité Angular existante)
        'artist_id':       o.artist_id,
        'artist_username': o.artist.username      if o.artist   else None,
        'artist_image':    o.artist.profile_image if o.artist   else None,
        'engineer_id':       o.engineer_id,
        'engineer_username': o.engineer.username      if o.engineer else None,
        'engineer_image':    o.engineer.profile_image if o.engineer else None,
        # Services
        'services': {
            'cleaning':  o.service_cleaning,
            'effects':   o.service_effects,
            'artistic':  o.service_artistic,
            'mastering': o.service_mastering,
        },
        'has_separated_stems': o.has_separated_stems,
        # Briefing
        'artist_message':      o.artist_message,
        'brief_vocals':        o.brief_vocals,
        'brief_backing_vocals': o.brief_backing_vocals,
        'brief_ambiance':      o.brief_ambiance,
        'brief_bass':          o.brief_bass,
        'brief_energy_style':  o.brief_energy_style,
        'brief_references':    o.brief_references,
        'brief_instruments':   o.brief_instruments,
        'brief_percussion':    o.brief_percussion,
        'brief_effects':       o.brief_effects,
        'brief_structure':     o.brief_structure,
        # Fichiers (proxy /static/ conservé — chemins stockés en DB avec ce préfixe)
        'reference_file_url':              f'/static/{o.reference_file}'              if o.reference_file              else None,
        'original_file_url':               f'/static/{o.original_file}'               if o.original_file               else None,
        'processed_file_preview_url':      f'/static/{o.processed_file_preview}'      if o.processed_file_preview      else None,
        'processed_file_preview_full_url': f'/static/{o.processed_file_preview_full}' if o.processed_file_preview_full else None,
        # Arborescence archive (rétrocompat : anciens enregistrements = dicts, nouveaux = strings)
        'archive_file_tree': [
            (f['path'] if isinstance(f, dict) else f)
            for f in (o.archive_file_tree or [])
            if not (isinstance(f, dict) and f.get('is_dir'))
        ],
        # Dates
        'created_at':   o.created_at.isoformat()   if o.created_at   else None,
        'accepted_at':  o.accepted_at.isoformat()  if o.accepted_at  else None,
        'deadline':     o.deadline.isoformat()      if o.deadline     else None,
        'delivered_at': o.delivered_at.isoformat()  if o.delivered_at else None,
        'completed_at': o.completed_at.isoformat()  if o.completed_at else None,
    }


# =============================================================================
# Wallet / Finance serializers
# =============================================================================

def wallet_transaction(t) -> dict:
    """Transaction wallet — crédit/débit/retrait."""
    return {
        'id':                 t.id,
        'type':               t.type,
        'amount':             float(t.amount),
        'status':             t.status,
        'description':        t.description,
        'available_at':       t.available_at.isoformat() if t.available_at else None,
        'created_at':         t.created_at.isoformat(),
        'stripe_transfer_id': t.stripe_transfer_id,
    }


def purchase(p) -> dict:
    """Achat de beat — historique artiste et paiement."""
    return {
        'id':               p.id,
        'format_purchased': p.format_purchased,
        'price_paid':       float(p.price_paid),
        'composer_revenue': float(p.composer_revenue),
        'platform_fee':     float(p.platform_fee),
        'created_at':       p.created_at.isoformat() if p.created_at else None,
        'track': track_card(p.track) if p.track else None,
        # Champs lifecycle licence
        'is_exclusive':    getattr(p, 'is_exclusive', False),
        'duration_years':  getattr(p, 'duration_years', None),
        'is_lifetime':     getattr(p, 'is_lifetime', False),
        'territory':       getattr(p, 'territory', None),
        'expires_at':      p.expires_at.isoformat() if getattr(p, 'expires_at', None) else None,
        'license_status':  getattr(p, 'license_status', 'active'),
        'contract_url':    f'/api/licenses/{p.id}/contract' if getattr(p, 'contract_file', None) else None,
    }


def purchase_detail(p, include_sole: bool = False) -> dict:
    """Détail complet d'une licence — vue artiste avec jours restants et sole licensee."""
    from utils.license_service import compute_days_remaining, is_sole_licensee
    days = compute_days_remaining(p)
    sole = is_sole_licensee(p) if include_sole else False
    return {
        **purchase(p),
        'days_remaining':  days,
        'is_sole_licensee': sole,
        'renewed_from_id': getattr(p, 'renewed_from_id', None),
        'renewed_to_id':   getattr(p, 'renewed_to_id', None),
    }


# =============================================================================
# Notification serializer
# =============================================================================

def notification(n) -> dict:
    """Notification utilisateur (bell icon, page notifications)."""
    return {
        'id':         n.id,
        'type':       n.type,
        'title':      n.title,
        'message':    n.message,
        'link':       n.link,
        'is_read':    n.is_read,
        'created_at': n.created_at.isoformat() if n.created_at else None,
        'read_at':    n.read_at.isoformat()    if n.read_at    else None,
    }
