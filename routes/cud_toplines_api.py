"""
Blueprint TOPLINES CUD API - Create/Update/Delete endpoints (jwt_required)

Format JSON unifié (identique à cud_tracks_api) :
  {
    "success": true | false,
    "feedback": { "level": "success|error|warning|info", "message": "..." },
    "data": { ... },          # présent si success ou si des données utiles à retourner
    "code": "SNAKE_CODE"      # optionnel, utilisé par le front pour distinguer les cas
  }

POST   /toplines/upload          → Upload voix + traitement + fusion
POST   /toplines/<id>/publish    → Publier une topline (propriétaire)
DELETE /toplines/<id>            → Supprimer une topline (propriétaire)
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
from models import Track, Topline, User
from serializers import ok, err, topline as ser_topline

cud_toplines_api_bp = Blueprint('cud_toplines_api', __name__, url_prefix='/api/toplines')


# ── POST /toplines/upload ──────────────────────────────────────────────────────

@cud_toplines_api_bp.route('/upload', methods=['POST'])
@jwt_required()
@csrf.exempt
@limiter.limit("10 per hour")
def upload_topline():
    """
    Upload voix + traitement audio + fusion avec le beat.

    FormData :
      - voice_file   : Blob audio (webm / mp3 / wav)
      - track_id     : int
      - use_autotune : 'true' | 'false'
      - description  : str (optionnel, max 500 car.)
    """
    current_user_id = int(get_jwt_identity())
    current_user = db.session.get(User, current_user_id)

    if not current_user:
        return err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    # ── Quota tokens ──────────────────────────────────────────────────────────
    can_submit, quota_message = current_user.can_submit_topline()
    if not can_submit:
        return err(quota_message, level='warning', code='QUOTA_EXCEEDED', status=403)

    try:
        voice_file   = request.files.get('voice_file')
        track_id_raw = request.form.get('track_id')
        use_autotune = request.form.get('use_autotune', 'false') == 'true'
        description  = request.form.get('description', '').strip()[:500] or None

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
        elif 'mp4'  in content_type:                              ext = 'm4a'
        else:                                                      ext = 'webm'

        toplines_dir = config.UPLOAD_FOLDER / 'toplines'
        toplines_dir.mkdir(parents=True, exist_ok=True)

        raw_filename = f"topline_raw_{track_id}_{current_user_id}_{timestamp}.{ext}"
        raw_path     = toplines_dir / raw_filename
        voice_file.save(raw_path)

        # ── Enqueue RQ ────────────────────────────────────────────────────────
        job_id = str(uuid.uuid4())

        job_payload = {
            'job_id':          job_id,
            'user_id':         current_user_id,
            'track_id':        track_id,
            'raw_path':        str(raw_path),
            'raw_filename':    raw_filename,
            'use_autotune':    use_autotune,
            'description':     description,
            'beat_audio_file': track.audio_file,
            'track_key':       track.key,
            'timestamp':       timestamp,
        }

        redis_client.hset(f"job:{job_id}", mapping={
            'status':  'queued',
            'user_id': str(current_user_id),
        })
        redis_client.expire(f"job:{job_id}", 7200)

        q = Queue(connection=redis_client)
        q.enqueue('tasks.topline_processing.process_topline_data', job_payload, job_timeout=300)

        current_app.logger.info(
            f"Topline job {job_id} enqueued par user #{current_user_id} sur track #{track_id}"
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

@cud_toplines_api_bp.route('/<int:topline_id>/publish', methods=['POST'])
@jwt_required()
@csrf.exempt
def publish_topline(topline_id):
    """Publier une topline (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = (
        db.session.query(Topline)
        .options(selectinload(Topline.artist_user))
        .get(topline_id)
    )
    if not topline:
        return err('Topline introuvable.', code='NOT_FOUND', status=404)
    if topline.artist_id != current_user_id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        topline.is_published = True
        db.session.commit()

        return ok(
            data={'topline': ser_topline(topline)},
            message='Topline publiée avec succès.',
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur publication topline #{topline_id}: {e}", exc_info=True)
        return err(str(e), code='SERVER_ERROR', status=500)


# ── POST /toplines/<id>/unpublish ─────────────────────────────────────────────

@cud_toplines_api_bp.route('/<int:topline_id>/unpublish', methods=['POST'])
@jwt_required()
@csrf.exempt
def unpublish_topline(topline_id):
    """Repasser une topline en privée (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = (
        db.session.query(Topline)
        .options(selectinload(Topline.artist_user))
        .get(topline_id)
    )
    if not topline:
        return err('Topline introuvable.', code='NOT_FOUND', status=404)
    if topline.artist_id != current_user_id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        topline.is_published = False
        db.session.commit()
        return ok(
            data={'topline': ser_topline(topline)},
            message='Topline repassée en privée.',
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur unpublish topline #{topline_id}: {e}", exc_info=True)
        return err(str(e), code='SERVER_ERROR', status=500)


# ── DELETE /toplines/<id> ──────────────────────────────────────────────────────

@cud_toplines_api_bp.route('/<int:topline_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
def delete_topline(topline_id):
    """Supprimer une topline (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = db.session.get(Topline, topline_id)
    if not topline:
        return err('Topline introuvable.', code='NOT_FOUND', status=404)
    if topline.artist_id != current_user_id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        track_id = topline.track_id

        # Supprimer le fichier audio physique
        file_path = config.UPLOAD_FOLDER / topline.audio_file.replace('audio/', '', 1)
        if file_path.exists():
            file_path.unlink()
            current_app.logger.info(f"Fichier supprimé : {topline.audio_file}")

        db.session.delete(topline)
        db.session.commit()

        current_app.logger.info(
            f"Topline #{topline_id} supprimée par user #{current_user_id}"
        )

        return ok(
            data={'track_id': track_id},
            message='Topline supprimée.',
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur suppression topline #{topline_id}: {e}", exc_info=True)
        return err(str(e), code='SERVER_ERROR', status=500)
