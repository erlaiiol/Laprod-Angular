"""
Invoice API — téléchargement de factures PDF pour les achats et demandes MixMaster.

Endpoints utilisateur :
  GET /api/invoices/purchase/<id>             → facture acheteur (Purchase)
  GET /api/invoices/purchase/<id>/statement   → relevé de vente compositeur (Purchase)
  GET /api/invoices/mixmaster/<id>            → facture artiste (MixMasterRequest)
  GET /api/invoices/mixmaster/<id>/earnings/<stage> → relevé ingénieur

Endpoint admin :
  GET /api/admin/invoices                     → liste paginée (purchases + MM)
"""

from flask import Blueprint, send_file, current_app
from flask_jwt_extended import jwt_required
from sqlalchemy import select, or_
from extensions import db, csrf
from models import Purchase, MixMasterRequest
from serializers import ok, err
from utils.auth_helpers import require_user, require_admin
from utils.invoice_generator import (
    generate_track_purchase_invoice,
    generate_track_sale_statement,
    generate_mixmaster_invoice,
    generate_mixmaster_earnings_statement,
)
import io

invoice_api_bp = Blueprint('invoice_api', __name__)

_VALID_STAGES = {'deposit', 'revision1', 'revision2', 'final'}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pdf_response(pdf_bytes: bytes, filename: str):
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Routes utilisateur — Purchase
# ══════════════════════════════════════════════════════════════════════════════

