"""
Blueprint PLANNING API — Rétroplanning partagé sur un lien roster actif

Libre à tous les paliers, comme le roster : seule l'appartenance au lien
(producteur ou artiste du RosterLink) conditionne l'accès.

POST   /api/planning/roster/<link_id>/events   → créer un événement
GET    /api/planning/roster/<link_id>/events    → lister les événements d'un lien
GET    /api/planning/mine                        → agrégat de tous mes événements
PUT    /api/planning/events/<id>                  → modifier (créateur)
POST   /api/planning/events/<id>/confirm           → confirmer (l'autre partie que le créateur)
POST   /api/planning/events/<id>/cancel             → annuler
DELETE /api/planning/events/<id>                     → supprimer (créateur, ou déjà annulé)

GET    /api/planning/events/<id>/ics                  → export .ics d'un événement
GET    /api/planning/roster/<link_id>/export.ics        → export .ics d'un lien entier
POST   /api/planning/ical-token/regenerate                → (re)génère mon token de flux
GET    /api/planning/feed/<token>.ics                        → flux iCal PUBLIC (pas de JWT)
"""
import secrets
from datetime import datetime

from flask import Blueprint, Response, request
from flask_jwt_extended import jwt_required
from sqlalchemy import select

from extensions import csrf, db, limiter
from models import PlanningEvent, PlanningEventStatus, PlanningEventTypeEnum, RosterLink, RosterLinkStatus, User
from serializers import err, ok
from serializers import planning_event as ser_planning_event
from utils.auth_helpers import require_user
from utils.ical_export import build_ics_calendar
from utils.notification_service import create_notification

planning_api_bp = Blueprint('planning_api', __name__, url_prefix='/api/planning')

_PLANNING_URL = '/producer/planning'


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _member_link(link_id, user_id):
    """RosterLink actif dont user_id est producteur ou artiste, sinon None."""
    link = db.session.get(RosterLink, link_id)
    if not link or link.status != RosterLinkStatus.active:
        return None
    if user_id not in (link.producer_id, link.artist_id):
        return None
    return link


def _counterpart_id(link, user_id):
    return link.artist_id if user_id == link.producer_id else link.producer_id


