"""
Blueprint TOPLINES API — GET + CUD endpoints

GET    /api/toplines/track/<track_id>  → toplines publiées d'une track (public)
GET    /api/toplines/my/<track_id>     → toplines de l'utilisateur courant (jwt_required)
POST   /api/toplines/upload            → Upload voix + traitement async (jwt_required)
POST   /api/toplines/<id>/publish      → Publier une topline (propriétaire)
POST   /api/toplines/<id>/unpublish    → Repasser en privée (propriétaire)
DELETE /api/toplines/<id>              → Supprimer une topline (propriétaire)
"""
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload
from datetime import datetime
from pathlib import Path
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
@jwt_required()
@limiter.limit("10 per hour")
@require_user
def upload_topline(current_user):
    """
    Upload voix + traitement audio async (RQ worker).

    FormData :
      - voice_file      : Blob audio (webm / mp3 / wav)
      - track_id        : int
      - use_autotune    : 'true' | 'false'
      - latency_hint_ms : int (optionnel) — latence hardware mesurée côté client
      - description     : str (optionnel, max 500 car.)
    """
    can_submit, quota_message = current_user.can_submit_topline()
    if not can_submit:
        return err(quota_message, level='warning', code='QUOTA_EXCEEDED', status=403)

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

        raw_filename = f"topline_raw_{track_id}_{current_user.id}_{timestamp}.{ext}"
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

        # ── Enqueue RQ ────────────────────────────────────────────────────────
        job_id = str(uuid.uuid4())

        job_payload = {
            'job_id':          job_id,
            'user_id':         current_user.id,
            'track_id':        track_id,
            'raw_path':        str(raw_path),
            'raw_filename':    raw_filename,
            'use_autotune':    use_autotune,
            'description':     description,
            'beat_audio_file': track.audio_file,
            'track_key':       track.key,
            'timestamp':       timestamp,
            'latency_hint_ms': latency_hint_ms,
        }

        redis_client.hset(f"job:{job_id}", mapping={
            'status':  'queued',
            'user_id': str(current_user.id),
        })
        redis_client.expire(f"job:{job_id}", 7200)

        q = Queue(connection=redis_client)
        q.enqueue('tasks.topline_processing.process_topline_data', job_payload, job_timeout=300)

        current_app.logger.info(
            f"Topline job {job_id} enqueued par user #{current_user.id} sur track #{track_id}"
        )

        return ok(
            data={'job_id': job_id},
            message='Topline envoyée, traitement en cours...',
        )

    except Exception as e:
        current_app.logger.error(f"Erreur upload topline: {e}", exc_info=True)
        return err(
            f"Erreur lors de l'envoi : {e}",
            code='PROCESSING_ERROR', status=500,
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
