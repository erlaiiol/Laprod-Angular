"""
Jobs APScheduler pour le rétroplanning partagé (roster).

  run_planning_event_reminders_job — rappels 48h puis 2h avant chaque
  événement confirmé, aux deux parties du lien roster (10 min)
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from extensions import db
from models import PlanningEvent, PlanningEventStatus, RosterLinkStatus, UserNotificationLog
from utils.notification_service import create_notification

logger = logging.getLogger(__name__)

_PLANNING_URL = '/producer/planning'

# Bornes (basse exclusive, haute inclusive) avant l'événement. Volontairement
# non chevauchantes : un événement à 1h30 ne doit déclencher QUE le rappel 2h,
# jamais le 48h en même temps — sinon le message « a lieu dans 48h » serait
# factuellement faux pour un événement en réalité imminent. Un événement créé
# tardivement (moins de 2h avant le début) ne recevra donc jamais de rappel
# 48h : il n'y a pas de façon exacte de l'envoyer rétroactivement.
_REMINDER_WINDOWS = (
    (timedelta(hours=2),  timedelta(hours=48), 'planning_reminder_48h', '48h'),
    (timedelta(hours=0),  timedelta(hours=2),  'planning_reminder_2h',  '2h'),
)


def run_planning_event_reminders_job(app):
    """Notifie producteur et artiste 48h puis 2h avant chaque événement confirmé.

    Dédupliqué via UserNotificationLog (period_key = l'événement, un couple
    destinataire+type de rappel ne peut apparaître qu'une fois grâce à la
    contrainte unique en base) — même mécanisme que campaign_jobs.py et
    run_reengagement_emails(). Le check préalable (`already`) est une pure
    optimisation et reste racy en soi (deux exécutions peuvent le franchir
    toutes les deux) : la sécurité réelle vient de la contrainte unique
    (user_id, notification_type, period_key) sur UserNotificationLog — si deux
    process tentent de committer la même ligne, le second lève un
    IntegrityError, capturé et journalisé ci-dessous, sans jamais laisser
    passer un rappel en double.
    """
    with app.app_context():
        now  = datetime.now()
        sent = 0

        for lower, upper, notif_type, label in _REMINDER_WINDOWS:
            due = db.session.scalars(
                select(PlanningEvent).where(
                    PlanningEvent.status == PlanningEventStatus.confirmed,
                    PlanningEvent.start_at > now + lower,
                    PlanningEvent.start_at <= now + upper,
                )
            ).all()

            for event in due:
                link = event.roster_link
                # Le lien a pu être révoqué/quitté après la création de
                # l'événement : pas de rappel pour une relation qui n'existe
                # plus, même si l'événement lui-même n'a pas été annulé.
                if link.status != RosterLinkStatus.active:
                    continue

                period_key = f'planning-event-{event.id}'

                for recipient_id in {link.producer_id, link.artist_id}:
                    already = db.session.query(UserNotificationLog).filter_by(
                        user_id=recipient_id, notification_type=notif_type, period_key=period_key,
                    ).first()
                    if already:
                        continue

                    try:
                        create_notification(
                            user_id=recipient_id,
                            notif_type=notif_type,
                            title=f'Rappel — dans {label}',
                            message=f'"{event.title}" a lieu dans {label}.',
                            link=_PLANNING_URL,
                        )
                        db.session.add(UserNotificationLog(
                            user_id=recipient_id, notification_type=notif_type, period_key=period_key,
                        ))
                        db.session.commit()
                        sent += 1
                    except Exception as exc:
                        db.session.rollback()
                        logger.error(
                            f'[planning] rappel {label} event #{event.id} user #{recipient_id} : {exc}'
                        )

        if sent:
            logger.info(f'[planning] {sent} rappel(s) envoyé(s)')
        return sent
