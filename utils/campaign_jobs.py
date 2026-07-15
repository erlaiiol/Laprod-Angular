"""
Jobs APScheduler pour les campagnes de mailing.

  dispatch_campaigns_job  — envoie les campagnes dont le créneau est arrivé (10 min)
  campaign_opportunity_job — repère les vendeurs en pic d'intérêt et les prévient (hebdo)
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func

from extensions import db
from models import (
    User, Track, Favorite, ListeningHistory, UserNotificationLog,
)
from utils.campaign_service import (
    dispatch_due_campaigns, quota_status, audience_size,
    CampaignSegment,
)

logger = logging.getLogger(__name__)

# Un pic n'a de sens que s'il est à la fois RELATIF (plus que d'habitude) et
# ABSOLU (assez d'événements pour ne pas se déclencher sur 2 clics). Sans le
# seuil absolu, un vendeur passant de 1 à 3 écoutes recevrait « pic d'intérêt ».
SPIKE_RATIO         = 1.5
SPIKE_MIN_EVENTS    = 15
MIN_AUDIENCE        = 5   # inutile de pousser une campagne vers 2 personnes

NOTIF_TYPE = 'campaign_opportunity'


def dispatch_campaigns_job(app):
    """Envoie les campagnes planifiées dont l'heure est venue."""
    with app.app_context():
        try:
            count = dispatch_due_campaigns()
            if count:
                logger.info(f'[campagnes] {count} campagne(s) dispatchée(s)')
        except Exception as exc:
            db.session.rollback()
            logger.error(f'[campagnes] dispatch échoué : {exc}', exc_info=True)


def _interest_events(owner_id, since, until):
    """Nombre de signaux d'intérêt (favoris + écoutes) sur les beats d'un vendeur."""
    track_ids = select(Track.id).where(Track.composer_id == owner_id).scalar_subquery()

    favs = db.session.query(func.count(Favorite.id)).filter(
        Favorite.track_id.in_(track_ids),
        Favorite.created_at >= since, Favorite.created_at < until,
    ).scalar() or 0

    listens = db.session.query(func.count(ListeningHistory.id)).filter(
        ListeningHistory.track_id.in_(track_ids),
        ListeningHistory.listened_at >= since, ListeningHistory.listened_at < until,
    ).scalar() or 0

    return favs + listens


def campaign_opportunity_job(app):
    """Prévient les vendeurs qui traversent un pic d'intérêt.

    Le mail n'est envoyé que si TOUT est réuni : pic réel, audience suffisante,
    quota de campagne disponible, et pas déjà prévenu ce mois-ci. Un vendeur qui
    ne peut pas envoyer de campagne ne doit pas recevoir un mail l'invitant à en
    envoyer une — ce serait une frustration gratuite.
    """
    from utils.email_service import send_campaign_opportunity_email

    with app.app_context():
        now       = datetime.now()
        this_week = now - timedelta(days=7)
        prev_week = now - timedelta(days=14)
        period    = now.strftime('%Y-%m')   # une invitation par vendeur et par mois

        sellers = User.query.filter(
            User.account_status == 'active',
            db.or_(User.is_beatmaker.is_(True), User.is_mixmaster_engineer.is_(True)),
        ).all()

        notified = 0
        for seller in sellers:
            try:
                if not seller.is_premium_active:
                    continue  # les campagnes sont Premium : ne pas vendre du rêve

                if quota_status(seller.id)['remaining'] <= 0:
                    continue

                already = UserNotificationLog.query.filter_by(
                    user_id=seller.id, notification_type=NOTIF_TYPE, period_key=period,
                ).first()
                if already:
                    continue

                current  = _interest_events(seller.id, this_week, now)
                previous = _interest_events(seller.id, prev_week, this_week)

                if current < SPIKE_MIN_EVENTS:
                    continue
                if previous and current < previous * SPIKE_RATIO:
                    continue

                audience = max(
                    audience_size(seller.id, CampaignSegment.FAVORITES.value),
                    audience_size(seller.id, CampaignSegment.BUYERS.value),
                )
                if audience < MIN_AUDIENCE:
                    continue

                signal = (
                    f'Vos beats ont reçu {current} écoutes et mises en favori cette semaine'
                    + (f', contre {previous} la semaine dernière.' if previous else '.')
                )
                send_campaign_opportunity_email(seller, signal)

                db.session.add(UserNotificationLog(
                    user_id=seller.id, notification_type=NOTIF_TYPE, period_key=period,
                ))
                db.session.commit()
                notified += 1

            except Exception as exc:
                db.session.rollback()
                logger.error(f'[campagnes] opportunité vendeur #{seller.id} : {exc}')

        if notified:
            logger.info(f'[campagnes] {notified} vendeur(s) prévenu(s) d\'un pic d\'intérêt')
        return notified
