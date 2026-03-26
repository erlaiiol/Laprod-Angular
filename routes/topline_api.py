"""
Blueprint TOPLINES API - GET endpoints (lecture seule, publics + authentifiés)

GET /toplines/track/<track_id>   → toplines publiées d'une track (public)
GET /toplines/my/<track_id>      → toplines de l'utilisateur courant (jwt_required)
"""
from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from sqlalchemy.orm import selectinload

from extensions import db
from models import Track, Topline, User

topline_api_bp = Blueprint('topline_api', __name__, url_prefix='/toplines')


def _topline_to_dict(tl):
    return {
        'id':           tl.id,
        'audio_file':   tl.audio_file,
        'description':  tl.description,
        'is_published': tl.is_published,
        'created_at':   tl.created_at.isoformat() if tl.created_at else None,
        'artist_user': {
            'username':      tl.artist_user.username,
            'profile_image': tl.artist_user.profile_image,
        } if tl.artist_user else None,
    }


@topline_api_bp.route('/track/<int:track_id>', methods=['GET'])
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

    return jsonify({
        'success': True,
        'data': {
            'toplines': [_topline_to_dict(tl) for tl in toplines]
        }
    })


@topline_api_bp.route('/my/<int:track_id>', methods=['GET'])
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

    return jsonify({
        'success': True,
        'data': {
            'toplines': [_topline_to_dict(tl) for tl in toplines]
        }
    })
