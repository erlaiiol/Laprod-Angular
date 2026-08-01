"""
Blueprint CONTRACT BUILDER API — Générateur de contrats d'exploitation musicale

GET  /api/contract-builder/template              → template complet (groupes + clauses actives)
POST /api/contract-builder/contracts             → créer un brouillon (premium uniquement)
GET  /api/contract-builder/contracts             → liste des contrats de l'utilisateur
GET  /api/contract-builder/contracts/<id>        → détail d'un contrat
PUT  /api/contract-builder/contracts/<id>        → mettre à jour un brouillon
POST /api/contract-builder/contracts/<id>/generate → générer le PDF
GET  /api/contract-builder/contracts/<id>/download → télécharger le PDF

Signature en ligne (envoi à un autre utilisateur LaProd) :
POST /api/contract-builder/contracts/<id>/parties/<party_id>/invite         → inviter une partie à signer
POST /api/contract-builder/contracts/<id>/parties/<party_id>/cancel-invite  → annuler une invitation en attente
POST /api/contract-builder/contracts/<id>/sign                             → signer (destinataire)
POST /api/contract-builder/contracts/<id>/decline                          → décliner (destinataire)
GET  /api/contract-builder/inbox                                           → contrats envoyés / reçus
GET  /api/contract-builder/invite/preview                                  → aperçu d'une invitation email (public)
POST /api/contract-builder/invite/resolve                                  → rattacher son compte à une invitation email
"""
import os
import re
import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, send_file, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy import or_, select

from extensions import db, csrf
from models import (
    User,
    ContractClauseGroup,
    UserContract,
    UserContractParty,
    UserContractValue,
    UserContractStatus,
    PartyTypeEnum,
    PartyInviteStatus,
    ContractSignatureStatus,
    ContractTemplateTypeEnum,
)
from utils.notification_service import (
    notify_contract_signature_requested,
    notify_contract_signed,
    notify_contract_fully_executed,
    notify_contract_declined,
    notify_contract_invite_cancelled,
)
from serializers import contract_share
import config

contract_builder_api_bp = Blueprint(
    'contract_builder_api', __name__, url_prefix='/api/contract-builder'
)

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _ok(data=None, message='', status=200):
    body = {'success': True, 'feedback': {'level': 'success', 'message': message}}
    if data is not None:
        body['data'] = data
    return jsonify(body), status


def _err(message, status=400, code=None):
    # `code` permet au front de distinguer « quota mensuel atteint » (on propose
    # de reprendre un contrat existant) de « palier insuffisant » (on propose
    # l'upgrade) — deux messages très différents pour l'utilisateur.
    body = {'success': False, 'feedback': {'level': 'error', 'message': message}}
    if code:
        body['code'] = code
    return jsonify(body), status


def _get_user():
    return db.get_or_404(User, int(get_jwt_identity()))


def _parse_contract_type(raw, default=ContractTemplateTypeEnum.exploitation):
    """Convertit un paramètre 'type' en ContractTemplateTypeEnum (fallback: exploitation)."""
    try:
        return ContractTemplateTypeEnum(raw) if raw else default
    except ValueError:
        return default


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
        'linked_user_id':  p.linked_user_id,
        # Signature en ligne — jamais signature_ip (preuve technique interne uniquement).
        'invite_status':   p.invite_status.value,
        'invited_at':      p.invited_at.isoformat() if p.invited_at else None,
        'signed_at':       p.signed_at.isoformat() if p.signed_at else None,
        'signature_name':  p.signature_name,
        'declined_at':     p.declined_at.isoformat() if p.declined_at else None,
    }


