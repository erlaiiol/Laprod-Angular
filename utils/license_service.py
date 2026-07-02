"""
Service de gestion du cycle de vie des licences.

Fonctions utilitaires pour les achats (Purchase) vus comme des licences :
- Calcul des dates d'expiration
- Détection du statut "unique licencié"
- Requêtes pour les dashboards artiste et compositeur
"""
from datetime import datetime, timedelta
from decimal import Decimal

from extensions import db
from models import Purchase, LicenseNotificationLog


# ── Helpers de durée ──────────────────────────────────────────────────────────

def compute_expires_at(is_lifetime: bool, duration_years: int | None) -> datetime | None:
    """
    Calcule la date d'expiration d'une licence.

    - Lifetime (à vie) → None (pas d'expiration)
    - Streaming seul (duration_years == 0 ou None) → None
    - Durée en années → datetime dans N ans
    """
    if is_lifetime:
        return None
    if not duration_years:
        return None
    return datetime.now() + timedelta(days=365 * duration_years)


def build_duration_text(is_lifetime: bool, duration_years: int | None) -> str:
    if is_lifetime:
        return 'À vie + 70 ans'
    if not duration_years:
        return 'Streaming seul — perpétuel'
    return f"{duration_years} an{'s' if duration_years > 1 else ''}"


def compute_days_remaining(purchase: Purchase) -> int | None:
    """Jours restants avant expiration. None si lifetime ou streaming seul."""
    if not purchase.expires_at:
        return None
    delta = purchase.expires_at - datetime.now()
    return max(0, delta.days)


# ── Statut "unique licencié" ──────────────────────────────────────────────────

def is_sole_licensee(purchase: Purchase) -> bool:
    """
    Retourne True si l'acheteur est le seul détenteur d'une licence active
    sur ce track (hors achats exclusifs : ils sont par définition uniques).
    """
    count = db.session.query(Purchase).filter(
        Purchase.track_id == purchase.track_id,
        Purchase.license_status == 'active',
        Purchase.id != purchase.id,
    ).count()
    return count == 0


def get_all_sole_licensee_active_purchases() -> list[Purchase]:
    """
    Retourne tous les achats actifs dont l'acheteur est le seul licencié
    sur le track. Utilisé par la tâche planifiée mensuelle.
    """
    from sqlalchemy import func

    # Compter les achats actifs par track
    subq = (
        db.session.query(Purchase.track_id, func.count(Purchase.id).label('cnt'))
        .filter(Purchase.license_status == 'active')
        .group_by(Purchase.track_id)
        .subquery()
    )

    # Sélectionner les tracks avec exactement 1 licencié actif
    solo_track_ids = (
        db.session.query(subq.c.track_id)
        .filter(subq.c.cnt == 1)
        .scalar_subquery()
    )

    return (
        db.session.query(Purchase)
        .filter(
            Purchase.track_id.in_(solo_track_ids),
            Purchase.license_status == 'active',
        )
        .all()
    )


# ── Requêtes licences ─────────────────────────────────────────────────────────

def get_user_licenses(user_id: int) -> list[Purchase]:
    """Toutes les licences d'un artiste, triées par expiration imminente."""
    from sqlalchemy import case, nullslast

    purchases = (
        db.session.query(Purchase)
        .filter(Purchase.buyer_id == user_id)
        .order_by(
            # Expirés en dernier, actifs avec date d'expiration en premier
            case(
                (Purchase.license_status == 'expired', 2),
                (Purchase.license_status == 'renewed', 3),
                else_=1,
            ),
            nullslast(Purchase.expires_at.asc()),
        )
        .all()
    )
    return purchases


def get_composer_sold_licenses(composer_id: int) -> list[Purchase]:
    """Toutes les licences vendues par un compositeur."""
    from models import Track
    return (
        db.session.query(Purchase)
        .join(Track, Purchase.track_id == Track.id)
        .filter(Track.composer_id == composer_id)
        .order_by(Purchase.created_at.desc())
        .all()
    )


def get_expiring_licenses(days_ahead: int) -> list[Purchase]:
    """
    Licences actives qui expirent dans exactement `days_ahead` jours (±12h).
    Utilisé par les tâches planifiées de rappel.
    """
    now = datetime.now()
    target = now + timedelta(days=days_ahead)
    window_start = target - timedelta(hours=12)
    window_end   = target + timedelta(hours=12)

    return (
        db.session.query(Purchase)
        .filter(
            Purchase.license_status == 'active',
            Purchase.expires_at.isnot(None),
            Purchase.expires_at >= window_start,
            Purchase.expires_at <= window_end,
        )
        .all()
    )


# ── Prix de renouvellement ────────────────────────────────────────────────────

def get_renewal_price(purchase: Purchase) -> Decimal:
    """
    Calcule le prix de renouvellement d'une licence.
    Actuellement : même prix que le contrat original (contract_price + track_price).
    Peut être adapté pour offrir une réduction aux licenciés fidèles.
    """
    return purchase.price_paid


# ── Déduplication des notifications ──────────────────────────────────────────

def already_notified(purchase_id: int, notification_type: str, period_key: str) -> bool:
    """Vérifie si une notification a déjà été envoyée pour cette période."""
    return db.session.query(LicenseNotificationLog).filter_by(
        purchase_id=purchase_id,
        notification_type=notification_type,
        period_key=period_key,
    ).first() is not None


def log_notification(purchase_id: int, user_id: int, notification_type: str, period_key: str) -> None:
    """Enregistre l'envoi d'une notification pour éviter les doublons."""
    log = LicenseNotificationLog(
        purchase_id=purchase_id,
        user_id=user_id,
        notification_type=notification_type,
        period_key=period_key,
    )
    db.session.add(log)
    # Pas de commit ici : le contexte appelant gère la transaction