def _parse_datetime(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ── POST /roster/<link_id>/events ─────────────────────────────────────────────────

@planning_api_bp.route('/roster/<int:link_id>/events', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def create_event(current_user, link_id):
    link = _member_link(link_id, current_user.id)
    if not link:
        return err("Lien roster introuvable ou inactif.", status=404)

    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    if not title:
        return err("Le titre est obligatoire.", status=400)

    start_at = _parse_datetime(data.get('start_at'))
    if not start_at:
        return err("Date de début invalide.", status=400)
    end_at = _parse_datetime(data.get('end_at'))
    if end_at and end_at < start_at:
        return err("La date de fin ne peut pas précéder la date de début.", status=400)

    try:
        event_type = PlanningEventTypeEnum(data.get('event_type', 'other'))
    except ValueError:
        event_type = PlanningEventTypeEnum.other

    event = PlanningEvent(
        roster_link_id=link.id,
        created_by_id=current_user.id,
        title=title,
        description=(data.get('description') or '').strip() or None,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        timezone=data.get('timezone') or 'Europe/Paris',
        all_day=bool(data.get('all_day', False)),
        location=(data.get('location') or '').strip() or None,
    )
    db.session.add(event)
    db.session.commit()

    create_notification(
        user_id=_counterpart_id(link, current_user.id),
        notif_type='planning_event_created',
        title='Nouvel événement',
        message=f'{current_user.username} a ajouté "{title}" au rétroplanning.',
        link=_PLANNING_URL,
    )

    return ok(data={'event': ser_planning_event(event)}, status=201)


# ── GET /roster/<link_id>/events ──────────────────────────────────────────────────

@planning_api_bp.route('/roster/<int:link_id>/events', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def list_events(current_user, link_id):
    link = _member_link(link_id, current_user.id)
    if not link:
        return err("Lien roster introuvable ou inactif.", status=404)

    query = select(PlanningEvent).where(PlanningEvent.roster_link_id == link.id)

    date_from = _parse_datetime(request.args.get('from'))
    date_to = _parse_datetime(request.args.get('to'))
    if date_from:
        query = query.where(PlanningEvent.start_at >= date_from)
    if date_to:
        query = query.where(PlanningEvent.start_at <= date_to)

    raw_type = request.args.get('type')
    if raw_type:
        try:
            query = query.where(PlanningEvent.event_type == PlanningEventTypeEnum(raw_type))
        except ValueError:
            pass

    events = db.session.scalars(query.order_by(PlanningEvent.start_at.asc())).all()
    return ok(data={'events': [ser_planning_event(e) for e in events]})


# ── GET /mine ──────────────────────────────────────────────────────────────────────

@planning_api_bp.route('/mine', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def mine(current_user):
    link_ids = db.session.scalars(
        select(RosterLink.id).where(
            RosterLink.status == RosterLinkStatus.active,
            (RosterLink.producer_id == current_user.id) | (RosterLink.artist_id == current_user.id),
        )
    ).all()
    if not link_ids:
        return ok(data={'events': []})

    events = db.session.scalars(
        select(PlanningEvent)
        .where(PlanningEvent.roster_link_id.in_(link_ids))
        .order_by(PlanningEvent.start_at.asc())
    ).all()
    return ok(data={'events': [ser_planning_event(e) for e in events]})


# ── PUT /events/<id> ─────────────────────────────────────────────────────────────

@planning_api_bp.route('/events/<int:event_id>', methods=['PUT'])
@jwt_required()
@csrf.exempt
@require_user
def update_event(current_user, event_id):
    event = db.session.get(PlanningEvent, event_id)
    if not event:
        return err("Événement introuvable.", status=404)
    if event.created_by_id != current_user.id:
        return err("Seul le créateur peut modifier cet événement.", status=403)

    data = request.get_json(silent=True) or {}
    if 'title' in data:
        title = (data.get('title') or '').strip()
        if not title:
            return err("Le titre est obligatoire.", status=400)
        event.title = title
    if 'description' in data:
        event.description = (data.get('description') or '').strip() or None
    if 'location' in data:
        event.location = (data.get('location') or '').strip() or None
    if 'event_type' in data:
        try:
            event.event_type = PlanningEventTypeEnum(data['event_type'])
        except ValueError:
            return err("Type d'événement invalide.", status=400)
    if 'start_at' in data:
        start_at = _parse_datetime(data.get('start_at'))
        if not start_at:
            return err("Date de début invalide.", status=400)
        event.start_at = start_at
    if 'end_at' in data:
        event.end_at = _parse_datetime(data.get('end_at'))
    if event.end_at and event.end_at < event.start_at:
        return err("La date de fin ne peut pas précéder la date de début.", status=400)
    if 'timezone' in data:
        event.timezone = data.get('timezone') or 'Europe/Paris'
    if 'all_day' in data:
        event.all_day = bool(data.get('all_day'))

    db.session.commit()
    return ok(data={'event': ser_planning_event(event)})


# ── POST /events/<id>/confirm ──────────────────────────────────────────────────────

@planning_api_bp.route('/events/<int:event_id>/confirm', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def confirm_event(current_user, event_id):
    event = db.session.get(PlanningEvent, event_id)
    if not event:
        return err("Événement introuvable.", status=404)
    link = event.roster_link
    if current_user.id not in (link.producer_id, link.artist_id):
        return err("Cet événement ne te concerne pas.", status=403)
    if event.status != PlanningEventStatus.proposed:
        return err("Cet événement n'est plus en attente de confirmation.", status=409)

    event.status = PlanningEventStatus.confirmed
    db.session.commit()

    create_notification(
        user_id=event.created_by_id,
        notif_type='planning_event_confirmed',
        title='Événement confirmé',
        message=f'"{event.title}" a été confirmé.',
        link=_PLANNING_URL,
    )

    return ok(data={'event': ser_planning_event(event)})


# ── POST /events/<id>/cancel ────────────────────────────────────────────────────────

@planning_api_bp.route('/events/<int:event_id>/cancel', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def cancel_event(current_user, event_id):
    event = db.session.get(PlanningEvent, event_id)
    if not event:
        return err("Événement introuvable.", status=404)
    link = event.roster_link
    if current_user.id not in (link.producer_id, link.artist_id):
        return err("Cet événement ne te concerne pas.", status=403)
    if event.status == PlanningEventStatus.cancelled:
        return err("Cet événement est déjà annulé.", status=409)

    event.status = PlanningEventStatus.cancelled
    db.session.commit()

    create_notification(
        user_id=_counterpart_id(link, current_user.id),
        notif_type='planning_event_cancelled',
        title='Événement annulé',
        message=f'"{event.title}" a été annulé.',
        link=_PLANNING_URL,
    )

    return ok(data={'event': ser_planning_event(event)})


# ── DELETE /events/<id> ─────────────────────────────────────────────────────────────

@planning_api_bp.route('/events/<int:event_id>', methods=['DELETE'])
@jwt_required()
@csrf.exempt
@require_user
def delete_event(current_user, event_id):
    event = db.session.get(PlanningEvent, event_id)
    if not event:
        return err("Événement introuvable.", status=404)
    if event.created_by_id != current_user.id and event.status != PlanningEventStatus.cancelled:
        return err("Seul le créateur peut supprimer cet événement.", status=403)

    db.session.delete(event)
    db.session.commit()
    return ok(message='Événement supprimé.')


# ── Export .ics (authentifié) ────────────────────────────────────────────────────────

@planning_api_bp.route('/events/<int:event_id>/ics', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def export_event_ics(current_user, event_id):
    event = db.session.get(PlanningEvent, event_id)
    if not event:
        return err("Événement introuvable.", status=404)
    link = event.roster_link
    if current_user.id not in (link.producer_id, link.artist_id):
        return err("Cet événement ne te concerne pas.", status=403)

    ics = build_ics_calendar([event], calendar_name=event.title)
    return Response(ics, mimetype='text/calendar',
                     headers={'Content-Disposition': f'attachment; filename="{event.id}.ics"'})


@planning_api_bp.route('/roster/<int:link_id>/export.ics', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def export_roster_ics(current_user, link_id):
    link = _member_link(link_id, current_user.id)
    if not link:
        return err("Lien roster introuvable ou inactif.", status=404)

    events = db.session.scalars(
        select(PlanningEvent)
        .where(PlanningEvent.roster_link_id == link.id)
        .order_by(PlanningEvent.start_at.asc())
    ).all()
    ics = build_ics_calendar(events)
    return Response(ics, mimetype='text/calendar',
                     headers={'Content-Disposition': 'attachment; filename="roster.ics"'})


# ── Abonnement iCal (token opaque, régénérable) ────────────────────────────────────

@planning_api_bp.route('/ical-token/regenerate', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def regenerate_ical_token(current_user):
    current_user.ical_feed_token = secrets.token_urlsafe(32)
    db.session.commit()
    return ok(data={'feed_path': f'/api/planning/feed/{current_user.ical_feed_token}.ics'})


@planning_api_bp.route('/feed/<token>.ics', methods=['GET'])
@limiter.limit('30 per hour')
def ical_feed(token):
    """Flux public — pollé par Apple/Google Calendar sans authentification
    interactive. Le token opaque (régénérable via /ical-token/regenerate) fait
    office de secret ; il n'a pas d'expiration, contrairement à un JWT."""
    user = db.session.scalar(select(User).where(User.ical_feed_token == token))
    if not user:
        return err("Flux introuvable.", status=404)

    link_ids = db.session.scalars(
        select(RosterLink.id).where(
            RosterLink.status == RosterLinkStatus.active,
            (RosterLink.producer_id == user.id) | (RosterLink.artist_id == user.id),
        )
    ).all()
    events = []
    if link_ids:
        events = db.session.scalars(
            select(PlanningEvent).where(PlanningEvent.roster_link_id.in_(link_ids))
        ).all()

    ics = build_ics_calendar(events, calendar_name=f'LaProd — Rétroplanning de {user.username}')
    return Response(ics, mimetype='text/calendar')
