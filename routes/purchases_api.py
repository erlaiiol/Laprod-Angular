"""
Purchases API — historique d'achats de l'utilisateur connecté

GET  /api/purchases           → liste achats + commandes MM
GET  /api/purchases/<id>/invoice → PDF facture acheteur (généré à la volée)
"""
from flask import Blueprint, send_file
from flask_jwt_extended import jwt_required
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from io import BytesIO

from extensions import db, csrf
from models import Purchase, Track, MixMasterRequest, User
from serializers import ok, err
from utils.auth_helpers import require_user

purchases_api_bp = Blueprint('purchases_api', __name__, url_prefix='/api/purchases')


def _p_dict(p):
    """Sérialise un Purchase en évitant les Decimal non-sérialisables."""
    return {
        'id':             p.id,
        'format':         p.format_purchased,
        'price_paid':     float(p.price_paid)     if p.price_paid     is not None else 0.0,
        'track_price':    float(p.track_price)    if p.track_price    is not None else 0.0,
        'contract_price': float(p.contract_price) if p.contract_price is not None else 0.0,
        'has_contract':   bool(p.contract_file),
        'created_at':     p.created_at.isoformat(),
        'stream_url':     f'/api/stream/tracks/{p.track_id}/download/{p.format_purchased}',
        'contract_url':   f'/api/stream/contracts/{p.id}' if p.contract_file else None,
        'invoice_url':    f'/api/purchases/{p.id}/invoice',
        'track': {
            'id':                p.track.id,
            'title':             p.track.title,
            'image_file':        p.track.image_file,
            'composer_username': p.track.composer_user.username if p.track.composer_user else None,
            'composer_image':    p.track.composer_user.profile_image if p.track.composer_user else None,
        } if p.track else None,
    }


@purchases_api_bp.route('', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_my_purchases(current_user):
    """Retourne tous les achats de tracks et commandes MM de l'utilisateur connecté."""
    purchases = db.session.scalars(
        select(Purchase)
        .options(
            selectinload(Purchase.track).selectinload(Track.composer_user)
        )
        .where(Purchase.buyer_id == current_user.id)
        .order_by(Purchase.created_at.desc())
    ).all()

    mm_orders = db.session.scalars(
        select(MixMasterRequest)
        .where(
            MixMasterRequest.artist_id == current_user.id,
            MixMasterRequest.status == 'completed',
        )
        .order_by(MixMasterRequest.completed_at.desc())
    ).all()

    mm_data = [
        {
            'id':                               o.id,
            'title':                            o.title,
            'total_price':                      float(o.total_price) if o.total_price is not None else 0.0,
            'completed_at':                     o.completed_at.isoformat() if o.completed_at else None,
            'created_at':                       o.created_at.isoformat(),
            'services': {
                'cleaning':  o.service_cleaning,
                'effects':   o.service_effects,
                'artistic':  o.service_artistic,
                'mastering': o.service_mastering,
            },
            'engineer_username':                o.engineer.username if o.engineer else None,
            'engineer_image':                   o.engineer.profile_image if o.engineer else None,
            'processed_file_preview_url':       f'/static/{o.processed_file_preview}' if o.processed_file_preview else None,
            'processed_file_preview_full_url':  f'/static/{o.processed_file_preview_full}' if o.processed_file_preview_full else None,
            'download_url':                     f'/mixmaster-artist/download/{o.id}',
        }
        for o in mm_orders
    ]

    total_spent = round(sum(float(p.price_paid) for p in purchases), 2)

    return ok({
        'purchases':      [_p_dict(p) for p in purchases],
        'total_spent':    total_spent,
        'mm_orders':      mm_data,
        'mm_total_spent': round(sum(float(o.total_price or 0) for o in mm_orders), 2),
    })


@purchases_api_bp.route('/<int:purchase_id>/invoice', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_invoice(purchase_id, current_user):
    """Génère et retourne la facture PDF de l'acheteur (à la volée)."""
    purchase = db.session.scalar(
        select(Purchase)
        .options(
            selectinload(Purchase.track).selectinload(Track.composer_user),
            selectinload(Purchase.buyer_user),
        )
        .where(Purchase.id == purchase_id)
    )

    if not purchase:
        return err('Achat introuvable.', status=404)

    if purchase.buyer_id != current_user.id:
        return err('Accès non autorisé.', status=403)

    try:
        from utils.invoice_generator import generate_track_purchase_invoice
        pdf_bytes = generate_track_purchase_invoice(purchase)
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f'Erreur génération facture purchase #{purchase_id}: {e}', exc_info=True)
        return err('Impossible de générer la facture.', status=500)

    title = purchase.track.title if purchase.track else 'beat'
    filename = f'facture_laprod_{purchase_id}_{title}.pdf'.replace(' ', '_')

    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )
