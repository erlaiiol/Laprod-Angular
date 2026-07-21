"""
Blueprint ROSTER API — Lien mutuel producteur ↔ artiste

Libre à tous les paliers : seul le rôle self-déclaré (is_producer côté
invitant, is_artist/is_beatmaker côté invité) conditionne l'accès. La
formalisation par contrat de management (attach-contract) est, elle, réservée
à can_use_management_contract (Premium+) — voir routes/roster_api.py::attach_contract.

POST /api/roster/invite            → producteur invite un artiste par username/email
GET  /api/roster/mine              → mon roster (vue producteur ET vue artiste géré)
POST /api/roster/<id>/accept       → l'artiste invité accepte
POST /api/roster/<id>/decline      → l'artiste invité décline
POST /api/roster/<id>/revoke       → n'importe quelle partie révoque/quitte
GET  /api/roster/search-artist     → recherche d'un artiste existant (producteur only)
POST /api/roster/<id>/attach-contract → attache un contrat de management au lien (Premium+)
"""
from datetime import datetime

from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from sqlalchemy import or_, select

from extensions import csrf, db
from models import ContractTemplateTypeEnum, RosterLink, RosterLinkStatus, User, UserContract
from serializers import err, ok
from serializers import roster_link as ser_roster_link
from utils.auth_helpers import require_user
from utils.notification_service import create_notification
from utils.search import LIKE_ESCAPE, escape_like

roster_api_bp = Blueprint('roster_api', __name__, url_prefix='/api/roster')

_ROSTER_URL = '/producer/roster'


# ── POST /invite ────────────────────────────────────────────────────────────────

