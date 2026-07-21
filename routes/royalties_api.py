"""
Blueprint ROYALTIES API — Cap-table déclarative par titre

Consulter la cap-table d'un titre est libre pour toute partie prenante légitime
(compositeur, tout intervenant déjà référencé par une ligne, producteur ayant un
lien roster actif avec le compositeur, admin) — comme pour le roster et le
planning, celui qui reçoit une part n'a pas à payer pour la voir. Seule la
GESTION (ajouter/modifier/confirmer pour un tiers/retirer une ligne) est
réservée à can_view_royalties (Premium+), et seulement pour le compositeur ou
son producteur.

GET    /api/royalties/tracks/<track_id>/splits   → cap-table d'un titre
POST   /api/royalties/tracks/<track_id>/splits    → ajouter une ligne
PUT    /api/royalties/splits/<id>                  → modifier une ligne
POST   /api/royalties/splits/<id>/confirm           → confirmer sa part
DELETE /api/royalties/splits/<id>                    → retirer une ligne
"""
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request
from flask_jwt_extended import jwt_required
from sqlalchemy import func, select

from extensions import csrf, db
from models import RosterLink, RosterLinkStatus, Track, TrackSplit, TrackSplitRole, TrackSplitStatus, User
from serializers import err, ok
from serializers import track_split as ser_track_split
from utils.auth_helpers import require_user

royalties_api_bp = Blueprint('royalties_api', __name__, url_prefix='/api/royalties')


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _is_producer_of(user_id: int, composer_id: int) -> bool:
    return db.session.scalar(
        select(RosterLink.id).where(
            RosterLink.producer_id == user_id,
            RosterLink.artist_id == composer_id,
            RosterLink.status == RosterLinkStatus.active,
        )
    ) is not None


def _can_view(user, track) -> bool:
    if user.is_admin or user.id == track.composer_id:
        return True
    if _is_producer_of(user.id, track.composer_id):
        return True
    return db.session.scalar(
        select(TrackSplit.id).where(TrackSplit.track_id == track.id, TrackSplit.user_id == user.id)
    ) is not None


def _can_manage(user, track) -> bool:
    if not user.can_view_royalties:
        return False
    return user.id == track.composer_id or _is_producer_of(user.id, track.composer_id) or user.is_admin


def _parse_percentage(raw):
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, TypeError):
        return None
    if value <= 0 or value > 100:
        return None
    return value


def _current_total(track_id: int, exclude_split_id: int | None = None) -> Decimal:
    query = select(func.coalesce(func.sum(TrackSplit.percentage), 0)).where(TrackSplit.track_id == track_id)
    if exclude_split_id:
        query = query.where(TrackSplit.id != exclude_split_id)
    return db.session.scalar(query) or Decimal('0')


# ── GET /tracks/<id>/splits ────────────────────────────────────────────────────

