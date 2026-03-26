"""
Blueprint TOPLINES CUD API - Create/Update/Delete endpoints (jwt_required)

POST   /toplines/upload              → Upload voix + traitement + fusion → JSON
POST   /toplines/<id>/publish        → Publier une topline (propriétaire)
DELETE /toplines/<id>                → Supprimer une topline (propriétaire)
"""
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload
from datetime import datetime
from pathlib import Path
import config

from extensions import db, limiter
from models import Track, Topline, User

# Réutilise les helpers de traitement audio du blueprint Jinja existant
from routes.toplines import (
    convert_to_wav,
    apply_audio_effects,
    merge_voice_and_beat,
    cleanup_temp_files,
)

topline_cud_api_bp = Blueprint('topline_cud_api', __name__, url_prefix='/toplines')


@topline_cud_api_bp.route('/upload', methods=['POST'])
@jwt_required()
@limiter.limit("10 per hour")
def upload_topline():
    """
    Upload voix + traitement audio + fusion avec le beat.

    FormData attendu :
      - voice_file  : Blob audio (webm/mp3/wav)
      - track_id    : int
      - use_autotune: 'true' | 'false'
      - description : str (optionnel)
    """
    current_user_id = int(get_jwt_identity())
    current_user = db.session.get(User, current_user_id)

    if not current_user:
        return jsonify({'success': False, 'error': 'Utilisateur introuvable'}), 404

    # Vérifier les quotas de topline
    can_submit, quota_message = current_user.can_submit_topline()
    if not can_submit:
        return jsonify({'success': False, 'error': quota_message}), 403

    try:
        voice_file    = request.files.get('voice_file')
        track_id      = request.form.get('track_id')
        use_autotune  = request.form.get('use_autotune', 'false') == 'true'
        description   = request.form.get('description', '').strip()[:500] or None

        if not voice_file or not track_id:
            return jsonify({'success': False, 'error': 'voice_file et track_id sont requis'}), 400

        track = db.get_or_404(Track, int(track_id))

        if not track.is_approved:
            return jsonify({'success': False, 'error': 'Track non disponible'}), 403

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # ── Étape 1 : Sauvegarder le fichier RAW ──────────────────────────────
        content_type = voice_file.content_type or ''
        if 'webm' in content_type:
            ext = 'webm'
        elif 'mp3' in content_type or 'mpeg' in content_type:
            ext = 'mp3'
        elif 'mp4' in content_type:
            ext = 'm4a'
        else:
            ext = 'webm'

        toplines_dir = config.UPLOAD_FOLDER / 'toplines'
        toplines_dir.mkdir(parents=True, exist_ok=True)

        raw_filename = f"topline_raw_{track_id}_{current_user_id}_{timestamp}.{ext}"
        raw_path = toplines_dir / raw_filename
        voice_file.save(raw_path)

        # ── Étape 2 : Convertir en WAV ────────────────────────────────────────
        wav_temp_path = convert_to_wav(raw_path)

        # ── Étape 3 : Effets + auto-tune ──────────────────────────────────────
        wav_effects_path = apply_audio_effects(
            wav_temp_path,
            sample_rate=48000,
            autotune_key=track.key if use_autotune else None
        )

        # ── Étape 4 : Fusion voix + beat ──────────────────────────────────────
        beat_path = config.UPLOAD_FOLDER / track.audio_file.replace('audio/', '', 1)
        if not beat_path.exists():
            beat_path_alt = Path(current_app.root_path) / 'static' / track.audio_file
            if beat_path_alt.exists():
                beat_path = beat_path_alt
            else:
                cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])
                return jsonify({'success': False, 'error': 'Instrumentale introuvable'}), 404

        final_relative_path = merge_voice_and_beat(
            voice_path=wav_effects_path,
            beat_path=str(beat_path),
            track_id=track_id,
            user_id=current_user_id,
            timestamp=timestamp
        )

        # ── Étape 5 : Enregistrer en BDD ──────────────────────────────────────
        topline = Topline(
            track_id=int(track_id),
            artist_id=current_user_id,
            audio_file=final_relative_path,
            description=description,
        )
        db.session.add(topline)
        current_user.consume_topline_token()
        db.session.commit()

        # Nettoyer les fichiers temporaires
        cleanup_temp_files([raw_path, wav_temp_path, wav_effects_path])

        current_app.logger.info(
            f"Topline #{topline.id} créée par user #{current_user_id} sur track #{track_id}"
        )

        return jsonify({
            'success':          True,
            'topline_id':       topline.id,
            'audio_file':       topline.audio_file,
            'tokens_remaining': current_user.topline_tokens,
        })

    except Exception as e:
        current_app.logger.error(f"Erreur upload topline: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@topline_cud_api_bp.route('/<int:topline_id>/publish', methods=['POST'])
@jwt_required()
def publish_topline(topline_id):
    """Publier une topline (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = db.session.query(Topline).options(selectinload(Topline.artist_user)).get(topline_id)
    if not topline:
        return jsonify({'success': False, 'error': 'Topline introuvable'}), 404

    if topline.artist_id != current_user_id:
        return jsonify({'success': False, 'error': 'Accès refusé'}), 403

    try:
        topline.is_published = True
        db.session.commit()

        return jsonify({
            'success': True,
            'message': 'Topline publiée',
            'topline': {
                'id':           topline.id,
                'is_published': topline.is_published,
                'audio_file':   topline.audio_file,
                'description':  topline.description,
                'created_at':   topline.created_at.isoformat() if topline.created_at else None,
                'artist_user': {
                    'username':      topline.artist_user.username,
                    'profile_image': topline.artist_user.profile_image,
                } if topline.artist_user else None,
            }
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur publication topline #{topline_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@topline_cud_api_bp.route('/<int:topline_id>', methods=['DELETE'])
@jwt_required()
def delete_topline(topline_id):
    """Supprimer une topline (propriétaire uniquement)."""
    current_user_id = int(get_jwt_identity())

    topline = db.session.get(Topline, topline_id)
    if not topline:
        return jsonify({'success': False, 'error': 'Topline introuvable'}), 404

    if topline.artist_id != current_user_id:
        return jsonify({'success': False, 'error': 'Accès refusé'}), 403

    try:
        track_id = topline.track_id

        # Supprimer le fichier audio
        file_path = config.UPLOAD_FOLDER / topline.audio_file.replace('audio/', '', 1)
        if file_path.exists():
            file_path.unlink()
            current_app.logger.info(f"Fichier supprimé: {topline.audio_file}")

        db.session.delete(topline)
        db.session.commit()

        current_app.logger.info(f"Topline #{topline_id} supprimée par user #{current_user_id}")

        return jsonify({'success': True, 'message': 'Topline supprimée', 'track_id': track_id})

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Erreur suppression topline #{topline_id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500
