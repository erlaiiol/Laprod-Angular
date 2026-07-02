"""
Recommendation API — routes de recommandation personnalisée.

GET  /api/recommendations/tracks      — top-N tracks personnalisés (ou cold start)
GET  /api/recommendations/my-profile  — vecteur de préférences utilisateur (debug)
"""

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from extensions import db
from models import ListenEvent
from serializers import ok, track_card, playlist_stats_for_tracks
from utils.auth_helpers import require_user
from utils.recommendation_service import (
    build_user_vector,
    get_cold_start_tracks,
    get_recommendations,
)

recommendation_api_bp = Blueprint(
    'recommendation_api', __name__, url_prefix='/api/recommendations'
)


@recommendation_api_bp.route('/tracks', methods=['GET'])
@jwt_required(optional=True)
def get_recommendation_tracks():
    """
    Retourne des tracks personnalisés si l'utilisateur est connecté et a ≥ 3
    événements d'écoute, sinon retourne les tracks les plus populaires.
    """
    identity     = get_jwt_identity()
    tag_category = request.args.get('tag_category', '').strip()

    if identity:
        user_id = int(identity)
        tracks, is_personalized = get_recommendations(user_id)
    else:
        tracks = get_cold_start_tracks()
        is_personalized = False

    if tag_category:
        tracks = [
            t for t in tracks
            if any(
                tag.category_obj and tag.category_obj.name == tag_category
                for tag in t.tags
            )
        ]

    pl_counts, pl_images = playlist_stats_for_tracks([t.id for t in tracks])
    return ok({
        'tracks': [track_card(t, pl_counts, pl_images) for t in tracks],
        'is_personalized': is_personalized,
    })


@recommendation_api_bp.route('/my-profile', methods=['GET'])
@jwt_required()
@require_user
def get_my_recommendation_profile(current_user):
    """Retourne le vecteur de préférences de l'utilisateur courant."""
    vector = build_user_vector(current_user.id)
    event_count = (
        db.session.query(ListenEvent)
        .filter_by(user_id=current_user.id)
        .count()
    )
    return ok({
        'profile': vector,
        'listen_event_count': event_count,
    })
