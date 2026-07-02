"""
Blueprint CONTRACT BUILDER API — Générateur de contrats d'exploitation musicale

GET  /api/contract-builder/template              → template complet (groupes + clauses actives)
POST /api/contract-builder/contracts             → créer un brouillon (premium uniquement)
GET  /api/contract-builder/contracts             → liste des contrats de l'utilisateur
GET  /api/contract-builder/contracts/<id>        → détail d'un contrat
PUT  /api/contract-builder/contracts/<id>        → mettre à jour un brouillon
POST /api/contract-builder/contracts/<id>/generate → générer le PDF
GET  /api/contract-builder/contracts/<id>/download → télécharger le PDF
"""
import os
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from extensions import db, csrf
from models import (
    User,
    ContractClauseGroup,
    UserContract,
    UserContractParty,
    UserContractValue,
    UserContractStatus,
    PartyTypeEnum,
)
import config

contract_builder_api_bp = Blueprint(
    'contract_builder_api', __name__, url_prefix='/api/contract-builder'
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _ok(data=None, message='', status=200):
    body = {'success': True, 'feedback': {'level': 'success', 'message': message}}
    if data is not None:
        body['data'] = data
    return jsonify(body), status


def _err(message, status=400):
    return jsonify({'success': False, 'feedback': {'level': 'error', 'message': message}}), status


def _get_user():
    return db.get_or_404(User, int(get_jwt_identity()))


def _clause_dto(c) -> dict:
    return {
        'id':                    c.id,
        'group_id':              c.group_id,
        'name':                  c.name,
        'description':           c.description,
        'tooltip_short':         c.tooltip_short,
        'tooltip_long':          c.tooltip_long,
        'clause_type':           c.clause_type.value,
        'options':               c.options,
        'default_value':         c.default_value,
        'is_required':           c.is_required,
        'is_enabled_by_default': c.is_enabled_by_default,
        'sort_order':            c.sort_order,
        'legal_reference':       c.legal_reference,
        'example_text':          c.example_text,
        'tooltip_plain':         c.tooltip_plain,
    }


def _group_dto(g) -> dict:
    return {
        'id':          g.id,
        'name':        g.name,
        'description': g.description,
        'tooltip':     g.tooltip,
        'sort_order':  g.sort_order,
        'is_active':   g.is_active,
        'clauses':     [_clause_dto(c) for c in g.clauses if c.is_active],
    }


def _party_dto(p) -> dict:
    return {
        'id':              p.id,
        'party_type':      p.party_type.value,
        'sort_order':      p.sort_order,
        'role':            p.role,
        'first_name':      p.first_name,
        'last_name':       p.last_name,
        'date_of_birth':   p.date_of_birth,
        'nationality':     p.nationality,
        'pseudonym':       p.pseudonym,
        'tax_id':          p.tax_id,
        'company_name':    p.company_name,
        'legal_form':      p.legal_form,
        'capital':         p.capital,
        'siren':           p.siren,
        'siret':           p.siret,
        'rcs':             p.rcs,
        'legal_rep':       p.legal_rep,
        'signatory_title': p.signatory_title,
        'address':         p.address,
        'email':           p.email,
    }


def _contract_summary_dto(c) -> dict:
    return {
        'id':         c.id,
        'title':      c.title,
        'status':     c.status.value,
        'created_at': c.created_at.isoformat(),
        'updated_at': c.updated_at.isoformat() if c.updated_at else None,
    }


def _contract_detail_dto(c) -> dict:
    d = _contract_summary_dto(c)
    d['pdf_file'] = c.pdf_file
    d['parties']  = [_party_dto(p) for p in c.parties]
    d['values']   = [
        {'clause_id': v.clause_id, 'is_enabled': v.is_enabled, 'value': v.value}
        for v in c.values
    ]
    return d


def _check_ownership(contract, user_id: int):
    if contract.user_id != user_id:
        return _err('Accès non autorisé.', status=403)
    return None


# ── GET /api/contract-builder/template ─────────────────────────────────────────

@contract_builder_api_bp.route('/template', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_template():
    groups = (
        db.session.query(ContractClauseGroup)
        .filter_by(is_active=True)
        .order_by(ContractClauseGroup.sort_order)
        .all()
    )
    return _ok(data={'groups': [_group_dto(g) for g in groups]})


# ── POST /api/contract-builder/contracts ───────────────────────────────────────

@contract_builder_api_bp.route('/contracts', methods=['POST'])
@jwt_required()
@csrf.exempt
def create_contract():
    user = _get_user()
    if not user.is_pro:
        return _err('Le Contract Builder est réservé au plan Pro LaProd+.', status=403)

    data  = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return _err("Le titre de l'œuvre est requis.")

    contract = UserContract(user_id=user.id, title=title)
    db.session.add(contract)
    db.session.commit()
    return _ok(data={'contract': _contract_summary_dto(contract)}, status=201)


# ── GET /api/contract-builder/contracts ────────────────────────────────────────

@contract_builder_api_bp.route('/contracts', methods=['GET'])
@jwt_required()
@csrf.exempt
def list_contracts():
    user_id = int(get_jwt_identity())
    contracts = (
        db.session.query(UserContract)
        .filter_by(user_id=user_id)
        .order_by(UserContract.created_at.desc())
        .all()
    )
    return _ok(data={'contracts': [_contract_summary_dto(c) for c in contracts]})


# ── GET /api/contract-builder/contracts/<id> ───────────────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_contract(contract_id):
    user_id  = int(get_jwt_identity())
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user_id):
        return err
    return _ok(data={'contract': _contract_detail_dto(contract)})


# ── PUT /api/contract-builder/contracts/<id> ───────────────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
def update_contract(contract_id):
    user_id  = int(get_jwt_identity())
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user_id):
        return err
    if contract.status == UserContractStatus.final:
        return _err('Ce contrat est finalisé et ne peut plus être modifié.', status=409)

    data = request.get_json(silent=True) or {}

    if 'title' in data:
        title = (data['title'] or '').strip()
        if title:
            contract.title = title

    # Parties — remplacement complet
    if 'parties' in data:
        for p in list(contract.parties):
            db.session.delete(p)
        db.session.flush()

        for i, pd in enumerate(data['parties']):
            try:
                ptype = PartyTypeEnum(pd.get('party_type', 'physical'))
            except ValueError:
                ptype = PartyTypeEnum.physical

            db.session.add(UserContractParty(
                contract_id    = contract.id,
                party_type     = ptype,
                sort_order     = pd.get('sort_order', i),
                role           = (pd.get('role') or '').strip(),
                first_name     = pd.get('first_name'),
                last_name      = pd.get('last_name'),
                date_of_birth  = pd.get('date_of_birth'),
                nationality    = pd.get('nationality'),
                pseudonym      = pd.get('pseudonym'),
                tax_id         = pd.get('tax_id'),
                company_name   = pd.get('company_name'),
                legal_form     = pd.get('legal_form'),
                capital        = pd.get('capital'),
                siren          = pd.get('siren'),
                siret          = pd.get('siret'),
                rcs            = pd.get('rcs'),
                legal_rep      = pd.get('legal_rep'),
                signatory_title= pd.get('signatory_title'),
                address        = pd.get('address'),
                email          = pd.get('email'),
            ))

    # Values — upsert
    if 'values' in data:
        existing = {v.clause_id: v for v in contract.values}
        for vd in data['values']:
            clause_id = vd.get('clause_id')
            if clause_id is None:
                continue
            if clause_id in existing:
                existing[clause_id].is_enabled = vd.get('is_enabled', True)
                existing[clause_id].value      = vd.get('value')
            else:
                db.session.add(UserContractValue(
                    contract_id = contract.id,
                    clause_id   = clause_id,
                    is_enabled  = vd.get('is_enabled', True),
                    value       = vd.get('value'),
                ))

    contract.updated_at = datetime.now()
    db.session.commit()
    return _ok(data={'contract': _contract_detail_dto(contract)})


