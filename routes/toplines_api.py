"""
Blueprint TOPLINES API — GET + CUD endpoints

GET    /api/toplines/track/<track_id>   → toplines publiées d'une track (public)
GET    /api/toplines/my/<track_id>      → toplines de l'utilisateur courant (jwt_required)
POST   /api/toplines/upload             → Upload voix + traitement async (jwt_required)
POST   /api/toplines/upload-processed   → Upload topline pré-traitée côté client (mobile natif)
POST   /api/toplines/<id>/publish       → Publier une topline (propriétaire)
POST   /api/toplines/<id>/unpublish     → Repasser en privée (propriétaire)
DELETE /api/toplines/<id>               → Supprimer une topline (propriétaire)
"""
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import uuid
import config

from rq import Queue
from extensions import db, limiter, csrf, redis_client
from models import Track, Topline
from serializers import ok, err, topline as ser_topline
from utils.auth_helpers import require_user
from utils.crud_helpers import (
    get_or_404, require_ownership,
    handle_route_exceptions, commit_or_rollback,
)

GUEST_LIMIT_UUID = 3   # max essais visibles côté UI
GUEST_LIMIT_IP   = 5   # max côté serveur (tolérance CG-NAT)
GUEST_TTL_SEC    = 86400  # 24h

toplines_api_bp = Blueprint('toplines_api', __name__, url_prefix='/api/toplines')


# ── GET /toplines/track/<track_id> ────────────────────────────────────────────

@toplines_api_bp.route('/track/<int:track_id>', methods=['GET'])
def get_track_toplines(track_id):
    """Toplines publiées pour une track (accès public)."""
    track = db.get_or_404(Track, track_id)

    toplines = (
        db.session.query(Topline)
        .options(selectinload(Topline.artist_user))
        .filter_by(track_id=track_id, is_published=True)
        .order_by(Topline.created_at.desc())
        .all()
    )

    return ok({'toplines': [ser_topline(tl) for tl in toplines]})


# ── GET /toplines/my/<track_id> ───────────────────────────────────────────────

@toplines_api_bp.route('/my/<int:track_id>', methods=['GET'])
@jwt_required()
def get_my_toplines(track_id):
    """Toutes les toplines de l'utilisateur courant pour une track."""
    current_user_id = int(get_jwt_identity())

    toplines = (
        db.session.query(Topline)
        .options(selectinload(Topline.artist_user))
        .filter_by(track_id=track_id, artist_id=current_user_id)
        .order_by(Topline.created_at.desc())
        .all()
    )

    return ok({'toplines': [ser_topline(tl) for tl in toplines]})


# ── POST /toplines/upload ──────────────────────────────────────────────────────

