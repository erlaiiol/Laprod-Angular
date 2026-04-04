"""
Purchases API — GET /purchases : historique d'achats de l'utilisateur connecté
"""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import select
from extensions import db, csrf
from models import Purchase, Track, MixMasterRequest

purchases_api_bp = Blueprint('purchases_api', __name__, url_prefix='/purchases')


@purchases_api_bp.route('', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_my_purchases():
    """Retourne tous les achats de tracks de l'utilisateur connecté."""
    user_id = int(get_jwt_identity())

    purchases = db.session.scalars(
        select(Purchase)
        .where(Purchase.buyer_id == user_id)
        .order_by(Purchase.created_at.desc())
    ).all()

    data = [
        {
            'id':                      p.id,
            'format':                  p.format_purchased,
            'price_paid':              p.price_paid,
            'track_price':             p.track_price,
            'contract_price':          p.contract_price,
            'has_contract':            bool(p.contract_file),
            'created_at':              p.created_at.isoformat(),
            'stream_url':              f'/stream/tracks/{p.track_id}/download/{p.format_purchased}',
            'contract_url':            f'/stream/contracts/{p.id}' if p.contract_file else None,
            'track': {
                'id':                  p.track.id,
                'title':               p.track.title,
                'image_file':          p.track.image_file,
                'composer_username':   p.track.composer_user.username if p.track.composer_user else None,
                'composer_image':      p.track.composer_user.profile_image if p.track.composer_user else None,
            } if p.track else None,
        }
        for p in purchases
    ]

    # ── Commandes mix/master complétées ──────────────────────────────────────
    mm_orders = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.artist_id == user_id, MixMasterRequest.status == 'completed')
        .order_by(MixMasterRequest.completed_at.desc())
    ).all()

    mm_data = [
        {
            'id':                o.id,
            'title':             o.title,
            'total_price':       o.total_price,
            'completed_at':      o.completed_at.isoformat() if o.completed_at else None,
            'created_at':        o.created_at.isoformat(),
            'services': {
                'cleaning':  o.service_cleaning,
                'effects':   o.service_effects,
                'artistic':  o.service_artistic,
                'mastering': o.service_mastering,
            },
            'engineer_username': o.engineer.username if o.engineer else None,
            'engineer_image':    o.engineer.profile_image if o.engineer else None,
            'processed_file_preview_url':      f'/static/{o.processed_file_preview}' if o.processed_file_preview else None,
            'processed_file_preview_full_url': f'/static/{o.processed_file_preview_full}' if o.processed_file_preview_full else None,
            'download_url':      f'/mixmaster-artist/download/{o.id}',
        }
        for o in mm_orders
    ]

    return jsonify({
        'success': True,
        'data': {
            'purchases':      data,
            'total_spent':    round(sum(p.price_paid for p in purchases), 2),
            'mm_orders':      mm_data,
            'mm_total_spent': round(sum(o.total_price or 0 for o in mm_orders), 2),
        },
    }), 200
