"""
Service de gestion du cycle de vie des contrats.

Responsabilités :
- Expiration automatique des licences échues
- Remise en vente des tracks dont l'exclusivité a expiré
- Liaison entre renouvellements
"""
from datetime import datetime

from flask import current_app
from extensions import db
from models import Purchase, Track, Contract


def expire_overdue_contracts(app=None) -> int:
    """
    Passe en 'expired' tous les achats actifs dont expires_at est dépassé.
    Pour les licences exclusives expirées : remet le track en vente.

    Retourne le nombre de licences expirées.
    """
    ctx = app.app_context() if app else None
    if ctx:
        ctx.push()

    try:
        now = datetime.now()
        overdue = (
            db.session.query(Purchase)
            .filter(
                Purchase.license_status == 'active',
                Purchase.expires_at.isnot(None),
                Purchase.expires_at <= now,
            )
            .all()
        )

        count = 0
        for purchase in overdue:
            purchase.license_status = 'expired'
            count += 1

            # Mettre à jour le Contract lié si présent
            if purchase.contract:
                purchase.contract.status = 'expired'

            # Remettre le track en vente si c'était une exclusivité
            if purchase.is_exclusive:
                track = db.session.get(Track, purchase.track_id)
                if track and track.exclusive_buyer_id == purchase.buyer_id:
                    track.is_exclusive_sold  = False
                    track.exclusive_buyer_id = None
                    # exclusive_sold_at conservé comme historique

                    _notify_exclusive_expired(track, purchase)

            _notify_license_expired(purchase)

        db.session.commit()

        if count:
            logger = current_app.logger if app is None else app.logger
            logger.info(f"expire_overdue_contracts : {count} licence(s) expirée(s)")

        return count

    except Exception as exc:
        db.session.rollback()
        logger = current_app.logger if app is None else app.logger
        logger.error(f"expire_overdue_contracts : erreur — {exc}", exc_info=True)
        raise
    finally:
        if ctx:
            ctx.pop()


def get_contracts_expiring_in(days: int) -> list[Purchase]:
    """
    Retourne les achats actifs qui expirent dans ± 12h autour de `days` jours.
    """
    from utils.license_service import get_expiring_licenses
    return get_expiring_licenses(days)


def mark_contract_renewed(old_purchase: Purchase, new_purchase: Purchase) -> None:
    """
    Lie deux licences consécutives (renouvellement).
    La nouvelle est active, l'ancienne passe à 'renewed'.
    """
    old_purchase.license_status = 'renewed'
    old_purchase.renewed_to_id  = new_purchase.id
    new_purchase.renewed_from_id = old_purchase.id

    if old_purchase.contract:
        old_purchase.contract.status = 'renewed'


# ── Notifications internes (import tardif pour éviter les circularités) ───────

def _notify_license_expired(purchase: Purchase) -> None:
    try:
        from utils.notification_service import notify_license_expired
        notify_license_expired(purchase)
    except Exception as exc:
        try:
            current_app.logger.error(f"notify_license_expired erreur: {exc}")
        except RuntimeError:
            pass


def _notify_exclusive_expired(track: Track, purchase: Purchase) -> None:
    try:
        from utils.notification_service import notify_exclusive_license_expired
        notify_exclusive_license_expired(track, purchase)
    except Exception as exc:
        try:
            current_app.logger.error(f"notify_exclusive_license_expired erreur: {exc}")
        except RuntimeError:
            pass