@toplines_api_bp.route('/upload', methods=['POST'])
@csrf.exempt
@limiter.limit("15 per hour")
def upload_topline():
    """
    Upload voix + traitement audio async (RQ worker).
    Supporte les utilisateurs connectés (JWT) et les guests (X-Guest-Session header).

    FormData :
      - voice_file      : Blob audio (webm / mp3 / wav)
      - track_id        : int
      - use_autotune    : 'true' | 'false'
      - latency_hint_ms : int (optionnel)
      - description     : str (optionnel, max 500 car.)

    Headers (guest uniquement) :
      - X-Guest-Session : UUID v4 généré côté client (localStorage)
    """
    # ── Résolution identité (JWT ou guest) ───────────────────────────────────
    current_user     = None
    guest_session_id = None

    try:
        verify_jwt_in_request(optional=True)
        user_id = get_jwt_identity()
        if user_id:
            from models import User
            current_user = db.session.get(User, int(user_id))
    except Exception:
        pass

    if not current_user:
        raw_session = (request.headers.get('X-Guest-Session') or '').strip()
        if not raw_session or len(raw_session) > 36:
            return err(
                'Authentification requise ou header X-Guest-Session manquant.',
                code='AUTH_REQUIRED', status=401,
            )
        guest_session_id = raw_session

    # ── Quota ────────────────────────────────────────────────────────────────
    if current_user:
        can_submit, quota_message = current_user.can_submit_topline()
        if not can_submit:
            return err(quota_message, level='warning', code='QUOTA_EXCEEDED', status=403)
    else:
        # Vérification Redis double-filet (UUID + IP-hash)
        uuid_key = f"guest_topline:{guest_session_id}"
        # request.remote_addr est corrigé par ProxyFix (vraie IP client, non
        # forgeable). Lire X-Forwarded-For brut laissait un bot injecter une IP
        # différente à chaque requête pour réinitialiser son quota guest.
        ip_hash  = hashlib.sha256(
            (request.remote_addr or '').encode()
        ).hexdigest()[:16]
        ip_key   = f"guest_topline_ip:{ip_hash}"

        uuid_count = int(redis_client.get(uuid_key) or 0)
        ip_count   = int(redis_client.get(ip_key) or 0)

        if uuid_count >= GUEST_LIMIT_UUID:
            return err(
                'Limite atteinte. Crée un compte gratuit pour continuer.',
                code='GUEST_LIMIT_REACHED', status=429,
                data={'remaining': 0},
            )
        if ip_count >= GUEST_LIMIT_IP:
            return err(
                'Trop de tentatives depuis cette adresse. Réessaie demain.',
                code='IP_LIMIT_REACHED', status=429,
            )

    try:
        voice_file      = request.files.get('voice_file')
        track_id_raw    = request.form.get('track_id')
        use_autotune    = request.form.get('use_autotune', 'false') == 'true'
        description     = request.form.get('description', '').strip()[:500] or None
        latency_hint_ms = max(0, min(500, int(request.form.get('latency_hint_ms', 0) or 0)))

        if not voice_file or not track_id_raw:
            return err(
                'Les champs voice_file et track_id sont requis.',
                level='warning', code='VALIDATION_ERROR',
            )

        track = db.session.get(Track, int(track_id_raw))
        if not track:
            return err('Track introuvable.', code='TRACK_NOT_FOUND', status=404)
        if not track.is_approved:
            return err('Cette track n\'est pas disponible.', code='TRACK_UNAVAILABLE', status=403)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        track_id  = int(track_id_raw)
        user_slug = current_user.id if current_user else f"g_{guest_session_id[:8]}"

        # ── Sauvegarder le fichier RAW ────────────────────────────────────────
        content_type = voice_file.content_type or ''
        if   'webm' in content_type:                              ext = 'webm'
        elif 'mp3'  in content_type or 'mpeg' in content_type:   ext = 'mp3'
        elif 'mp4'  in content_type or 'm4a'  in content_type:   ext = 'm4a'
        elif 'ogg'  in content_type:                              ext = 'ogg'
        elif 'wav'  in content_type:                              ext = 'wav'
        else:                                                      ext = 'bin'

        toplines_dir = config.UPLOAD_FOLDER / 'toplines'
        toplines_dir.mkdir(parents=True, exist_ok=True)

        raw_filename = f"topline_raw_{track_id}_{user_slug}_{timestamp}.{ext}"
        raw_path     = toplines_dir / raw_filename
        voice_file.save(raw_path)

        file_size = raw_path.stat().st_size
        if file_size < 512:
            raw_path.unlink(missing_ok=True)
            return err(
                'Fichier audio vide ou invalide. Vérifiez que votre micro fonctionne et réessayez.',
                level='warning', code='INVALID_AUDIO', status=400,
            )

        current_app.logger.info(
            f"Topline raw saved: {raw_filename} ({file_size // 1024} KB, "
            f"content-type={content_type!r})"
        )

        # ── Incrémentation Redis si guest (après validation fichier) ──────────
        if not current_user:
            pipe = redis_client.pipeline()
            pipe.incr(uuid_key)
            pipe.expire(uuid_key, GUEST_TTL_SEC)
            pipe.incr(ip_key)
            pipe.expire(ip_key, GUEST_TTL_SEC)
            pipe.execute()

        # ── Enqueue RQ ────────────────────────────────────────────────────────
        job_id = str(uuid.uuid4())

        job_payload = {
            'job_id':           job_id,
            'user_id':          current_user.id if current_user else None,
            'guest_session_id': guest_session_id,
            'track_id':         track_id,
            'raw_path':         str(raw_path),
            'raw_filename':     raw_filename,
            'use_autotune':     use_autotune,
            'description':      description,
            'beat_audio_file':  track.audio_file,
            'track_key':        track.key,
            'timestamp':        timestamp,
            'latency_hint_ms':  latency_hint_ms,
        }

        redis_client.hset(f"job:{job_id}", mapping={
            'status':  'queued',
            'user_id': str(current_user.id) if current_user else 'guest',
        })
        redis_client.expire(f"job:{job_id}", 7200)

        q = Queue(connection=redis_client)
        q.enqueue('tasks.topline_processing.process_topline_data', job_payload, job_timeout=300)

        who = f"user #{current_user.id}" if current_user else f"guest {guest_session_id[:8]}"
        current_app.logger.info(f"Topline job {job_id} enqueued par {who} sur track #{track_id}")

        remaining = None
        if not current_user:
            new_count = int(redis_client.get(uuid_key) or 1)
            remaining = max(0, GUEST_LIMIT_UUID - new_count)

        return ok(
            data={'job_id': job_id, 'remaining_guest_attempts': remaining},
            message='Topline envoyée, traitement en cours...',
        )

    except Exception as e:
        current_app.logger.error(f"Erreur upload topline: {e}", exc_info=True)
        return err(
            f"Erreur lors de l'envoi : {e}",
            code='PROCESSING_ERROR', status=500,
        )


