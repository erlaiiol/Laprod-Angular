"""
Tâches planifiées pour le cycle de vie des licences et de la plateforme.

run_contract_expiry_update(app)      → Quotidien à 0h : expire les licences échues + libère exclusivités
run_expiry_notifications(app)        → Quotidien à 8h : rappels 90/30/7/1 jours avant expiration
run_sole_licensee_notifications(app) → 1er du mois à 9h : "vous êtes le seul licencié"
run_stripe_reminder_job(app)         → Chaque lundi à 9h : rappel Stripe Connect aux non-configurés
"""
from datetime import date


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
