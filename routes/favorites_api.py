"""
Favorites API — toggle, check, listening history (JWT)
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import select
from extensions import db, csrf
from models import Favorite, ListeningHistory, Track
from datetime import datetime

favorites_api_bp = Blueprint('favorites_api', __name__, url_prefix='/favorites-api')


@favorites_api_bp.route('/toggle/<int:track_id>', methods=['POST'])
@jwt_required()
@csrf.exempt
def toggle_favorite(track_id):
    """Ajoute ou retire un track des favoris."""
    user_id = int(get_jwt_identity())
    db.get_or_404(Track, track_id)

    existing = db.session.query(Favorite).filter_by(
        user_id=user_id, track_id=track_id
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'success': True, 'action': 'removed', 'is_favorite': False}), 200
    else:
        db.session.add(Favorite(user_id=user_id, track_id=track_id))
        db.session.commit()
        return jsonify({'success': True, 'action': 'added', 'is_favorite': True}), 200


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
def add_listening_history(track_id):
    """Enregistre une écoute. Garde les 10 dernières entrées uniques."""
    user_id = int(get_jwt_identity())
    db.get_or_404(Track, track_id)

    db.session.add(ListeningHistory(
        user_id=user_id,
        track_id=track_id,
        listened_at=datetime.now(),
    ))

    total = db.session.query(ListeningHistory).filter_by(user_id=user_id).count()
    if total > 10:
        oldest = (
            db.session.query(ListeningHistory)
            .filter_by(user_id=user_id)
            .order_by(ListeningHistory.listened_at.asc())
            .limit(total - 10)
            .all()
        )
        for entry in oldest:
            db.session.delete(entry)

    db.session.commit()
    return jsonify({'success': True}), 200
