"""
Favorites API — toggle, check, listening history (JWT)
"""
from flask import Blueprint, jsonify, request as flask_request
from flask_jwt_extended import jwt_required, verify_jwt_in_request
from sqlalchemy import select
from extensions import db, csrf, limiter
from models import Favorite, ListenEvent, ListeningHistory, Track
from serializers import ok, err
from datetime import datetime
from utils.auth_helpers import require_user
from utils.recommendation_service import invalidate_user_vector_cache

favorites_api_bp = Blueprint('favorites_api', __name__, url_prefix='/api/favorites')


@favorites_api_bp.route('/toggle/<int:track_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def toggle_favorite(track_id, current_user):
    """Ajoute ou retire un track des favoris."""
    db.get_or_404(Track, track_id)

    existing = db.session.query(Favorite).filter_by(
        user_id=current_user.id, track_id=track_id
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        invalidate_user_vector_cache(current_user.id)
        return ok({'action': 'removed', 'is_favorite': False})
    else:
        db.session.add(Favorite(user_id=current_user.id, track_id=track_id))
        db.session.commit()
        invalidate_user_vector_cache(current_user.id)
        return ok({'action': 'added', 'is_favorite': True})


@favorites_api_bp.route('/check-batch', methods=['GET'])
@csrf.exempt
def check_favorites_batch():
    """Vérifie si plusieurs tracks sont en favoris en une seule requête."""
    ids_param = flask_request.args.get('ids', '')
    try:
        track_ids = [int(i) for i in ids_param.split(',') if i.strip()]
    except ValueError:
        return jsonify({'success': False, 'data': {}}), 400

    try:
        verify_jwt_in_request(optional=True)
        from flask_jwt_extended import get_jwt_identity as _gji
        raw = _gji()
        user_id = int(raw) if raw else None
    except Exception:
        user_id = None

    result = {str(tid): False for tid in track_ids}
    if user_id and track_ids:
        favs = db.session.query(Favorite.track_id).filter(
            Favorite.user_id == user_id,
            Favorite.track_id.in_(track_ids)
        ).all()
        for (tid,) in favs:
            result[str(tid)] = True

    return ok(result)


@favorites_api_bp.route('/check/<int:track_id>', methods=['GET'])
@csrf.exempt
def check_favorite(track_id):
    """Vérifie si un track est en favoris (optionnel : retourne False si non connecté)."""
    try:
        verify_jwt_in_request(optional=True)
        from flask_jwt_extended import get_jwt_identity as _gji
        raw = _gji()
        user_id = int(raw) if raw else None
    except Exception:
        user_id = None

    if not user_id:
        return jsonify({'is_favorite': False}), 200

    is_fav = db.session.query(Favorite).filter_by(
        user_id=user_id, track_id=track_id
    ).first() is not None

    return jsonify({'is_favorite': is_fav}), 200


@favorites_api_bp.route('/listening/<int:track_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
@limiter.exempt
@require_user
def add_listening_history(track_id, current_user):
    """Enregistre une écoute. Garde les 10 dernières entrées uniques."""
    db.get_or_404(Track, track_id)

    existing = db.session.query(ListeningHistory).filter_by(
        user_id=current_user.id, track_id=track_id
    ).first()

    if existing:
        # Track déjà dans l'historique → mettre à jour la date (pas de doublon)
        existing.listened_at = datetime.now()
    else:
        db.session.add(ListeningHistory(
            user_id=current_user.id,
            track_id=track_id,
            listened_at=datetime.now(),
        ))
        # Trimmer à 10 entrées uniques seulement lors d'un ajout
        total = db.session.query(ListeningHistory).filter_by(user_id=current_user.id).count()
        if total > 10:
            oldest = (
                db.session.query(ListeningHistory)
                .filter_by(user_id=current_user.id)
                .order_by(ListeningHistory.listened_at.asc())
                .limit(total - 10)
                .all()
            )
            for entry in oldest:
                db.session.delete(entry)

    # Enregistrer un ListenEvent si le client fournit les données de durée
    body = flask_request.get_json(silent=True) or {}
    duration_listened = body.get('duration_listened', 0)
    track_duration = body.get('track_duration', 0)
    source = body.get('source', 'home')

    if duration_listened > 0 and track_duration > 0:
        ratio = min(duration_listened / track_duration, 1.0)
        db.session.add(ListenEvent(
            user_id=current_user.id,
            track_id=track_id,
            duration_listened=float(duration_listened),
            track_duration=float(track_duration),
            completion_ratio=ratio,
            source=source,
        ))
        invalidate_user_vector_cache(current_user.id)

    db.session.commit()
    return ok()
