"""
Blueprint TOPLINES API - GET endpoints (lecture seule, publics + authentifiés)

GET /toplines/track/<track_id>   → toplines publiées d'une track (public)
GET /toplines/my/<track_id>      → toplines de l'utilisateur courant (jwt_required)
"""
from flask import Blueprint, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from sqlalchemy.orm import selectinload

from extensions import db
from models import Track, Topline, User
from serializers import ok, err, topline as ser_topline

toplines_api_bp = Blueprint('toplines_api', __name__, url_prefix='/api/toplines')


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