def _contract_summary_dto(c) -> dict:
    return {
        'id':               c.id,
        'title':            c.title,
        'contract_type':    c.contract_type.value,
        'status':           c.status.value,
        'signature_status': c.signature_status.value,
        'created_at':       c.created_at.isoformat(),
        'updated_at':       c.updated_at.isoformat() if c.updated_at else None,
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


def _find_invited_party(contract, user_id: int):
    """Renvoie la UserContractParty de `contract` liée à `user_id` avec une
    invitation active (pending/signed/declined), ou None. Le filtre sur
    `invite_status` est important : une invitation annulée doit couper l'accès
    même si `linked_user_id` traîne encore sur la ligne (préremplissage)."""
    for p in contract.parties:
        if p.linked_user_id == user_id and p.invite_status != PartyInviteStatus.none:
            return p
    return None


def _check_ownership_or_invited_party(contract, user_id: int):
    """Lecture autorisée au propriétaire ET à tout signataire invité (même
    après refus, pour qu'il retrouve trace de ce qu'il a décliné)."""
    if contract.user_id == user_id:
        return None
    if _find_invited_party(contract, user_id) is not None:
        return None
    return _err('Accès non autorisé.', status=403)


def _recompute_signature_status(contract):
    """Recalcule l'agrégat de signature du contrat à partir de ses parties
    invitées. Appelé avant chaque commit des routes invite/cancel/sign/decline.
    Ne concerne que les parties invitées numériquement — les autres continuent
    de signer hors app (papier), ce qui n'empêche jamais 'signed' d'être atteint."""
    invited = [p for p in contract.parties if p.invite_status != PartyInviteStatus.none]
    if not invited:
        contract.signature_status = ContractSignatureStatus.not_sent
    elif any(p.invite_status == PartyInviteStatus.declined for p in invited):
        contract.signature_status = ContractSignatureStatus.declined
    elif all(p.invite_status == PartyInviteStatus.signed for p in invited):
        contract.signature_status = ContractSignatureStatus.signed
    else:
        contract.signature_status = ContractSignatureStatus.pending


# ── GET /api/contract-builder/template ─────────────────────────────────────────
# Public : structure de clauses (aucune donnée utilisateur), consultable sans compte
# pour permettre l'aperçu du générateur (page démo côté front).

@contract_builder_api_bp.route('/template', methods=['GET'])
@csrf.exempt
def get_template():
    ctype = _parse_contract_type(request.args.get('type'))
    groups = (
        db.session.query(ContractClauseGroup)
        .filter_by(is_active=True, contract_type=ctype)
        .order_by(ContractClauseGroup.sort_order)
        .all()
    )
    return _ok(data={'groups': [_group_dto(g) for g in groups]})


# ── POST /api/contract-builder/contracts ───────────────────────────────────────

def _check_builder_access(user, contract_type=None):
    """Accès au contract builder. Renvoie une réponse d'erreur, ou None.

    Le contrat de management suit son propre seuil (Premium+, can_use_management_
    contract) — plus bas que le reste du contract builder (Semi-Pro+, contract_quota)
    car il formalise un lien roster déjà libre, pas un usage professionnel intensif.
    """
    if contract_type == ContractTemplateTypeEnum.management:
        if not user.can_use_management_contract:
            return _err(
                "Le contrat de management est accessible à partir du plan Premium LaProd+.",
                status=403,
            )
        return None
    if not user.can_use_contract_builder:
        return _err(
            'Le Contract Builder est accessible à partir du plan Semi-Pro LaProd+.',
            status=403,
        )
    return None


def _check_contract_quota(user):
    """Quota mensuel de contrats. Renvoie une réponse d'erreur, ou None.

    Le quota compte les contrats CRÉÉS ce mois-ci, pas les générations de PDF :
    un Semi-Pro (1 contrat/mois) qui corrige une faute et régénère son unique
    contrat ne doit pas se retrouver bloqué jusqu'au mois suivant. On facture
    l'acte de rédiger un nouveau contrat, pas le droit de le relire.
    """
    quota = user.contract_quota
    if quota is None:      # Pro Structuré : illimité
        return None

    start_of_month = datetime.now().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0,
    )
    used = db.session.query(UserContract).filter(
        UserContract.user_id == user.id,
        UserContract.created_at >= start_of_month,
    ).count()

    if used >= quota:
        return _err(
            f'Votre plan vous permet de créer {quota} contrat par mois '
            f'(vous en avez créé {used}). Passez au plan Pro Structuré pour un '
            f'accès illimité — ou reprenez un contrat existant, le modifier et le '
            f'régénérer est toujours gratuit.',
            code='CONTRACT_QUOTA_REACHED', status=403,
        )
    return None


@contract_builder_api_bp.route('/contracts', methods=['POST'])
@jwt_required()
@csrf.exempt
def create_contract():
    user  = _get_user()
    data  = request.get_json(silent=True) or {}
    ctype = _parse_contract_type(data.get('contract_type'))

    if err := _check_builder_access(user, ctype):
        return err
    # Le contrat de management n'a pas de quota mensuel : ce n'est pas un usage
    # professionnel volumique comme le contract builder générique, c'est la
    # formalisation ponctuelle d'un lien roster déjà noué.
    if ctype != ContractTemplateTypeEnum.management:
        if err := _check_contract_quota(user):
            return err

    title = (data.get('title') or '').strip()
    if not title:
        return _err("Le titre de l'œuvre ou de l'évènement est requis.")

    contract = UserContract(user_id=user.id, title=title, contract_type=ctype)
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
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership_or_invited_party(contract, user.id):
        return err
    dto = _contract_detail_dto(contract)
    is_owner = contract.user_id == user.id
    dto['viewer_role'] = 'owner' if is_owner else 'recipient'
    dto['can_edit'] = is_owner and (
        user.can_use_management_contract if contract.contract_type == ContractTemplateTypeEnum.management
        else user.can_use_contract_builder
    )
    if not is_owner:
        my_party = _find_invited_party(contract, user.id)
        dto['my_party_id'] = my_party.id if my_party else None
    else:
        dto['my_party_id'] = None
    return _ok(data={'contract': dto})


# ── PUT /api/contract-builder/contracts/<id> ───────────────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
def update_contract(contract_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user.id):
        return err
    # Pas de contrôle de quota ici : modifier un contrat déjà créé ne consomme
    # rien. Le quota porte sur la création, pas sur le droit de se corriger.
    if err := _check_builder_access(user, contract.contract_type):
        return err
    # L'envoi pour signature (invite) n'est lui-même permis que sur un contrat
    # `final` (voir invite_party) : un contrat avec des invitations en cours est
    # donc déjà non modifiable par ce seul garde-fou. Ne pas l'assouplir pour
    # les contrats "final mais pas encore signés" sans repenser cette invariant.
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
                linked_user_id = pd.get('linked_user_id'),
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


# ── DELETE /api/contract-builder/contracts/<id> ─────────────────────────────────
# Brouillons uniquement : un contrat finalisé (PDF généré) est un document déjà
# potentiellement transmis/signé, on ne le fait pas disparaître silencieusement —
# cohérent avec update_contract, qui refuse déjà toute modification sur un final.

