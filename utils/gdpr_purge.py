"""
RGPD — Purge des comptes en attente de suppression.

Cycle de vie d'un compte supprimé par l'admin :
  1. Admin clique "Supprimer" → account_status = 'pending_deletion', deleted_at = now()
  2. Le compte est immédiatement bloqué (login refusé, profil masqué)
  3. Après DELETION_DELAY_DAYS (30j), le job nuit anonymise les données PII
  4. account_status passe à 'deleted', les données personnelles sont effacées

Le job /purge-now (route admin uniquement) court-circuite le délai — utile en test
et pour les cas urgents (CNIL, plainte utilisateur).
"""

import uuid
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

DELETION_DELAY_DAYS = 30


def anonymize_user(user, db) -> None:
    """
    Remplace toutes les PII par des valeurs anonymes et marque le compte 'deleted'.
    L'enregistrement est conservé pour l'intégrité référentielle (tracks, paiements).
    """
    token = uuid.uuid4().hex[:10]

    user.email               = f'supprime_{user.id}_{token}@laprod-deleted.fr'
    user.username            = f'utilisateur_supprime_{user.id}'
    user.signature           = None
    user.bio                 = None
    user.profile_image       = 'images/default_profile.png'
    user.profile_picture_url = None

    # OAuth
    user.google_id      = None
    user.oauth_provider = None

    # Réseaux sociaux
    user.instagram  = None
    user.twitter    = None
    user.youtube    = None
    user.soundcloud = None

    # Statut final
    user.account_status = 'deleted'

    db.session.commit()
    logger.info(f'[RGPD] Compte #{user.id} anonymisé (purge RGPD).')


def run_gdpr_purge_job(app) -> None:
    """
    Job APScheduler — à lancer chaque nuit à 4h.
    Anonymise tous les comptes dont deleted_at > DELETION_DELAY_DAYS.
    """
    with app.app_context():
        from extensions import db
        from models import User

        cutoff = datetime.now(timezone.utc) - timedelta(days=DELETION_DELAY_DAYS)

        pending = (
            db.session.query(User)
            .filter(
                User.account_status == 'pending_deletion',
                User.deleted_at.isnot(None),
                User.deleted_at <= cutoff,
            )
            .all()
        )

        if not pending:
            logger.debug('[RGPD] Aucun compte à purger.')
            return

        for user in pending:
            try:
                anonymize_user(user, db)
            except Exception as e:
                logger.error(f'[RGPD] Erreur purge compte #{user.id} : {e}')

        logger.info(f'[RGPD] {len(pending)} compte(s) purgé(s).')