# ── POST /toplines/upload-processed ───────────────────────────────────────────

@toplines_api_bp.route('/upload-processed', methods=['POST'])
@csrf.exempt
@jwt_required()
@limiter.limit("30 per hour")
@require_user
def upload_processed_topline(current_user):
    """
    Reçoit une topline déjà traitée côté client (app mobile native).
    Enregistrement direct en BDD sans job RQ.

    FormData :
      - processed_file : Blob MP3 (audio/mpeg)
      - track_id       : int
      - description    : str (optionnel, max 500 car.)
    """
    can_submit, quota_message = current_user.can_submit_topline()
    if not can_submit:
        return err(quota_message, level='warning', code='QUOTA_EXCEEDED', status=403)

    try:
        processed_file = request.files.get('processed_file')
        track_id_raw   = request.form.get('track_id')
        description    = request.form.get('description', '').strip()[:500] or None

        if not processed_file or not track_id_raw:
            return err(
                'Les champs processed_file et track_id sont requis.',
                level='warning', code='VALIDATION_ERROR',
            )

        content_type = processed_file.content_type or ''
        allowed_types = {'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/wav', 'audio/x-wav'}
        if not any(t in content_type for t in ('mpeg', 'mp3', 'mp4', 'wav')):
            return err('Format de fichier invalide. MP3 attendu.', code='INVALID_FORMAT', status=400)

        track = db.session.get(Track, int(track_id_raw))
        if not track:
            return err('Track introuvable.', code='TRACK_NOT_FOUND', status=404)
        if not track.is_approved:
            return err('Cette track n\'est pas disponible.', code='TRACK_UNAVAILABLE', status=403)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        toplines_dir = config.UPLOAD_FOLDER / 'toplines'
        toplines_dir.mkdir(parents=True, exist_ok=True)

        filename = f"topline_mobile_{track.id}_{current_user.id}_{timestamp}.mp3"
        abs_path = toplines_dir / filename
        processed_file.save(abs_path)

        file_size = abs_path.stat().st_size
        if file_size < 512:
            abs_path.unlink(missing_ok=True)
            return err(
                'Fichier audio vide ou invalide.',
                level='warning', code='INVALID_AUDIO', status=400,
            )

        rel_path = f"audio/toplines/{filename}"

        topline = Topline(
            track_id=track.id,
            artist_id=current_user.id,
            audio_file=rel_path,
            description=description,
            is_published=False,
            is_mobile_processed=True,
        )
        db.session.add(topline)
        current_user.consume_topline_token()

        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            abs_path.unlink(missing_ok=True)
            current_app.logger.error(f"upload-processed DB error: {e}", exc_info=True)
            return err('Erreur lors de l\'enregistrement.', status=500)

        current_app.logger.info(
            f"Topline mobile #{topline.id} enregistrée par user #{current_user.id} "
            f"sur track #{track.id} ({file_size // 1024} KB)"
        )

        try:
            from utils.notification_service import create_notification
            create_notification(
                user_id=track.composer_id,
                type='topline_received',
                title='Nouvelle topline reçue',
                message=f'{current_user.username} a enregistré une topline sur "{track.title}"',
                link=f'/track/{track.id}',
            )
        except Exception:
            pass

        return ok({'topline_id': topline.id}, message='Topline enregistrée avec succès.')

    except Exception as e:
        current_app.logger.error(f"Erreur upload-processed: {e}", exc_info=True)
        return err(f"Erreur lors de l'envoi : {e}", code='PROCESSING_ERROR', status=500)