@roster_api_bp.route('/invite', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def invite(current_user):
    if not current_user.is_producer:
        return err("Le rôle producteur est requis pour inviter un artiste.", status=403)

    data = request.get_json(silent=True) or {}
    identifier = (data.get('identifier') or '').strip()
    if not identifier:
        return err("Indique le nom d'utilisateur ou l'email de l'artiste à inviter.", status=400)

    target = db.session.scalar(
        select(User).where(or_(User.username == identifier, User.email == identifier))
    )
    if not target:
        return err("Aucun utilisateur trouvé avec cet identifiant.", status=404)
    if target.id == current_user.id:
        return err("Tu ne peux pas t'inviter toi-même.", status=400)
    if not (target.is_artist or target.is_beatmaker):
        return err("Cet utilisateur n'a pas activé le rôle artiste ou beatmaker.", status=400)

    existing = db.session.scalar(
        select(RosterLink).where(
            RosterLink.producer_id == current_user.id,
            RosterLink.artist_id == target.id,
        )
    )
    if existing and existing.status in (RosterLinkStatus.invited, RosterLinkStatus.active):
        return err("Un lien existe déjà avec cet artiste.", status=409)

    if existing:
        # Ré-invitation après declined/revoked/ended : on réutilise la même
        # ligne plutôt que d'en créer une nouvelle (unicité (producer_id, artist_id)).
        existing.status = RosterLinkStatus.invited
        existing.invited_by_id = current_user.id
        existing.responded_at = None
        existing.ended_at = None
        link = existing
    else:
        link = RosterLink(
            producer_id=current_user.id,
            artist_id=target.id,
            invited_by_id=current_user.id,
        )
        db.session.add(link)

    db.session.commit()

    create_notification(
        user_id=target.id,
        notif_type='roster_invite',
        title='Invitation roster',
        message=f'{current_user.username} te propose de rejoindre son roster.',
        link=_ROSTER_URL,
    )

    return ok(data={'link': ser_roster_link(link, current_user.id)},
              message='Invitation envoyée.', status=201)


# ── GET /mine ───────────────────────────────────────────────────────────────────

@roster_api_bp.route('/mine', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def mine(current_user):
    """Un producteur peut aussi être artiste géré par quelqu'un d'autre — les
    deux vues sont donc toujours renvoyées ensemble, jamais mutuellement
    exclusives."""
    as_producer = db.session.scalars(
        select(RosterLink)
        .where(RosterLink.producer_id == current_user.id)
        .order_by(RosterLink.created_at.desc())
    ).all()
    as_artist = db.session.scalars(
        select(RosterLink)
        .where(RosterLink.artist_id == current_user.id)
        .order_by(RosterLink.created_at.desc())
    ).all()

    return ok(data={
        'as_producer': [ser_roster_link(link, current_user.id) for link in as_producer],
        'as_artist':   [ser_roster_link(link, current_user.id) for link in as_artist],
    })


# ── POST /<id>/accept ───────────────────────────────────────────────────────────

@roster_api_bp.route('/<int:link_id>/accept', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def accept(current_user, link_id):
    link = db.session.get(RosterLink, link_id)
    if not link:
        return err("Lien roster introuvable.", status=404)
    if link.artist_id != current_user.id:
        return err("Cette invitation ne t'est pas adressée.", status=403)
    if link.status != RosterLinkStatus.invited:
        return err("Cette invitation n'est plus en attente.", status=409)

    link.status = RosterLinkStatus.active
    link.responded_at = datetime.now()
    db.session.commit()

    create_notification(
        user_id=link.producer_id,
        notif_type='roster_accepted',
        title='Invitation acceptée',
        message=f'{current_user.username} a rejoint ton roster.',
        link=_ROSTER_URL,
    )

    return ok(data={'link': ser_roster_link(link, current_user.id)}, message='Invitation acceptée.')


# ── POST /<id>/decline ──────────────────────────────────────────────────────────

@roster_api_bp.route('/<int:link_id>/decline', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def decline(current_user, link_id):
    link = db.session.get(RosterLink, link_id)
    if not link:
        return err("Lien roster introuvable.", status=404)
    if link.artist_id != current_user.id:
        return err("Cette invitation ne t'est pas adressée.", status=403)
    if link.status != RosterLinkStatus.invited:
        return err("Cette invitation n'est plus en attente.", status=409)

    link.status = RosterLinkStatus.declined
    link.responded_at = datetime.now()
    db.session.commit()

    create_notification(
        user_id=link.producer_id,
        notif_type='roster_declined',
        title='Invitation déclinée',
        message=f'{current_user.username} a décliné ton invitation.',
        link=_ROSTER_URL,
    )

    return ok(data={'link': ser_roster_link(link, current_user.id)}, message='Invitation déclinée.')


# ── POST /<id>/revoke ───────────────────────────────────────────────────────────

@roster_api_bp.route('/<int:link_id>/revoke', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def revoke(current_user, link_id):
    """Révoque une invitation en attente ou quitte un lien actif — les deux
    parties peuvent le faire à tout moment, sans confirmation d'un tiers
    (droit de sortie RGPD)."""
    link = db.session.get(RosterLink, link_id)
    if not link:
        return err("Lien roster introuvable.", status=404)
    if current_user.id not in (link.producer_id, link.artist_id):
        return err("Ce lien roster ne te concerne pas.", status=403)
    if link.status not in (RosterLinkStatus.invited, RosterLinkStatus.active):
        return err("Ce lien roster est déjà terminé.", status=409)

    was_active = link.status == RosterLinkStatus.active
    link.status = RosterLinkStatus.ended if was_active else RosterLinkStatus.revoked
    link.ended_at = datetime.now()
    db.session.commit()

    other_id = link.artist_id if current_user.id == link.producer_id else link.producer_id
    create_notification(
        user_id=other_id,
        notif_type='roster_ended' if was_active else 'roster_revoked',
        title='Lien roster terminé' if was_active else 'Invitation annulée',
        message=(f'{current_user.username} a quitté le lien roster.' if was_active
                  else f'{current_user.username} a annulé l’invitation.'),
        link=_ROSTER_URL,
    )

    return ok(data={'link': ser_roster_link(link, current_user.id)}, message='Lien roster terminé.')


# ── GET /search-artist ──────────────────────────────────────────────────────────

@roster_api_bp.route('/search-artist', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def search_artist(current_user):
    if not current_user.is_producer:
        return err("Le rôle producteur est requis.", status=403)

    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return ok({'users': []})

    esc = escape_like(q)
    candidates = db.session.scalars(
        select(User)
        .where(
            or_(User.is_artist == True, User.is_beatmaker == True),  # noqa: E712
            User.id != current_user.id,
            User.username.ilike(f'%{esc}%', escape=LIKE_ESCAPE),
        )
        .limit(10)
    ).all()

    linked_ids = {
        link.artist_id for link in db.session.scalars(
            select(RosterLink).where(
                RosterLink.producer_id == current_user.id,
                RosterLink.status.in_((RosterLinkStatus.invited, RosterLinkStatus.active)),
            )
        )
    }

    return ok({'users': [
        {'id': u.id, 'username': u.username, 'already_linked': u.id in linked_ids}
        for u in candidates
    ]})


# ── POST /<id>/attach-contract ───────────────────────────────────────────────────

@roster_api_bp.route('/<int:link_id>/attach-contract', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def attach_contract(current_user, link_id):
    """Attache un contrat de management (déjà créé via le contract builder) au
    lien roster. Réservé au producteur du lien — c'est lui qui formalise la
    relation, l'artiste garde la main via l'acceptation du contrat lui-même
    (signature) qui reste un processus séparé."""
    link = db.session.get(RosterLink, link_id)
    if not link:
        return err("Lien roster introuvable.", status=404)
    if current_user.id != link.producer_id:
        return err("Seul le producteur du lien peut y attacher un contrat.", status=403)
    if not current_user.can_use_management_contract:
        return err("Le contrat de management est réservé à l'abonnement Premium et plus.", status=403)

    data = request.get_json(silent=True) or {}
    contract_id = data.get('contract_id')
    contract = db.session.get(UserContract, contract_id) if contract_id else None
    if not contract:
        return err("Contrat introuvable.", status=404)
    if contract.user_id != current_user.id:
        return err("Ce contrat ne t'appartient pas.", status=403)
    if contract.contract_type != ContractTemplateTypeEnum.management:
        return err("Seul un contrat de type management peut être attaché à un lien roster.", status=400)

    link.management_contract_id = contract.id
    db.session.commit()

    return ok(data={'link': ser_roster_link(link, current_user.id)})