@invoice_api_bp.route('/api/invoices/purchase/<int:purchase_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_purchase_invoice(current_user, purchase_id: int):
    """Facture acheteur pour un achat de track."""
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Achat introuvable.', code='NOT_FOUND', status=404)
    if purchase.buyer_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        pdf = generate_track_purchase_invoice(purchase)
    except Exception as e:
        current_app.logger.error(f"Erreur génération facture purchase#{purchase_id}: {e}")
        return err('Impossible de générer la facture.', code='PDF_ERROR', status=500)

    year = purchase.created_at.year
    return _pdf_response(pdf, f"facture_laprod_{year}_{purchase_id}.pdf")


@invoice_api_bp.route('/api/invoices/purchase/<int:purchase_id>/statement', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_sale_statement(current_user, purchase_id: int):
    """Relevé de vente compositeur pour un achat de track."""
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Achat introuvable.', code='NOT_FOUND', status=404)
    if not purchase.track or purchase.track.composer_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        pdf = generate_track_sale_statement(purchase)
    except Exception as e:
        current_app.logger.error(f"Erreur génération relevé vente purchase#{purchase_id}: {e}")
        return err('Impossible de générer le relevé.', code='PDF_ERROR', status=500)

    year = purchase.created_at.year
    return _pdf_response(pdf, f"releve_vente_laprod_{year}_{purchase_id}.pdf")


# ══════════════════════════════════════════════════════════════════════════════
# Routes utilisateur — MixMaster
# ══════════════════════════════════════════════════════════════════════════════

@invoice_api_bp.route('/api/invoices/mixmaster/<int:mm_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_mixmaster_invoice(current_user, mm_id: int):
    """Facture artiste pour une demande MixMaster."""
    mm = db.session.get(MixMasterRequest, mm_id)
    if not mm:
        return err('Demande introuvable.', code='NOT_FOUND', status=404)
    if mm.artist_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        pdf = generate_mixmaster_invoice(mm)
    except Exception as e:
        current_app.logger.error(f"Erreur génération facture mixmaster#{mm_id}: {e}")
        return err('Impossible de générer la facture.', code='PDF_ERROR', status=500)

    year = mm.created_at.year
    return _pdf_response(pdf, f"facture_mixmaster_laprod_{year}_{mm_id}.pdf")


@invoice_api_bp.route('/api/invoices/mixmaster/<int:mm_id>/earnings/<stage>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_mixmaster_earnings(current_user, mm_id: int, stage: str):
    """Relevé de gains ingénieur pour une étape de paiement MixMaster."""
    if stage not in _VALID_STAGES:
        return err(f"Étape invalide. Valeurs acceptées : {', '.join(_VALID_STAGES)}",
                   code='INVALID_STAGE', status=400)

    mm = db.session.get(MixMasterRequest, mm_id)
    if not mm:
        return err('Demande introuvable.', code='NOT_FOUND', status=404)
    if mm.engineer_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    try:
        pdf = generate_mixmaster_earnings_statement(mm, stage)
    except Exception as e:
        current_app.logger.error(f"Erreur génération relevé gains mixmaster#{mm_id} stage={stage}: {e}")
        return err('Impossible de générer le relevé.', code='PDF_ERROR', status=500)

    year = mm.created_at.year
    return _pdf_response(pdf, f"releve_gains_mixmaster_laprod_{year}_{mm_id}_{stage}.pdf")


# ══════════════════════════════════════════════════════════════════════════════
# Routes admin — liste des factures
# ══════════════════════════════════════════════════════════════════════════════

@invoice_api_bp.route('/api/admin/invoices', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_list_invoices(current_user):
    """Liste paginée des achats de tracks et demandes MixMaster pour l'admin."""
    purchases = db.session.scalars(
        select(Purchase).order_by(Purchase.created_at.desc())
    ).all()

    mm_requests = db.session.scalars(
        select(MixMasterRequest)
        .where(MixMasterRequest.status.in_(['accepted', 'processing', 'delivered',
                                            'revision1', 'revision2', 'completed']))
        .order_by(MixMasterRequest.created_at.desc())
    ).all()

    purchases_data = [
        {
            'id':            p.id,
            'type':          'purchase',
            'created_at':    p.created_at.isoformat(),
            'buyer':         p.buyer_user.username if p.buyer_user else '—',
            'buyer_email':   p.buyer_user.email    if p.buyer_user else '—',
            'composer':      p.track.composer_user.username if p.track and p.track.composer_user else '—',
            'track_title':   p.track.title if p.track else '—',
            'format':        p.format_purchased,
            'amount':        float(p.price_paid),
            'invoice_url':   f'/api/admin/invoices/purchase/{p.id}',
            'statement_url': f'/api/admin/invoices/purchase/{p.id}/statement',
        }
        for p in purchases
    ]

    mm_data = [
        {
            'id':          mm.id,
            'type':        'mixmaster',
            'created_at':  mm.created_at.isoformat(),
            'artist':      mm.artist.username  if mm.artist  else '—',
            'engineer':    mm.engineer.username if mm.engineer else '—',
            'title':       mm.title,
            'status':      mm.status,
            'amount':      float(mm.total_price),
            'invoice_url':       f'/api/admin/invoices/mixmaster/{mm.id}',
            'earnings_urls': {
                'deposit':   f'/api/admin/invoices/mixmaster/{mm.id}/earnings/deposit',
                'revision1': f'/api/admin/invoices/mixmaster/{mm.id}/earnings/revision1',
                'revision2': f'/api/admin/invoices/mixmaster/{mm.id}/earnings/revision2',
                'final':     f'/api/admin/invoices/mixmaster/{mm.id}/earnings/final',
            },
        }
        for mm in mm_requests
    ]

    return ok({
        'purchases':   purchases_data,
        'mm_requests': mm_data,
        'totals': {
            'purchases_count': len(purchases_data),
            'mm_count':        len(mm_data),
            'purchases_revenue': round(sum(p['amount'] for p in purchases_data), 2),
            'mm_revenue':        round(sum(m['amount'] for m in mm_data), 2),
        },
    })


# ── Routes admin de téléchargement (bypass restriction user) ─────────────────

@invoice_api_bp.route('/api/admin/invoices/purchase/<int:purchase_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_download_purchase_invoice(current_user, purchase_id: int):
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Achat introuvable.', code='NOT_FOUND', status=404)
    try:
        pdf = generate_track_purchase_invoice(purchase)
    except Exception as e:
        current_app.logger.error(f"Admin: erreur génération facture purchase#{purchase_id}: {e}")
        return err('Impossible de générer la facture.', code='PDF_ERROR', status=500)
    year = purchase.created_at.year
    return _pdf_response(pdf, f"admin_facture_laprod_{year}_{purchase_id}.pdf")


@invoice_api_bp.route('/api/admin/invoices/purchase/<int:purchase_id>/statement', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_download_sale_statement(current_user, purchase_id: int):
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Achat introuvable.', code='NOT_FOUND', status=404)
    try:
        pdf = generate_track_sale_statement(purchase)
    except Exception as e:
        current_app.logger.error(f"Admin: erreur génération relevé vente purchase#{purchase_id}: {e}")
        return err('Impossible de générer le relevé.', code='PDF_ERROR', status=500)
    year = purchase.created_at.year
    return _pdf_response(pdf, f"admin_releve_vente_laprod_{year}_{purchase_id}.pdf")


@invoice_api_bp.route('/api/admin/invoices/mixmaster/<int:mm_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_download_mixmaster_invoice(current_user, mm_id: int):
    mm = db.session.get(MixMasterRequest, mm_id)
    if not mm:
        return err('Demande introuvable.', code='NOT_FOUND', status=404)
    try:
        pdf = generate_mixmaster_invoice(mm)
    except Exception as e:
        current_app.logger.error(f"Admin: erreur génération facture mixmaster#{mm_id}: {e}")
        return err('Impossible de générer la facture.', code='PDF_ERROR', status=500)
    year = mm.created_at.year
    return _pdf_response(pdf, f"admin_facture_mixmaster_laprod_{year}_{mm_id}.pdf")


@invoice_api_bp.route('/api/admin/invoices/mixmaster/<int:mm_id>/earnings/<stage>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_admin
def admin_download_mixmaster_earnings(current_user, mm_id: int, stage: str):
    if stage not in _VALID_STAGES:
        return err(f"Étape invalide. Valeurs acceptées : {', '.join(_VALID_STAGES)}",
                   code='INVALID_STAGE', status=400)
    mm = db.session.get(MixMasterRequest, mm_id)
    if not mm:
        return err('Demande introuvable.', code='NOT_FOUND', status=404)
    try:
        pdf = generate_mixmaster_earnings_statement(mm, stage)
    except Exception as e:
        current_app.logger.error(f"Admin: erreur génération relevé gains mixmaster#{mm_id} stage={stage}: {e}")
        return err('Impossible de générer le relevé.', code='PDF_ERROR', status=500)
    year = mm.created_at.year
    return _pdf_response(pdf, f"admin_releve_gains_mixmaster_{year}_{mm_id}_{stage}.pdf")