@royalties_api_bp.route('/tracks/<int:track_id>/splits', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def list_splits(current_user, track_id):
    track = db.session.get(Track, track_id)
    if not track:
        return err("Titre introuvable.", status=404)
    if not _can_view(current_user, track):
        return err("Tu n'as pas accès à la cap-table de ce titre.", status=403)

    splits = db.session.scalars(
        select(TrackSplit).where(TrackSplit.track_id == track_id).order_by(TrackSplit.created_at.asc())
    ).all()
    total = sum((s.percentage for s in splits), Decimal('0'))

    return ok(data={
        'splits': [ser_track_split(s) for s in splits],
        'total_percentage': float(total),
        'can_manage': _can_manage(current_user, track),
    })


# ── POST /tracks/<id>/splits ───────────────────────────────────────────────────

@royalties_api_bp.route('/tracks/<int:track_id>/splits', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def add_split(current_user, track_id):
    track = db.session.get(Track, track_id)
    if not track:
        return err("Titre introuvable.", status=404)
    if not _can_manage(current_user, track):
        return err(
            "Ajouter une part est réservé au compositeur du titre (ou à son producteur) "
            "à partir de l'abonnement Premium.",
            status=403,
        )

    data = request.get_json(silent=True) or {}
    percentage = _parse_percentage(data.get('percentage'))
    if percentage is None:
        return err("Le pourcentage doit être compris entre 0 et 100.", status=400)

    try:
        role = TrackSplitRole(data.get('role'))
    except ValueError:
        return err("Rôle invalide.", status=400)

    user_id = data.get('user_id')
    linked_user = db.session.get(User, user_id) if user_id else None
    external_name = (data.get('external_name') or '').strip()
    if linked_user:
        external_name = external_name or linked_user.username
    elif not external_name:
        return err("Indique un nom pour cette part (ou lie un compte LaProd existant).", status=400)

    if _current_total(track_id) + percentage > 100:
        return err(
            f"Cette part ferait dépasser 100 % de la cap-table "
            f"(déjà {_current_total(track_id)} % attribués).",
            status=409,
        )

    split = TrackSplit(
        track_id=track_id,
        user_id=linked_user.id if linked_user else None,
        external_name=external_name,
        role=role,
        percentage=percentage,
        added_by_id=current_user.id,
    )
    db.session.add(split)
    db.session.commit()

    return ok(data={'split': ser_track_split(split)}, status=201)


# ── PUT /splits/<id> ─────────────────────────────────────────────────────────────

@royalties_api_bp.route('/splits/<int:split_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_user
def update_split(current_user, split_id):
    split = db.session.get(TrackSplit, split_id)
    if not split:
        return err("Part introuvable.", status=404)
    if not _can_manage(current_user, split.track):
        return err("Modifier cette part est réservé au compositeur du titre ou à son producteur.", status=403)

    data = request.get_json(silent=True) or {}

    new_percentage = split.percentage
    if 'percentage' in data:
        parsed = _parse_percentage(data.get('percentage'))
        if parsed is None:
            return err("Le pourcentage doit être compris entre 0 et 100.", status=400)
        new_percentage = parsed

    if _current_total(split.track_id, exclude_split_id=split.id) + new_percentage > 100:
        return err("Cette modification ferait dépasser 100 % de la cap-table.", status=409)
    split.percentage = new_percentage

    if 'role' in data:
        try:
            split.role = TrackSplitRole(data['role'])
        except ValueError:
            return err("Rôle invalide.", status=400)

    if 'external_name' in data:
        name = (data.get('external_name') or '').strip()
        if name:
            split.external_name = name

    db.session.commit()
    return ok(data={'split': ser_track_split(split)})


# ── POST /splits/<id>/confirm ───────────────────────────────────────────────────

@royalties_api_bp.route('/splits/<int:split_id>/confirm', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def confirm_split(current_user, split_id):
    """Confirmer sa propre part ne gate rien par palier : c'est un acquiescement,
    pas un acte de gestion. Le compositeur/producteur peut aussi confirmer au nom
    d'une partie externe sans compte LaProd."""
    split = db.session.get(TrackSplit, split_id)
    if not split:
        return err("Part introuvable.", status=404)

    is_split_owner = split.user_id == current_user.id
    is_manager = _can_manage(current_user, split.track)
    if not (is_split_owner or is_manager):
        return err("Tu ne peux pas confirmer cette part.", status=403)

    split.status = TrackSplitStatus.confirmed
    db.session.commit()
    return ok(data={'split': ser_track_split(split)})


# ── DELETE /splits/<id> ──────────────────────────────────────────────────────────

@royalties_api_bp.route('/splits/<int:split_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_user
def delete_split(current_user, split_id):
    split = db.session.get(TrackSplit, split_id)
    if not split:
        return err("Part introuvable.", status=404)
    if not _can_manage(current_user, split.track):
        return err("Retirer cette part est réservé au compositeur du titre ou à son producteur.", status=403)

    db.session.delete(split)
    db.session.commit()
    return ok(message='Part retirée.')