# ── POST /api/contract-builder/contracts/<id>/generate ─────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>/generate', methods=['POST'])
@jwt_required()
@csrf.exempt
def generate_contract(contract_id):
    user_id  = int(get_jwt_identity())
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user_id):
        return err
    if len(contract.parties) < 2:
        return _err('Le contrat doit comporter au moins deux parties.')

    value_map = {v.clause_id: v for v in contract.values}
    groups = (
        db.session.query(ContractClauseGroup)
        .filter_by(is_active=True)
        .order_by(ContractClauseGroup.sort_order)
        .all()
    )

    sections = []
    for group in groups:
        clauses_data = []
        for clause in group.clauses:
            if not clause.is_active:
                continue
            ucv        = value_map.get(clause.id)
            is_enabled = ucv.is_enabled if ucv else clause.is_enabled_by_default
            value      = ucv.value      if ucv else clause.default_value
            clauses_data.append({
                'name':           clause.name,
                'clause_type':    clause.clause_type.value,
                'value':          value,
                'is_enabled':     is_enabled,
                'is_required':    clause.is_required,
                'legal_reference': clause.legal_reference,
            })
        if clauses_data:
            sections.append({'group_name': group.name, 'clauses': clauses_data})

    contract_data = {
        'title':        contract.title,
        'generated_at': datetime.now().strftime('%d/%m/%Y'),
        'parties':      [_party_dto(p) for p in contract.parties],
        'sections':     sections,
    }

    builder_dir = config.CONTRACTS_FOLDER / 'builder'
    builder_dir.mkdir(parents=True, exist_ok=True)
    filename    = f'contract_{contract.id}_{uuid.uuid4().hex[:8]}.pdf'
    output_path = str(builder_dir / filename)

    try:
        from utils.contract_builder_pdf import generate_custom_contract_pdf
        generate_custom_contract_pdf(output_path, contract_data)
    except Exception as e:
        current_app.logger.error(f'contract_builder: PDF generation failed: {e}')
        return _err('La génération du PDF a échoué. Veuillez réessayer.')

    # Supprimer l'ancien PDF si existant
    if contract.pdf_file:
        old_path = str(builder_dir / contract.pdf_file)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    contract.pdf_file   = filename
    contract.status     = UserContractStatus.final
    contract.updated_at = datetime.now()
    db.session.commit()

    return _ok(data={'pdf_url': f'/api/contract-builder/contracts/{contract.id}/download'})


# ── GET /api/contract-builder/contracts/<id>/download ──────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>/download', methods=['GET'])
@jwt_required()
@csrf.exempt
def download_contract(contract_id):
    user_id  = int(get_jwt_identity())
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user_id):
        return err
    if not contract.pdf_file:
        return _err("Le PDF de ce contrat n'a pas encore été généré.", status=404)

    file_path = str(config.CONTRACTS_FOLDER / 'builder' / contract.pdf_file)
    if not os.path.exists(file_path):
        return _err('Fichier PDF introuvable.', status=404)

    safe_title = ''.join(c for c in contract.title if c.isalnum() or c in ' _-')[:40]
    return send_file(
        file_path,
        as_attachment=True,
        download_name=f'contrat_{safe_title}.pdf',
        mimetype='application/pdf',
    )
