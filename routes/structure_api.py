"""
Blueprint STRUCTURE API — Identité légale B2B (SMAC, labels, structures de management)

Réservé au palier Pro Structuré (current_user.is_pro). v1 mono-owner : une
Structure par utilisateur, pas de sièges multiples (voir backlog).

GET    /api/structures/mine            → structure de l'utilisateur courant (ou null)
POST   /api/structures                 → création (Pro Structuré, une seule par owner)
PUT    /api/structures/<id>            → modification (owner uniquement)
DELETE /api/structures/<id>            → suppression (owner uniquement)
GET    /api/structures/<id>/export     → export compta consolidé (CSV ou PDF)
"""
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Blueprint, request, send_file
from flask_jwt_extended import jwt_required

from extensions import csrf, db, limiter
from models import PremiumPayment, Purchase, Structure, UserContractParty
from serializers import err, ok
from serializers import structure as ser_structure
from utils.auth_helpers import require_user
from utils.structure_export import generate_structure_statement

structure_api_bp = Blueprint('structure_api', __name__, url_prefix='/api/structures')

_STRUCTURE_FIELDS = (
    'name', 'legal_form', 'capital', 'siren', 'siret', 'rcs',
    'legal_rep', 'signatory_title', 'address', 'email', 'phone',
)


def _apply_fields(structure: Structure, data: dict) -> None:
    for field in _STRUCTURE_FIELDS:
        if field in data:
            value = data.get(field)
            setattr(structure, field, value.strip() if isinstance(value, str) else value)


# ── GET /mine ──────────────────────────────────────────────────────────────────

@structure_api_bp.route('/mine', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_mine(current_user):
    structure = current_user.structure
    return ok(data={'structure': ser_structure(structure) if structure else None})


# ── POST / ─────────────────────────────────────────────────────────────────────

@structure_api_bp.route('', methods=['POST'])
@limiter.limit('10 per minute')
@jwt_required()
@csrf.exempt
@require_user
def create_structure(current_user):
    if not current_user.is_pro:
        return err('Réservé au palier Pro Structuré.', code='FORBIDDEN', status=403)
    if current_user.structure:
        return err('Vous avez déjà une structure.', code='ALREADY_EXISTS', status=409)

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return err('Le nom de la structure est requis.', code='NAME_REQUIRED', status=400)

    structure = Structure(owner_id=current_user.id, name=name)
    _apply_fields(structure, data)
    db.session.add(structure)
    db.session.commit()

    return ok(data={'structure': ser_structure(structure)}, message='Structure créée.', status=201)


# ── PUT /<id> ──────────────────────────────────────────────────────────────────

@structure_api_bp.route('/<int:structure_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_user
def update_structure(current_user, structure_id):
    structure = db.session.get(Structure, structure_id)
    if not structure:
        return err('Structure introuvable.', code='NOT_FOUND', status=404)
    if structure.owner_id != current_user.id:
        return err('Vous n\'êtes pas le propriétaire de cette structure.', code='FORBIDDEN', status=403)

    data = request.get_json(silent=True) or {}
    if 'name' in data:
        name = (data.get('name') or '').strip()
        if not name:
            return err('Le nom de la structure est requis.', code='NAME_REQUIRED', status=400)
        structure.name = name
    _apply_fields(structure, data)

    db.session.commit()
    return ok(data={'structure': ser_structure(structure)}, message='Structure mise à jour.')


# ── DELETE /<id> ───────────────────────────────────────────────────────────────

@structure_api_bp.route('/<int:structure_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_user
def delete_structure(current_user, structure_id):
    structure = db.session.get(Structure, structure_id)
    if not structure:
        return err('Structure introuvable.', code='NOT_FOUND', status=404)
    if structure.owner_id != current_user.id:
        return err('Vous n\'êtes pas le propriétaire de cette structure.', code='FORBIDDEN', status=403)

    # Pas de cascade sur les parties de contrat déjà générées (snapshot légal) :
    # on détache la référence de pré-remplissage sans toucher au contrat lui-même.
    db.session.query(UserContractParty).filter_by(linked_structure_id=structure.id).update(
        {'linked_structure_id': None}
    )
    db.session.delete(structure)
    db.session.commit()
    return ok(message='Structure supprimée.')


# ── GET /<id>/export ───────────────────────────────────────────────────────────

@structure_api_bp.route('/<int:structure_id>/export', methods=['GET'])
@limiter.limit('10 per minute')
@jwt_required()
@csrf.exempt
@require_user
def export_structure(current_user, structure_id):
    structure = db.session.get(Structure, structure_id)
    if not structure:
        return err('Structure introuvable.', code='NOT_FOUND', status=404)
    if structure.owner_id != current_user.id:
        return err('Vous n\'êtes pas le propriétaire de cette structure.', code='FORBIDDEN', status=403)

    fmt = (request.args.get('format') or 'csv').strip().lower()
    if fmt not in ('csv', 'pdf'):
        return err('Format invalide. Valeurs acceptées : csv, pdf.', code='INVALID_FORMAT', status=400)

    def _parse_date(raw, fallback):
        if not raw:
            return fallback
        try:
            return datetime.strptime(raw, '%Y-%m-%d')
        except ValueError:
            return fallback

    period_to = _parse_date(request.args.get('to'), datetime.now())
    period_from = _parse_date(request.args.get('from'), period_to - timedelta(days=365))
    # Borne haute incluse jusqu'à la fin de la journée demandée.
    period_to_inclusive = period_to + timedelta(days=1)

    payments = db.session.query(PremiumPayment).filter(
        PremiumPayment.user_id == structure.owner_id,
        PremiumPayment.created_at >= period_from,
        PremiumPayment.created_at < period_to_inclusive,
    ).order_by(PremiumPayment.created_at.asc()).all()

    purchases = db.session.query(Purchase).filter(
        Purchase.buyer_id == structure.owner_id,
        Purchase.created_at >= period_from,
        Purchase.created_at < period_to_inclusive,
    ).order_by(Purchase.created_at.asc()).all()

    rows = []
    for p in payments:
        label = 'Renouvellement' if p.is_renewal else 'Abonnement'
        rows.append((p.created_at, f'LaProd+ {p.plan} — {label}', p.amount_paid))
    for pur in purchases:
        title = pur.track.title if pur.track else f'Titre #{pur.track_id}'
        rows.append((pur.created_at, f'Achat "{title}" ({pur.format_purchased.upper()})', pur.price_paid))
    rows.sort(key=lambda r: r[0])

    if fmt == 'csv':
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['Date', 'Description', 'Montant (EUR)'])
        for date, description, amount in rows:
            writer.writerow([date.strftime('%d/%m/%Y'), description, str(amount)])
        total = sum((r[2] for r in rows), Decimal('0'))
        writer.writerow(['', 'TOTAL', str(total)])
        data_bytes = buf.getvalue().encode('utf-8-sig')  # BOM pour Excel FR
        return send_file(
            io.BytesIO(data_bytes),
            as_attachment=True,
            download_name=f'export_compta_structure_{structure.id}.csv',
            mimetype='text/csv',
        )

    pdf_bytes = generate_structure_statement(structure, rows, period_from, period_to)
    return send_file(
        io.BytesIO(pdf_bytes),
        as_attachment=True,
        download_name=f'releve_structure_{structure.id}.pdf',
        mimetype='application/pdf',
    )