# ── POST /toplines/claim ───────────────────────────────────────────────────────

@toplines_api_bp.route('/claim', methods=['POST'])
@csrf.exempt
@jwt_required()
@require_user
def claim_guest_toplines(current_user):
    """
    Associe les toplines guest d'une session à l'utilisateur connecté.
    Body JSON : { "guest_session_id": "uuid" }
    """
    data             = request.get_json(silent=True) or {}
    guest_session_id = (data.get('guest_session_id') or '').strip()

    if not guest_session_id or len(guest_session_id) > 36:
        return err('guest_session_id manquant ou invalide.', status=400)

    toplines = (
        db.session.query(Topline)
        .filter_by(guest_session_id=guest_session_id, artist_id=None)
        .all()
    )

    if not toplines:
        return ok({'claimed': 0}, message='Aucune topline guest à récupérer.')

    count = 0
    for tl in toplines:
        tl.artist_id        = current_user.id
        tl.guest_session_id = None
        tl.guest_expires_at = None
        count += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Claim toplines failed: {e}", exc_info=True)
        return err('Erreur lors de la récupération des toplines.', status=500)

    current_app.logger.info(
        f"Claimed {count} topline(s) depuis session {guest_session_id[:8]} → user #{current_user.id}"
    )
    return ok(
        {'claimed': count, 'toplines': [ser_topline(tl) for tl in toplines]},
        message=f'{count} topline(s) récupérée(s) avec succès.',
    )


# ── POST /toplines/<id>/publish ────────────────────────────────────────────────

@toplines_api_bp.route('/<int:topline_id>/publish', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def publish_topline(topline_id, current_user):
    """Publier une topline (propriétaire uniquement)."""
    topline = get_or_404(Topline, topline_id, 'Topline introuvable.')
    require_ownership(topline, 'artist_id', current_user)

    topline.is_published = True
    db.session.commit()

    return ok(
        data={'topline': ser_topline(topline)},
        message='Topline publiée avec succès.',
    )


# ── POST /toplines/<id>/unpublish ─────────────────────────────────────────────

@toplines_api_bp.route('/<int:topline_id>/unpublish', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def unpublish_topline(topline_id, current_user):
    """Repasser une topline en privée (propriétaire uniquement)."""
    topline = get_or_404(Topline, topline_id, 'Topline introuvable.')
    require_ownership(topline, 'artist_id', current_user)

    topline.is_published = False
    db.session.commit()

    return ok(
        data={'topline': ser_topline(topline)},
        message='Topline repassée en privée.',
    )


# ── PATCH /toplines/<id> ───────────────────────────────────────────────────────

@toplines_api_bp.route('/<int:topline_id>', methods=['PATCH'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
def update_topline(topline_id, current_user):
    """Met à jour la description d'une topline (propriétaire uniquement)."""
    topline = get_or_404(Topline, topline_id, 'Topline introuvable.')
    require_ownership(topline, 'artist_id', current_user)

    data = request.get_json(silent=True) or {}
    description = (data.get('description') or '').strip()
    if len(description) > 200:
        return err('La description ne peut pas dépasser 200 caractères.', status=400)

    topline.description = description or None
    db.session.commit()

    return ok(
        data={'topline': ser_topline(topline)},
        message='Description mise à jour.',
    )


# ── DELETE /toplines/<id> ──────────────────────────────────────────────────────

@toplines_api_bp.route('/<int:topline_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def delete_topline(topline_id, current_user):
    """Supprimer une topline (propriétaire uniquement)."""
    topline = get_or_404(Topline, topline_id, 'Topline introuvable.')
    require_ownership(topline, 'artist_id', current_user)

    track_id = topline.track_id

    file_path = config.UPLOAD_FOLDER / topline.audio_file.replace('audio/', '', 1)
    if file_path.exists():
        file_path.unlink()
        current_app.logger.info(f"Fichier supprimé : {topline.audio_file}")

    db.session.delete(topline)
    db.session.commit()

    current_app.logger.info(
        f"Topline #{topline_id} supprimée par user #{current_user.id}"
    )

    return ok(
        data={'track_id': track_id},
        message='Topline supprimée.',
    )
