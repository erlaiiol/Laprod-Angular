"""
Mode Clip — comptage des clips vidéo (docs/roadmap.md § Chantier 4, Passe 3).

Le clip est rendu, filigrané et monté 100 % sur l'appareil : AUCUNE vidéo ne
transite par le serveur. L'app signale seulement qu'un clip a été enregistré
dans la galerie ou partagé, pour :
  - le compteur « clips » des stats beatmaker (à côté des vues, gratuit) ;
  - la mesure d'acquisition (cible de partage).
"""
import re

from flask import Blueprint, current_app, request
from flask_jwt_extended import jwt_required

from extensions import csrf, db, limiter
from models import SocialClipEvent, Track
from serializers import err, ok
from utils.auth_helpers import require_user
from utils.crud_helpers import commit_or_rollback, handle_route_exceptions

clips_api_bp = Blueprint('clips_api', __name__, url_prefix='/api/clips')

# Identifiant de clip généré par l'app (crypto.randomUUID) — format strict.
_UID_RE = re.compile(r'^[0-9a-fA-F-]{8,36}$')


@clips_api_bp.route('/events', methods=['POST'])
@csrf.exempt                 # R7 : TOUJOURS en premier après @route
@jwt_required()
@limiter.limit('120 per hour')
@handle_route_exceptions
@require_user
@commit_or_rollback
def record_clip_event(current_user):
    # R1 : le Mode Clip est réservé Premium+ ; l'UI le verrouille, le serveur aussi.
    if not current_user.can_make_clips:
        return err('Le Mode Clip est réservé aux membres Premium.', code='PREMIUM_REQUIRED', status=403)

    data = request.get_json(silent=True) or {}

    try:
        track_id = int(data.get('track_id'))
        duration = int(data.get('duration_s'))
    except (TypeError, ValueError):
        return err('Informations du clip incomplètes.', code='INVALID_CLIP_EVENT')

    mode   = data.get('mode')
    action = data.get('action')
    uid    = str(data.get('clip_uid') or '')
    if mode not in SocialClipEvent.MODES or action not in SocialClipEvent.ACTIONS or not _UID_RE.match(uid):
        return err('Informations du clip incomplètes.', code='INVALID_CLIP_EVENT')
    # Double verrou du plafond produit (45 s) : l'app et le natif le garantissent déjà.
    if duration < 0 or duration > SocialClipEvent.MAX_DURATION_S:
        return err('Un clip dure 45 secondes au maximum.', code='INVALID_CLIP_DURATION')

    track = db.session.get(Track, track_id)
    if track is None:
        return err('Ce beat n\'existe plus.', code='TRACK_NOT_FOUND', status=404)

    target = data.get('target')
    if target not in SocialClipEvent.TARGETS:
        target = 'share' if action == 'shared' else None

    db.session.add(SocialClipEvent(
        track_id=track.id, user_id=current_user.id, clip_uid=uid,
        mode=mode, action=action, target=target, duration_s=duration,
    ))
    current_app.logger.info('clip %s track=%s mode=%s target=%s', action, track.id, mode, target)
    return ok({'recorded': True}, status=201)
