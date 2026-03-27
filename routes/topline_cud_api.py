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
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload
from datetime import datetime
from pathlib import Path
import config

from extensions import db, limiter
from models import Track, Topline, User

from routes.toplines import (
    convert_to_wav,
    apply_audio_effects,
    merge_voice_and_beat,
    cleanup_temp_files,
)

topline_cud_api_bp = Blueprint('topline_cud_api', __name__, url_prefix='/toplines')


# ── Helpers réponse unifiée ────────────────────────────────────────────────────

def _ok(data=None, message='', level='success', code=None, status=200):
    body = {
        'success': True,
        'feedback': {'level': level, 'message': message},
    }
    if data is not None:
        body['data'] = data
    if code:
        body['code'] = code
    return jsonify(body), status


def _err(message, level='error', code=None, status=400):
    body = {
        'success': False,
        'feedback': {'level': level, 'message': message},
    }
    if code:
        body['code'] = code
    return jsonify(body), status


def _topline_dict(topline, artist_user=None):
    """Sérialise une topline dans le format API unifié."""
    user = artist_user or topline.artist_user
    return {
        'id':           topline.id,
        'audio_file':   topline.audio_file,
        'description':  topline.description,
        'is_published': topline.is_published,
        'created_at':   topline.created_at.isoformat() if topline.created_at else None,
        'artist_user': {
            'username':      user.username,
            'profile_image': user.profile_image,
        } if user else None,
    }


# ── POST /toplines/upload ──────────────────────────────────────────────────────

@topline_cud_api_bp.route('/upload', methods=['POST'])
@jwt_required()
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
        return _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    # ── Quota tokens ──────────────────────────────────────────────────────────
    can_submit, quota_message = current_user.can_submit_topline()
    if not can_submit:
        return _err(quota_message, level='warning', code='QUOTA_EXCEEDED', status=403)

    try:
        voice_file   = request.files.get('voice_file')
        track_id_raw = request.form.get('track_id')
        use_autotune = request.form.get('use_autotune', 'false') == 'true'
        description  = request.form.get('description', '').strip()[:500] or None

        if not voice_file or not track_id_raw:
            return _err(
                'Les champs voice_file et track_id sont requis.',
                level='warning', code='VALIDATION_ERROR',
            )

        track = db.session.get(Track, int(track_id_raw))
        if not track:
            return _err('Track introuvable.', code='TRACK_NOT_FOUND', status=404)
        if not track.is_approved:
            return _err('Cette track n\'est pas disponible.', code='TRACK_UNAVAILABLE', status=403)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        track_id  = int(track_id_raw)

        # ── Étape 1 : sauvegarder le fichier RAW ──────────────────────────────
        content_type = voice_file.content_type or ''
        if   'webm' in content_type:                ext = 'webm'
        elif 'mp3'  in content_type or 'mpeg' in content_type: ext = 'mp3'
        elif 'mp4'  in content_type:                ext = 'm4a'
        else:                                        ext = 'webm'

        toplines_dir = config.UPLOAD_FOLDER / 'toplines'
        toplines_dir.mkdir(parents=True, exist_ok=True)

        raw_filename = f"topline_raw_{track_id}_{current_user_id}_{timestamp}.{ext}"
        raw_path     = toplines_dir / raw_filename
        voice_file.save(raw_path)

        # ── Étape 2 : convertir en WAV ────────────────────────────────────────
        wav_temp_path = convert_to_wav(raw_path)

        # ── Étape 3 : effets + auto-tune ──────────────────────────────────────
        wav_effects_path = apply_audio_effects(
            wav_temp_path,
            sample_rate=48000,
            autotune_key=track.key if use_autotune else None,
        )

        # ── Étape 4 : fusion voix + beat ──────────────────────────────────────
        beat_path = config.UPLOAD_FOLDER / track.audio_file.replace('audio/', '', 1)
        if not beat_path.exists():
            beat_path_alt = Path(current_app.root_path) / 'static' / track.audio_file
            if beat_path_alt.exists():
                beat_path = beat_path_alt
            else:
                cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])
                return _err(
                    'Instrumentale introuvable sur le serveur.',
                    code='BEAT_NOT_FOUND', status=404,
                )

        final_relative_path = merge_voice_and_beat(
            voice_path=wav_effects_path,
            beat_path=str(beat_path),
            track_id=track_id,
            user_id=current_user_id,
            timestamp=timestamp,
        )

        # ── Étape 5 : enregistrer en BDD ──────────────────────────────────────
        topline = Topline(
            track_id=track_id,
            artist_id=current_user_id,
            audio_file=final_relative_path,
            description=description,
        )
        db.session.add(topline)
        current_user.consume_topline_token()
        db.session.commit()

        cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])

        current_app.logger.info(
            f"Topline #{topline.id} créée par user #{current_user_id} sur track #{track_id}"
        )

        return _ok(
            data={
                'topline':          _topline_dict(topline, artist_user=current_user),
                'tokens_remaining': current_user.topline_tokens,
            },
            message='Topline enregistrée et traitée avec succès.',
        )

    except Exception as e:
        current_app.logger.error(f"Erreur upload topline: {e}", exc_info=True)
        return _err(
            f"Erreur lors du traitement audio : {e}",
            code='PROCESSING_ERROR', status=500,
        )


# ── POST /toplines/<id>/publish ────────────────────────────────────────────────

@topline_cud_api_bp.route('/<int:topline_id>/publish', methods=['POST'])
@jwt_required()
def publish_topline(topline_id):
    """Publier une topline (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = (
        db.session.query(Topline)
        .options(selectinload(Topline.artist_user))
        .get(topline_id)
    )
    if not topline:
        return _err('Topline introuvable.', code='NOT_FOUND', status=404)
    if topline.artist_id != current_user_id:
        return _err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        topline.is_published = True
        db.session.commit()

        return _ok(
            data={'topline': _topline_dict(topline)},
            message='Topline publiée avec succès.',
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur publication topline #{topline_id}: {e}", exc_info=True)
        return _err(str(e), code='SERVER_ERROR', status=500)


# ── DELETE /toplines/<id> ──────────────────────────────────────────────────────

@topline_cud_api_bp.route('/<int:topline_id>', methods=['DELETE'])
@jwt_required()
def delete_topline(topline_id):
    """Supprimer une topline (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = db.session.get(Topline, topline_id)
    if not topline:
        return _err('Topline introuvable.', code='NOT_FOUND', status=404)
    if topline.artist_id != current_user_id:
        return _err('Accès refusé.', code='FORBIDDEN', status=403)

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

        return _ok(
            data={'track_id': track_id},
            message='Topline supprimée.',
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur suppression topline #{topline_id}: {e}", exc_info=True)
        return _err(str(e), code='SERVER_ERROR', status=500)