@contract_builder_api_bp.route('/contracts/<int:contract_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
def delete_contract(contract_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user.id):
        return err
    if contract.status == UserContractStatus.final:
        return _err('Ce contrat est finalisé et ne peut pas être supprimé.', status=409)

    if contract.pdf_file:
        old_path = str(config.CONTRACTS_FOLDER / 'builder' / contract.pdf_file)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    db.session.delete(contract)  # cascade='all, delete-orphan' sur parties/values
    db.session.commit()
    return _ok(message='Brouillon supprimé.')


# ── POST /api/contract-builder/contracts/<id>/generate ─────────────────────────

def _build_contract_pdf_data(contract) -> dict:
    """Construit le dict attendu par generate_custom_contract_pdf(). Partagé
    entre la génération initiale (generate_contract) et la régénération à
    chaque signature (sign_contract) pour que les deux ne divergent jamais."""
    value_map = {v.clause_id: v for v in contract.values}
    groups = (
        db.session.query(ContractClauseGroup)
        .filter_by(is_active=True, contract_type=contract.contract_type)
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

    type_labels = {
        ContractTemplateTypeEnum.exploitation: "Contrat d'exploitation d'œuvre musicale",
        ContractTemplateTypeEnum.performance:  "Contrat de représentation musicale",
        ContractTemplateTypeEnum.management:   "Mandat de management artistique",
    }

    parties_data = []
    for p in contract.parties:
        pd = _party_dto(p)
        # Date lisible dans le PDF plutôt que l'ISO renvoyé au frontend.
        pd['signed_at'] = p.signed_at.strftime('%d/%m/%Y') if p.signed_at else None
        parties_data.append(pd)

    return {
        'title':        contract.title,
        'type_label':   type_labels.get(contract.contract_type, ''),
        'generated_at': datetime.now().strftime('%d/%m/%Y'),
        'parties':      parties_data,
        'sections':     sections,
    }


def _regenerate_pdf_file(contract) -> bool:
    """(Re)génère le PDF sur disque et met à jour contract.pdf_file (pas de
    commit ici, laissé à l'appelant). Renvoie False si la génération échoue —
    le contrat garde alors son ancien PDF, aucune donnée n'est perdue."""
    contract_data = _build_contract_pdf_data(contract)

    builder_dir = config.CONTRACTS_FOLDER / 'builder'
    builder_dir.mkdir(parents=True, exist_ok=True)
    filename    = f'contract_{contract.id}_{uuid.uuid4().hex[:8]}.pdf'
    output_path = str(builder_dir / filename)

    try:
        from utils.contract_builder_pdf import generate_custom_contract_pdf
        generate_custom_contract_pdf(output_path, contract_data)
    except Exception as e:
        current_app.logger.error(f'contract_builder: PDF generation failed: {e}')
        return False

    old_file = contract.pdf_file
    contract.pdf_file   = filename
    contract.updated_at = datetime.now()

    if old_file:
        old_path = str(builder_dir / old_file)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    return True


@contract_builder_api_bp.route('/contracts/<int:contract_id>/generate', methods=['POST'])
@jwt_required()
@csrf.exempt
def generate_contract(contract_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user.id):
        return err
    # Régénérer le PDF d'un contrat existant ne consomme pas de quota (cf.
    # _check_contract_quota) : on facture l'acte de rédiger, pas celui de relire.
    if err := _check_builder_access(user, contract.contract_type):
        return err
    if len(contract.parties) < 2:
        return _err('Le contrat doit comporter au moins deux parties.')

    if not _regenerate_pdf_file(contract):
        return _err('La génération du PDF a échoué. Veuillez réessayer.')

    contract.status = UserContractStatus.final
    db.session.commit()

    return _ok(data={'pdf_url': f'/api/contract-builder/contracts/{contract.id}/download'})


# ── GET /api/contract-builder/contracts/<id>/download ──────────────────────────
# Pas de re-check is_pro ici (contrairement à update/generate) : télécharger un PDF
# déjà généré n'est pas une action d'édition, et l'utilisateur y avait droit au
# moment de la génération. Un downgrade ultérieur ne doit pas lui bloquer l'accès
# à un livrable déjà produit.

@contract_builder_api_bp.route('/contracts/<int:contract_id>/download', methods=['GET'])
@jwt_required()
@csrf.exempt
def download_contract(contract_id):
    user_id  = int(get_jwt_identity())
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership_or_invited_party(contract, user_id):
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


# =============================================================================
# SIGNATURE EN LIGNE — envoi à un autre utilisateur LaProd
# =============================================================================

def _get_party_or_404(contract, party_id):
    return next((p for p in contract.parties if p.id == party_id), None)


# ── POST /contracts/<id>/parties/<party_id>/invite ─────────────────────────────

@contract_builder_api_bp.route(
    '/contracts/<int:contract_id>/parties/<int:party_id>/invite', methods=['POST']
)
@jwt_required()
@csrf.exempt
def invite_party(contract_id, party_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user.id):
        return err
    if contract.status != UserContractStatus.final:
        return _err('Le contrat doit être finalisé avant l\'envoi pour signature.', status=409)

    party = _get_party_or_404(contract, party_id)
    if not party:
        return _err('Partie introuvable.', status=404)
    if party.invite_status in (PartyInviteStatus.pending, PartyInviteStatus.signed):
        return _err(
            'Une invitation est déjà en attente ou a déjà été signée pour cette partie.',
            status=409,
        )

    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    if not identifier:
        return _err("Indiquez le pseudo ou l'email de la personne à inviter.", status=400)

    target = db.session.scalar(
        select(User).where(or_(User.username == identifier, User.email == identifier))
    )
    if target and target.id == user.id:
        return _err('Vous ne pouvez pas vous inviter vous-même.', status=400)
    if not target and not _EMAIL_RE.match(identifier):
        return _err(
            "Aucun compte trouvé avec cet identifiant — saisissez un pseudo existant "
            "ou une adresse email valide pour inviter une personne qui n'a pas encore "
            "de compte LaProd.",
            status=400,
        )

    # Réinitialisation commune (couvre la ré-invitation après un refus).
    party.signed_at         = None
    party.signature_name    = None
    party.signature_ip      = None
    party.consent_confirmed = False
    party.declined_at       = None
    party.invited_at        = datetime.now()
    party.invited_by_id     = user.id
    party.invite_status     = PartyInviteStatus.pending

    if target:
        party.linked_user_id = target.id
        _recompute_signature_status(contract)
        db.session.commit()
        notify_contract_signature_requested(contract, party, target)
        return _ok(
            data={'party': _party_dto(party), 'signature_status': contract.signature_status.value},
            message='Invitation envoyée.',
        )

    # Pas de compte trouvé pour cet email : on invite un futur inscrit.
    party.email           = identifier
    party.linked_user_id  = None
    _recompute_signature_status(contract)
    db.session.commit()

    from utils.email_service import send_contract_invite_email
    send_contract_invite_email(party, contract, user)

    return _ok(
        data={'party': _party_dto(party), 'signature_status': contract.signature_status.value},
        message="Invitation envoyée par email — cette personne n'a pas encore de compte LaProd.",
    )


# ── POST /contracts/<id>/parties/<party_id>/cancel-invite ──────────────────────

@contract_builder_api_bp.route(
    '/contracts/<int:contract_id>/parties/<int:party_id>/cancel-invite', methods=['POST']
)
@jwt_required()
@csrf.exempt
def cancel_party_invite(contract_id, party_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    if err := _check_ownership(contract, user.id):
        return err

    party = _get_party_or_404(contract, party_id)
    if not party:
        return _err('Partie introuvable.', status=404)
    if party.invite_status != PartyInviteStatus.pending:
        return _err("Cette invitation n'est plus en attente.", status=409)

    # Conserver linked_user_id pour préremplir une ré-invitation future, mais
    # invite_status=none coupe immédiatement l'accès en lecture du destinataire
    # (voir _find_invited_party) même si un compte était déjà résolu.
    target_user = party.linked_user
    party.invite_status = PartyInviteStatus.none
    party.invited_at    = None
    party.invited_by_id = None
    _recompute_signature_status(contract)
    db.session.commit()

    if target_user:
        notify_contract_invite_cancelled(contract, party, target_user)

    return _ok(
        data={'party': _party_dto(party), 'signature_status': contract.signature_status.value},
        message='Invitation annulée.',
    )


# ── GET /inbox ──────────────────────────────────────────────────────────────────

@contract_builder_api_bp.route('/inbox', methods=['GET'])
@jwt_required()
@csrf.exempt
def get_inbox():
    user_id = int(get_jwt_identity())

    sent = (
        db.session.query(UserContract)
        .filter(
            UserContract.user_id == user_id,
            UserContract.signature_status != ContractSignatureStatus.not_sent,
        )
        .order_by(UserContract.updated_at.desc())
        .all()
    )

    received_parties = (
        db.session.query(UserContractParty)
        .join(UserContract, UserContractParty.contract_id == UserContract.id)
        .filter(
            UserContractParty.linked_user_id == user_id,
            UserContractParty.invite_status != PartyInviteStatus.none,
        )
        .order_by(UserContract.updated_at.desc())
        .all()
    )

    return _ok(data={
        'sent':     [contract_share(c) for c in sent],
        'received': [contract_share(p.contract, p) for p in received_parties],
    })


# ── POST /contracts/<id>/sign ────────────────────────────────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>/sign', methods=['POST'])
@jwt_required()
@csrf.exempt
def sign_contract(contract_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    party    = _find_invited_party(contract, user.id)
    if not party or party.invite_status != PartyInviteStatus.pending:
        return _err("Vous n'avez pas d'invitation à signer en attente pour ce contrat.", status=404)

    data           = request.get_json(silent=True) or {}
    signature_name = (data.get('signature_name') or '').strip()
    consent        = data.get('consent') is True

    if not signature_name:
        return _err('Indiquez votre nom légal complet pour signer.', status=400)
    if len(signature_name) > 200:
        return _err('Nom trop long.', status=400)
    if not consent:
        return _err('Vous devez cocher la case de consentement pour signer.', status=400)

    party.invite_status     = PartyInviteStatus.signed
    party.signed_at         = datetime.now()
    party.signature_name    = signature_name
    party.signature_ip      = request.remote_addr
    party.consent_confirmed = True
    _recompute_signature_status(contract)

    # Régénère le PDF pour y graver la signature — si ça échoue, on annule
    # tout (y compris la signature) plutôt que de laisser un état incohérent.
    if not _regenerate_pdf_file(contract):
        db.session.rollback()
        return _err(
            'La signature n\'a pas pu être enregistrée (échec de génération du PDF). Réessayez.',
            status=500,
        )

    db.session.commit()

    notify_contract_signed(contract, party, user)
    if contract.signature_status == ContractSignatureStatus.signed:
        notify_contract_fully_executed(contract)

    return _ok(data={'contract': _contract_detail_dto(contract)}, message='Contrat signé.')


# ── POST /contracts/<id>/decline ─────────────────────────────────────────────────

@contract_builder_api_bp.route('/contracts/<int:contract_id>/decline', methods=['POST'])
@jwt_required()
@csrf.exempt
def decline_contract(contract_id):
    user     = _get_user()
    contract = db.get_or_404(UserContract, contract_id)
    party    = _find_invited_party(contract, user.id)
    if not party or party.invite_status != PartyInviteStatus.pending:
        return _err("Vous n'avez pas d'invitation à signer en attente pour ce contrat.", status=404)

    party.invite_status = PartyInviteStatus.declined
    party.declined_at   = datetime.now()
    _recompute_signature_status(contract)
    db.session.commit()

    notify_contract_declined(contract, party, user)

    return _ok(data={'contract': _contract_detail_dto(contract)}, message='Signature déclinée.')


# ── GET /invite/preview ──────────────────────────────────────────────────────────
# Public (pas de compte requis) : permet d'afficher "X vous invite à signer Y"
# avant même de se connecter/s'inscrire. Ne modifie rien.

@contract_builder_api_bp.route('/invite/preview', methods=['GET'])
@csrf.exempt
def invite_preview():
    from utils.email_service import verify_contract_invite_token

    token   = request.args.get('token', '')
    payload = verify_contract_invite_token(token)
    if not payload:
        return _err("Ce lien d'invitation est invalide ou a expiré.", status=410)

    contract = db.session.get(UserContract, payload.get('contract_id'))
    party    = db.session.get(UserContractParty, payload.get('party_id'))
    if not contract or not party or party.contract_id != contract.id:
        return _err('Invitation introuvable.', status=404)
    if party.invite_status != PartyInviteStatus.pending:
        return _err("Cette invitation n'est plus valide — contactez l'expéditeur.", status=409)

    return _ok(data={
        'title':            contract.title,
        'inviter_username': contract.user.username,
        'email':            payload.get('email'),
    })


# ── POST /invite/resolve ─────────────────────────────────────────────────────────
# Rattache le compte connecté (qui vient de se créer/se connecter via le lien
# email) à la partie invitée — condition : son email de compte correspond bien
# à celui invité, sinon on refuse plutôt que de rattacher silencieusement le
# mauvais compte.

@contract_builder_api_bp.route('/invite/resolve', methods=['POST'])
@jwt_required()
@csrf.exempt
def invite_resolve():
    from utils.email_service import verify_contract_invite_token

    user  = _get_user()
    data  = request.get_json(silent=True) or {}
    token = data.get('token', '')

    payload = verify_contract_invite_token(token)
    if not payload:
        return _err("Ce lien d'invitation est invalide ou a expiré.", status=410)

    contract = db.session.get(UserContract, payload.get('contract_id'))
    party    = db.session.get(UserContractParty, payload.get('party_id'))
    if not contract or not party or party.contract_id != contract.id:
        return _err('Invitation introuvable.', status=404)
    if party.invite_status != PartyInviteStatus.pending:
        return _err("Cette invitation n'est plus valide — contactez l'expéditeur.", status=409)

    invited_email = (payload.get('email') or '').strip().lower()
    if (user.email or '').strip().lower() != invited_email:
        return _err(
            'Vous êtes connecté avec un autre compte que celui invité — '
            'déconnectez-vous et réessayez avec le bon compte.',
            status=409,
        )

    party.linked_user_id = user.id
    db.session.commit()

    return _ok(data={'contract_id': contract.id})
