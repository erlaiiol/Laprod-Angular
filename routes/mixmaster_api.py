"""
Mixmaster API — GET endpoints (public + JWT)
Ingénieurs certifiés, détail commande, historique artiste
"""
from flask import Blueprint
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from sqlalchemy import select
from extensions import db, csrf
from models import User, MixMasterRequest
from serializers import ok, err, mix_engineer, mix_order_full as ser_order_full

mixmaster_api_bp = Blueprint('mixmaster_api', __name__, url_prefix='/api/mixmaster')


# ─── Ingénieurs certifiés (public) ────────────────────────────────────────────

@mixmaster_api_bp.route('/engineers', methods=['GET'])
@csrf.exempt
def get_engineers():
    """Liste des ingénieurs certifiés (public)."""
    engineers = db.session.scalars(
        select(User).where(User.is_mixmaster_engineer == True).order_by(User.username)
    ).all()
    return ok({'engineers': [mix_engineer(e) for e in engineers]})


@mixmaster_api_bp.route('/engineers/<int:engineer_id>', methods=['GET'])
@csrf.exempt
def get_engineer(engineer_id):
    """Détail d'un ingénieur (public)."""
    eng = db.get_or_404(User, engineer_id)
    if not eng.is_mixmaster_engineer:
        return err('Ingénieur introuvable.', status=404)
    return ok({'engineer': mix_engineer(eng)})


# ─── Demandes de l'artiste (JWT) ──────────────────────────────────────────────

@mixmaster_api_bp.route('/my-requests', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_my_requests():
    """Demandes de mix/master de l'artiste connecté."""
    user_id = int(get_jwt_identity())
    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.artist_id == user_id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()
    return ok({'requests': [ser_order_full(o, 'artist') for o in orders]})


# ─── Commandes de l'ingénieur (JWT) ───────────────────────────────────────────

@mixmaster_api_bp.route('/my-orders', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_my_orders():
    """Commandes de mix/master reçues par l'ingénieur connecté."""
    user_id = int(get_jwt_identity())
    user = db.get_or_404(User, user_id)
    if not user.is_mix_engineer:
        return err('Accès refusé.', status=403)

    orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.engineer_id == user_id)
        .order_by(MixMasterRequest.created_at.desc())
    ).all()
    return ok({'orders': [ser_order_full(o, 'engineer') for o in orders]})


# ─── Détail d'une commande (JWT — artiste ou ingénieur) ───────────────────────

@mixmaster_api_bp.route('/orders/<int:order_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_order(order_id):
    """Détail complet d'une commande (artiste ou ingénieur concerné)."""
    user_id = int(get_jwt_identity())
    order = db.get_or_404(MixMasterRequest, order_id)
    if order.artist_id != user_id and order.engineer_id != user_id:
        return err('Accès refusé.', status=403)
    return ok({'order': ser_order_full(order)})
