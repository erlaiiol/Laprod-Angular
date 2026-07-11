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

import os
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

DELETION_DELAY_DAYS = 30


def _safe_delete_pdf(filename: str, base_dir) -> None:
    """
    Supprime un PDF sur disque en garantissant qu'il reste confiné dans base_dir
    (défense en profondeur contre un champ DB manipulé). No-op si absent/hors zone.
    """
    if not filename:
        return
    try:
        base = Path(base_dir).resolve()
        target = (base / filename).resolve()
        if not target.is_relative_to(base):
            logger.warning(f'[RGPD] Suppression PDF hors zone ignorée : {filename!r}')
            return
        if target.exists():
            target.unlink()
    except OSError as e:
        logger.error(f'[RGPD] Échec suppression PDF {filename!r} : {e}')


def _purge_related_pii(user, db) -> None:
    """
    Efface les PII de l'utilisateur disséminées hors de la table User :
    contrats de tracks, contrats builder + parties, nom d'acheteur, et les PDF
    correspondants sur disque. Conserve les lignes pour l'intégrité référentielle.
    """
    import config
    from models import Purchase, Contract, UserContract

    # ── Achats : nom d'acheteur + PDF contrat associé ────────────────────────
    for purchase in db.session.query(Purchase).filter(Purchase.buyer_id == user.id).all():
        purchase.buyer_name = 'Acheteur supprimé'
        _safe_delete_pdf(purchase.contract_file, config.CONTRACTS_FOLDER)
        purchase.contract_file = None

    # ── Contrats de tracks : PII compositeur et/ou client + PDF ──────────────
    contracts = db.session.query(Contract).filter(
        (Contract.composer_id == user.id) | (Contract.client_id == user.id)
    ).all()
    for contract in contracts:
        if contract.composer_id == user.id:
            contract.composer_email   = None
            contract.composer_address = None
        if contract.client_id == user.id:
            contract.client_email   = None
            contract.client_address = None
        _safe_delete_pdf(contract.contract_file, config.CONTRACTS_FOLDER)
        contract.contract_file = None

    # ── Contrats builder : parties (état civil, adresse, email) + PDF ─────────
    builder_dir = config.CONTRACTS_FOLDER / 'builder'
    for uc in db.session.query(UserContract).filter(UserContract.user_id == user.id).all():
        for party in uc.parties:
            party.first_name    = None
            party.last_name     = None
            party.date_of_birth = None
            party.nationality   = None
            party.pseudonym     = None
            party.tax_id        = None
            party.address       = None
            party.email         = None
            party.legal_rep     = None
        _safe_delete_pdf(uc.pdf_file, builder_dir)
        uc.pdf_file = None


def anonymize_user(user, db) -> None:
    """
    Remplace toutes les PII par des valeurs anonymes et marque le compte 'deleted'.
    L'enregistrement est conservé pour l'intégrité référentielle (tracks, paiements).
    Efface aussi les PII liées hors table User (contrats, parties, PDF disque).
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

    # PII disséminées hors table User (contrats, parties, PDF)
    _purge_related_pii(user, db)

    # Statut final
    user.account_status = 'deleted'

    db.session.commit()
    logger.info(f'[RGPD] Compte #{user.id} anonymisé (purge RGPD, PII liées incluses).')


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
