"""
Blueprint CONTRACTS API — GET endpoints pour les données d'achats/ventes (frontend Angular)

GET  /api/contracts/my      → Achats de l'utilisateur connecté (jwt_required)
GET  /api/contracts/sales   → Ventes de l'utilisateur connecté  (jwt_required)
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.orm import selectinload

from extensions import db
from models import Purchase, Track

contracts_api_bp = Blueprint('contracts_api', __name__, url_prefix='/api/contracts')


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok(data=None, message='', status=200):
    body = {'success': True, 'feedback': {'level': 'success', 'message': message}}
    if data is not None:
        body['data'] = data
    return jsonify(body), status


def _err(message, level='error', code=None, status=400):
    body = {'success': False, 'feedback': {'level': level, 'message': message}}
    if code:
        body['code'] = code
    return jsonify(body), status


def _purchase_dict(p):
    """Sérialise un Purchase dans le format API."""
    return {
        'id':                p.id,
        'track_id':          p.track_id,
        'format_purchased':  p.format_purchased,
        'price_paid':        p.price_paid,
        'track_price':       p.track_price,
        'contract_price':    p.contract_price,
        'platform_fee':      p.platform_fee,
        'composer_revenue':  p.composer_revenue,
        'contract_file':     p.contract_file,
        'created_at':        p.created_at.isoformat(),
        'track': {
            'id':                p.track.id,
            'title':             p.track.title,
            'image_file':        p.track.image_file,
            'composer_username': p.track.composer_user.username,
        } if p.track else None,
    }


# ── GET /api/contracts/my ──────────────────────────────────────────────────────

@contracts_api_bp.route('/my', methods=['GET'])
@jwt_required()
def get_my_purchases():
    """Achats de l'utilisateur connecté (en tant qu'acheteur)."""
    current_user_id = int(get_jwt_identity())

    purchases = (
        db.session.query(Purchase)
        .options(
            selectinload(Purchase.track).selectinload(Track.composer_user)
        )
        .filter_by(buyer_id=current_user_id)
        .order_by(Purchase.created_at.desc())
        .all()
    )

    return _ok(data={'purchases': [_purchase_dict(p) for p in purchases]})


# ── GET /api/contracts/sales ───────────────────────────────────────────────────

@contracts_api_bp.route('/sales', methods=['GET'])
@jwt_required()
def get_my_sales():
    """Ventes de l'utilisateur connecté (en tant que compositeur)."""
    current_user_id = int(get_jwt_identity())

    sales = (
        db.session.query(Purchase)
        .join(Track, Purchase.track_id == Track.id)
        .options(
            selectinload(Purchase.track).selectinload(Track.composer_user)
        )
        .filter(Track.composer_id == current_user_id)
        .order_by(Purchase.created_at.desc())
        .all()
    )

    total_revenue = sum(s.composer_revenue for s in sales)

    return _ok(data={
        'sales':         [_purchase_dict(s) for s in sales],
        'total_revenue': round(total_revenue, 2),
    })
