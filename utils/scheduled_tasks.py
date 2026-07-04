"""
Tâches planifiées pour le cycle de vie des licences et de la plateforme.

run_contract_expiry_update(app)      → Quotidien à 0h : expire les licences échues + libère exclusivités
run_expiry_notifications(app)        → Quotidien à 8h : rappels 90/30/7/1 jours avant expiration
run_sole_licensee_notifications(app) → 1er du mois à 9h : "vous êtes le seul licencié"
run_stripe_reminder_job(app)         → Chaque lundi à 9h : rappel Stripe Connect aux non-configurés
run_reengagement_emails(app)         → Chaque mercredi à 10h : re-engagement des utilisateurs inactifs 7j+
"""
from datetime import date, datetime, timedelta


def run_contract_expiry_update(app):
    """
    Quotidien.
    - Passe license_status='expired' sur les achats échus
    - Remet les tracks exclusifs en vente si leur licence a expiré
    """
    with app.app_context():
        from utils.contract_service import expire_overdue_contracts
        count = expire_overdue_contracts()
        app.logger.info(f"[scheduler] run_contract_expiry_update : {count} licence(s) expirée(s)")


def run_expiry_notifications(app):
    """
    Quotidien à 8h.
    Envoie des rappels d'expiration pour les licences expirant dans 90, 30, 7 et 1 jour.
    Protégé contre les doublons via LicenseNotificationLog.
    """
    with app.app_context():
        from utils.license_service import (
            get_expiring_licenses, already_notified, log_notification,
        )
        from utils.notification_service import notify_expiry_approaching
        from utils.email_service import send_expiry_reminder_email
        from extensions import db

        total = 0
        for days in [90, 30, 7, 1]:
            purchases = get_expiring_licenses(days)
            for p in purchases:
                period_key = f"{date.today().isoformat()}-{days}d"
                notif_type = f"expiry_{days}d"
                if already_notified(p.id, notif_type, period_key):
                    continue
                try:
                    notify_expiry_approaching(p, days)
                    log_notification(p.id, p.buyer_id, notif_type, period_key)
                    db.session.commit()
                    total += 1
                except Exception as exc:
                    db.session.rollback()
                    app.logger.error(f"[scheduler] expiry {days}d purchase #{p.id}: {exc}")

                try:
                    send_expiry_reminder_email(p, days)
                except Exception as exc:
                    app.logger.error(f"[scheduler] email expiry {days}d purchase #{p.id}: {exc}")

        app.logger.info(f"[scheduler] run_expiry_notifications : {total} notification(s) envoyée(s)")


def run_sole_licensee_notifications(app):
    """
    1er du mois à 9h.
    Notifie les artistes qui sont l'unique licencié actif d'une composition.
    Protégé contre les doublons : une seule notification par mois par achat.
    """
    with app.app_context():
        from utils.license_service import (
            get_all_sole_licensee_active_purchases,
            already_notified, log_notification,
        )
        from utils.notification_service import notify_sole_licensee_monthly
        from utils.email_service import send_sole_licensee_email
        from extensions import db

        period_key = date.today().strftime('%Y-%m')
        notif_type = 'sole_licensee_monthly'
        purchases  = get_all_sole_licensee_active_purchases()
        total      = 0

        for p in purchases:
            if already_notified(p.id, notif_type, period_key):
                continue
            try:
                notify_sole_licensee_monthly(p)
                log_notification(p.id, p.buyer_id, notif_type, period_key)
                db.session.commit()
                total += 1
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"[scheduler] sole_licensee purchase #{p.id}: {exc}")

            try:
                send_sole_licensee_email(p)
            except Exception as exc:
                app.logger.error(f"[scheduler] email sole_licensee purchase #{p.id}: {exc}")

        app.logger.info(f"[scheduler] run_sole_licensee_notifications : {total} notification(s) envoyée(s)")


def run_stripe_reminder_job(app):
    """
    Chaque lundi à 9h.
    Envoie un rappel in-app aux beatmakers et mix engineers qui n'ont pas encore
    finalisé leur onboarding Stripe Connect.
    Dédupliqué dans notify_stripe_connect_reminder() : pas de doublon si une notif
    non lue de ce type existe depuis moins de 7 jours.
    """
    with app.app_context():
        from extensions import db
        from models import User
        from utils.notification_service import notify_stripe_connect_reminder

        users = User.query.filter(
            (User.is_beatmaker == True) | (User.is_mix_engineer == True),
            User.stripe_onboarding_complete == False,
            User.user_type_selected == True,
        ).all()

        sent = 0
        for user in users:
            try:
                notif = notify_stripe_connect_reminder(user.id)
                if notif:
                    db.session.commit()
                    sent += 1
                else:
                    db.session.rollback()
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"[scheduler] stripe_reminder user #{user.id}: {exc}")

        app.logger.info(f"[scheduler] run_stripe_reminder_job : {sent}/{len(users)} rappel(s) envoyé(s)")


