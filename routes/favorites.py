"""
Blueprint FAVORITES - Gestion des favoris et historique d'écoute
Routes pour ajouter/retirer des favoris et enregistrer l'historique d'écoute
"""
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime

from extensions import db
from models import Favorite, ListeningHistory, Track

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

favorites_bp = Blueprint('favorites', __name__)


# ============================================
# ROUTE 1 : TOGGLE FAVORITE
# ============================================

@favorites_bp.route('/toggle-favorite/<int:track_id>', methods=['POST'])
@login_required
def toggle_favorite(track_id):
    """Ajoute ou retire un track des favoris de l'utilisateur"""

    track = db.get_or_404(Track, track_id)

    # Vérifier si déjà en favoris
    existing_favorite = db.session.query(Favorite).filter_by(
        user_id=current_user.id,
        track_id=track_id
    ).first()

    if existing_favorite:
        # Retirer des favoris
        db.session.delete(existing_favorite)
        db.session.commit()
        return jsonify({
            'success': True,
            'action': 'removed',
            'message': 'Track retiré des favoris'
        })
    else:
        # Ajouter aux favoris
        new_favorite = Favorite(
            user_id=current_user.id,
            track_id=track_id
        )
        db.session.add(new_favorite)
        db.session.commit()
        return jsonify({
            'success': True,
            'action': 'added',
            'message': 'Track ajouté aux favoris'
        })


# ============================================
# ROUTE 2 : CHECK IF FAVORITE
# ============================================

@favorites_bp.route('/is-favorite/<int:track_id>', methods=['GET'])
@login_required
def is_favorite(track_id):
    """Vérifie si un track est en favoris"""

    is_fav = db.session.query(Favorite).filter_by(
        user_id=current_user.id,
        track_id=track_id
    ).first() is not None

    return jsonify({'is_favorite': is_fav})


# ============================================
# ROUTE 3 : ADD LISTENING HISTORY
# ============================================

@favorites_bp.route('/add-listening-history/<int:track_id>', methods=['POST'])
@login_required
def add_listening_history(track_id):
    """
    Enregistre qu'un utilisateur a écouté un track.
    Garde seulement les 10 derniers tracks écoutés.
    """

    track = db.get_or_404(Track, track_id)

    # Ajouter à l'historique
    new_history = ListeningHistory(
        user_id=current_user.id,
        track_id=track_id,
        listened_at=datetime.now()
    )
    db.session.add(new_history)

    # Garder seulement les 10 derniers
    # Compter combien d'entrées existent
    total_count = db.session.query(ListeningHistory).filter_by(user_id=current_user.id).count()

    if total_count > 10:
        # Supprimer les plus anciennes
        oldest_entries = (
            db.session.query(ListeningHistory).filter_by(user_id=current_user.id)
            .order_by(ListeningHistory.listened_at.asc())
            .limit(total_count - 10)
            .all()
        )

        for entry in oldest_entries:
            db.session.delete(entry)

    db.session.commit()

    return jsonify({
        'success': True,
        'message': 'Historique mis à jour'
    })
