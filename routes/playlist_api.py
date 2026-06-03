"""
Playlist API — CRUD playlists beatmaker (JWT)

Endpoints :
  GET  /api/playlists/my                               → mes playlists
  POST /api/playlists                                  → créer une playlist
  GET  /api/playlists/<id>                             → détail public + signal reco
  PUT  /api/playlists/<id>                             → renommer / changer image
  DELETE /api/playlists/<id>                           → supprimer
  POST /api/playlists/<id>/tracks                      → ajouter un track
  DELETE /api/playlists/<id>/tracks/<track_id>         → retirer un track
  GET  /api/playlists/by-beatmaker/<username>          → playlists d'un beatmaker
  GET  /api/playlists/containing/<track_id>/by/<username> → IDs des playlists contenant ce track
"""
import uuid
from pathlib import Path

from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required, verify_jwt_in_request, get_jwt_identity
from sqlalchemy import func

from extensions import db, csrf
from models import Playlist, Track, User, playlist_track
from serializers import ok
from utils.auth_helpers import require_user
from utils.crud_helpers import (
    get_or_404, EntityForbidden, EntityNotFound,
    handle_route_exceptions, commit_or_rollback,
)
from utils.file_validator import validate_image_file

playlist_bp = Blueprint('playlist', __name__, url_prefix='/api/playlists')

_PLAYLISTS_IMG_DIR = Path('db_assets') / 'images' / 'playlists'


def _ensure_img_dir(app):
    d = Path(app.root_path) / _PLAYLISTS_IMG_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _serialize_playlist(pl, track_count=None):
    return {
        'id':                 pl.id,
        'title':              pl.title,
        'image_file':         pl.image_file,
        'beatmaker_username': pl.beatmaker.username,
        'track_count':        track_count if track_count is not None else len(pl.tracks),
        'created_at':         pl.created_at.isoformat() if pl.created_at else None,
    }


def _serialize_playlist_detail(pl):
    from serializers import track_card as ser_track_card
    # Pré-requête playlist_count pour éviter le N+1 sur les tracks de la playlist
    track_ids = [t.id for t in pl.tracks]
    counts, images = _playlist_stats_for_tracks(track_ids)
    tracks = [_enrich_track_card(t, counts, images) for t in pl.tracks]
    return {**_serialize_playlist(pl), 'tracks': tracks}