def run_reengagement_emails(app):
    """
    Chaque mercredi à 10h.
    Envoie un email de re-engagement aux utilisateurs inactifs depuis 7+ jours :
      - Beatmakers : aucun upload depuis 7 jours
      - Artistes   : aucune écoute depuis 7 jours
      - Mix engineers : aucune demande reçue depuis 7 jours
    Dédupliqué par semaine ISO (une seule notification de chaque type par semaine).
    """
    with app.app_context():
        from extensions import db
        from models import User, Track, ListenEvent, MixMasterRequest, UserNotificationLog
        from utils.email_service import (
            send_reengagement_beatmaker_email,
            send_reengagement_artist_email,
            send_reengagement_mix_engineer_email,
        )

        cutoff       = datetime.utcnow() - timedelta(days=7)
        period_key   = datetime.utcnow().strftime('%Y-W%W')  # ex: '2026-W27'
        sent_bm = sent_ar = sent_me = 0

        def _already_sent(user_id, notif_type):
            return db.session.query(UserNotificationLog).filter_by(
                user_id=user_id,
                notification_type=notif_type,
                period_key=period_key,
            ).first() is not None

        def _log_sent(user_id, notif_type):
            log = UserNotificationLog(
                user_id=user_id,
                notification_type=notif_type,
                period_key=period_key,
                sent_at=datetime.utcnow(),
            )
            db.session.add(log)
            db.session.commit()

        # ── Beatmakers inactifs ───────────────────────────────────────────────
        beatmakers = User.query.filter(
            User.is_beatmaker == True,
            User.account_status == 'active',
            User.email_verified == True,
        ).all()

        for user in beatmakers:
            if _already_sent(user.id, 'reengagement_beatmaker'):
                continue

            last_track = (
                Track.query
                .filter_by(composer_id=user.id)
                .order_by(Track.created_at.desc())
                .first()
            )

            # Inactif si jamais uploadé ou dernier upload > 7j
            if last_track and last_track.created_at > cutoff:
                continue

            track_count = Track.query.filter_by(composer_id=user.id).count()

            try:
                send_reengagement_beatmaker_email(user, last_track, track_count)
                _log_sent(user.id, 'reengagement_beatmaker')
                sent_bm += 1
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"[scheduler] reengagement_beatmaker user #{user.id}: {exc}")

        # ── Artistes inactifs ─────────────────────────────────────────────────
        artists = User.query.filter(
            User.is_artist == True,
            User.account_status == 'active',
            User.email_verified == True,
        ).all()

        for user in artists:
            if _already_sent(user.id, 'reengagement_artist'):
                continue

            last_event = (
                ListenEvent.query
                .filter_by(user_id=user.id)
                .order_by(ListenEvent.created_at.desc())
                .first()
            )

            # Inactif si jamais écouté ou dernière écoute > 7j
            if last_event and last_event.created_at > cutoff:
                continue

            # Récupère les 3 derniers favoris ou écoutes pour l'email
            from models import Favorite, Track as TrackModel
            recent_tracks = (
                TrackModel.query
                .join(Favorite, Favorite.track_id == TrackModel.id)
                .filter(Favorite.user_id == user.id)
                .order_by(Favorite.created_at.desc())
                .limit(3)
                .all()
            )
            if not recent_tracks:
                recent_tracks = (
                    TrackModel.query
                    .join(ListenEvent, ListenEvent.track_id == TrackModel.id)
                    .filter(ListenEvent.user_id == user.id)
                    .order_by(ListenEvent.created_at.desc())
                    .limit(3)
                    .all()
                )

            try:
                send_reengagement_artist_email(user, recent_tracks)
                _log_sent(user.id, 'reengagement_artist')
                sent_ar += 1
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"[scheduler] reengagement_artist user #{user.id}: {exc}")

        # ── Mix engineers inactifs ────────────────────────────────────────────
        engineers = User.query.filter(
            User.is_mix_engineer == True,
            User.account_status == 'active',
            User.email_verified == True,
        ).all()

        for user in engineers:
            if _already_sent(user.id, 'reengagement_mix_engineer'):
                continue

            last_request = (
                MixMasterRequest.query
                .filter_by(engineer_id=user.id)
                .order_by(MixMasterRequest.created_at.desc())
                .first()
            )

            # Inactif si jamais reçu de demande ou dernière > 7j
            if last_request and last_request.created_at > cutoff:
                continue

            completed_count = MixMasterRequest.query.filter_by(
                engineer_id=user.id, status='completed'
            ).count()

            # Calcul approximatif des gains totaux (somme des remaining_amount complétés)
            from sqlalchemy import func
            total_earnings_row = db.session.query(
                func.sum(MixMasterRequest.total_price * 0.9)
            ).filter_by(engineer_id=user.id, status='completed').scalar()
            total_earnings = round(float(total_earnings_row), 2) if total_earnings_row else None

            try:
                send_reengagement_mix_engineer_email(user, completed_count, total_earnings)
                _log_sent(user.id, 'reengagement_mix_engineer')
                sent_me += 1
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"[scheduler] reengagement_mix_engineer user #{user.id}: {exc}")

        app.logger.info(
            f"[scheduler] run_reengagement_emails : "
            f"{sent_bm} beatmaker(s) / {sent_ar} artiste(s) / {sent_me} engineer(s)"
        )


def run_guest_topline_cleanup(app):
    """
    Toutes les heures.
    Supprime les toplines guest dont le TTL 24h est expiré et qui n'ont pas été réclamées.
    """
    with app.app_context():
        from extensions import db
        from models import Topline
        import config

        expired = (
            db.session.query(Topline)
            .filter(
                Topline.artist_id.is_(None),
                Topline.guest_expires_at.isnot(None),
                Topline.guest_expires_at < datetime.utcnow(),
            )
            .all()
        )

        count = 0
        for tl in expired:
            try:
                file_path = config.UPLOAD_FOLDER / tl.audio_file.replace('audio/', '', 1)
                if file_path.exists():
                    file_path.unlink()
                db.session.delete(tl)
                count += 1
            except Exception as exc:
                db.session.rollback()
                app.logger.error(f"[scheduler] guest_topline_cleanup #{tl.id}: {exc}")

        if count:
            db.session.commit()

        app.logger.info(f"[scheduler] run_guest_topline_cleanup : {count} topline(s) purgée(s)")