def _playlist_stats_for_tracks(track_ids: list[int]):
    """Retourne (counts_dict, first_images_dict) en deux requêtes SQL groupées."""
    if not track_ids:
        return {}, {}
    counts = dict(
        db.session.query(playlist_track.c.track_id, func.count(playlist_track.c.playlist_id))
        .filter(playlist_track.c.track_id.in_(track_ids))
        .group_by(playlist_track.c.track_id)
        .all()
    )
    # Première image par track : sous-requête avec row_number
    from sqlalchemy import select as sa_select, over, literal_column
    subq = (
        db.session.query(
            playlist_track.c.track_id,
            Playlist.image_file,
            func.row_number().over(
                partition_by=playlist_track.c.track_id,
                order_by=playlist_track.c.playlist_id
            ).label('rn')
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


def _enrich_track_card(track, counts: dict, images: dict):
    from serializers import track_card as ser_track_card
    d = ser_track_card(track)
    d['playlist_count']       = counts.get(track.id, 0)
    d['first_playlist_image'] = images.get(track.id)
    return d


def _save_playlist_image(file, app) -> str | None:
    """Valide et enregistre une image de playlist, retourne le chemin relatif."""
    if not file or not file.filename:
        return None
    is_valid, error = validate_image_file(file)
    if not is_valid:
        raise EntityForbidden(f"Image invalide : {error}")
    ext = Path(file.filename).suffix.lower() or '.jpg'
    filename = f"{uuid.uuid4()}{ext}"
    img_dir = _ensure_img_dir(app)
    file.save(img_dir / filename)
    return f"images/playlists/{filename}"


def _current_user_optional():
    """Retourne l'utilisateur authentifié ou None si pas de token valide."""
    try:
        verify_jwt_in_request(optional=True)
        raw = get_jwt_identity()
        if not raw:
            return None
        return db.session.get(User, int(raw))
    except Exception:
        return None


# ── GET /my ──────────────────────────────────────────────────────────────────

@playlist_bp.route('/my', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_my_playlists(current_user):
    playlists = (
        db.session.query(Playlist)
        .filter_by(beatmaker_id=current_user.id)
        .order_by(Playlist.created_at.desc())
        .all()
    )
    # Counts en une requête
    pl_ids = [p.id for p in playlists]
    counts_raw = (
        db.session.query(playlist_track.c.playlist_id, func.count(playlist_track.c.track_id))
        .filter(playlist_track.c.playlist_id.in_(pl_ids))
        .group_by(playlist_track.c.playlist_id)
        .all()
    ) if pl_ids else []
    counts = dict(counts_raw)
    return ok([_serialize_playlist(p, counts.get(p.id, 0)) for p in playlists])


# ── POST / — créer ────────────────────────────────────────────────────────────

@playlist_bp.route('', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def create_playlist(current_user):
    if not current_user.is_beatmaker:
        raise EntityForbidden("Seuls les beatmakers peuvent créer des playlists.")
    title = (request.form.get('title') or '').strip()
    if not title:
        raise EntityForbidden("Le titre est obligatoire.")
    image_path = _save_playlist_image(request.files.get('image'), current_app._get_current_object())
    pl = Playlist(beatmaker_id=current_user.id, title=title, image_file=image_path)
    db.session.add(pl)
    db.session.commit()
    return ok(_serialize_playlist(pl, 0), status=201)


# ── GET /<id> — détail public ─────────────────────────────────────────────────

@playlist_bp.route('/<int:playlist_id>', methods=['GET'])
@csrf.exempt
@handle_route_exceptions
def get_playlist(playlist_id):
    pl = get_or_404(Playlist, playlist_id, "Playlist introuvable.")
    viewer = _current_user_optional()
    # Signal recommandation si ≥ 3 tracks et utilisateur authentifié
    if viewer and len(pl.tracks) >= 3:
        try:
            from utils.recommendation_service import record_playlist_browse
            record_playlist_browse(viewer.id, pl.beatmaker_id, pl.tracks)
        except Exception:
            pass  # Ne jamais bloquer l'affichage pour un signal reco
    return ok(_serialize_playlist_detail(pl))


# ── PUT /<id> — modifier ──────────────────────────────────────────────────────

@playlist_bp.route('/<int:playlist_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def update_playlist(playlist_id, current_user):
    pl = get_or_404(Playlist, playlist_id)
    if pl.beatmaker_id != current_user.id:
        raise EntityForbidden("Vous ne pouvez modifier que vos propres playlists.")
    title = (request.form.get('title') or '').strip()
    if title:
        pl.title = title
    new_image = request.files.get('image')
    if new_image and new_image.filename:
        # Supprimer l'ancienne image si elle existe
        if pl.image_file:
            old_path = Path(current_app.root_path) / 'db_assets' / pl.image_file
            if old_path.exists():
                old_path.unlink(missing_ok=True)
        pl.image_file = _save_playlist_image(new_image, current_app._get_current_object())
    db.session.commit()
    return ok(_serialize_playlist(pl))


# ── DELETE /<id> ──────────────────────────────────────────────────────────────

@playlist_bp.route('/<int:playlist_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def delete_playlist(playlist_id, current_user):
    pl = get_or_404(Playlist, playlist_id)
    if pl.beatmaker_id != current_user.id:
        raise EntityForbidden("Vous ne pouvez supprimer que vos propres playlists.")
    if pl.image_file:
        img_path = Path(current_app.root_path) / 'db_assets' / pl.image_file
        img_path.unlink(missing_ok=True)
    db.session.delete(pl)
    db.session.commit()
    return ok()


# ── POST /<id>/tracks — ajouter ───────────────────────────────────────────────

@playlist_bp.route('/<int:playlist_id>/tracks', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def add_track(playlist_id, current_user):
    pl = get_or_404(Playlist, playlist_id)
    if pl.beatmaker_id != current_user.id:
        raise EntityForbidden("Vous ne pouvez modifier que vos propres playlists.")
    data = request.get_json(silent=True) or {}
    track_id = data.get('track_id')
    if not track_id:
        raise EntityForbidden("track_id requis.")
    track = get_or_404(Track, track_id, "Track introuvable.")
    if track.composer_id != current_user.id and not current_user.is_admin:
        raise EntityForbidden("Vous ne pouvez ajouter que vos propres tracks.")
    # Eviter les doublons
    already = db.session.execute(
        db.select(playlist_track).where(
            playlist_track.c.playlist_id == playlist_id,
            playlist_track.c.track_id == track_id,
        )
    ).first()
    if already:
        return ok({'message': 'Track déjà présent dans cette playlist.'})
    # Position = dernier + 1
    max_pos = db.session.query(func.max(playlist_track.c.position)).filter(
        playlist_track.c.playlist_id == playlist_id
    ).scalar() or 0
    db.session.execute(
        playlist_track.insert().values(
            playlist_id=playlist_id, track_id=track_id, position=max_pos + 1
        )
    )
    db.session.commit()
    return ok(status=201)


# ── DELETE /<id>/tracks/<track_id> — retirer ─────────────────────────────────

@playlist_bp.route('/<int:playlist_id>/tracks/<int:track_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def remove_track(playlist_id, track_id, current_user):
    pl = get_or_404(Playlist, playlist_id)
    if pl.beatmaker_id != current_user.id:
        raise EntityForbidden("Vous ne pouvez modifier que vos propres playlists.")
    result = db.session.execute(
        playlist_track.delete().where(
            playlist_track.c.playlist_id == playlist_id,
            playlist_track.c.track_id == track_id,
        )
    )
    if result.rowcount == 0:
        raise EntityNotFound("Ce track n'est pas dans cette playlist.")
    db.session.commit()
    return ok()


# ── GET /by-beatmaker/<username> ──────────────────────────────────────────────

@playlist_bp.route('/by-beatmaker/<username>', methods=['GET'])
@csrf.exempt
@handle_route_exceptions
def get_by_beatmaker(username):
    beatmaker = db.session.query(User).filter_by(username=username).first()
    if not beatmaker:
        raise EntityNotFound(f"Utilisateur '{username}' introuvable.")
    playlists = (
        db.session.query(Playlist)
        .filter_by(beatmaker_id=beatmaker.id)
        .order_by(Playlist.created_at.desc())
        .all()
    )
    pl_ids = [p.id for p in playlists]
    counts_raw = (
        db.session.query(playlist_track.c.playlist_id, func.count(playlist_track.c.track_id))
        .filter(playlist_track.c.playlist_id.in_(pl_ids))
        .group_by(playlist_track.c.playlist_id)
        .all()
    ) if pl_ids else []
    counts = dict(counts_raw)
    return ok([_serialize_playlist(p, counts.get(p.id, 0)) for p in playlists])


# ── GET /containing/<track_id>/by/<username> ─────────────────────────────────

@playlist_bp.route('/containing/<int:track_id>/by/<username>', methods=['GET'])
@csrf.exempt
@handle_route_exceptions
def get_containing(track_id, username):
    beatmaker = db.session.query(User).filter_by(username=username).first()
    if not beatmaker:
        raise EntityNotFound(f"Utilisateur '{username}' introuvable.")
    rows = (
        db.session.query(playlist_track.c.playlist_id)
        .join(Playlist, Playlist.id == playlist_track.c.playlist_id)
        .filter(
            playlist_track.c.track_id == track_id,
            Playlist.beatmaker_id == beatmaker.id,
        )
        .all()
    )
    return ok([r[0] for r in rows])
