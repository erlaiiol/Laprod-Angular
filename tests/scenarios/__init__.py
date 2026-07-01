"""
Scénarios de test nommés — couche 2 de la bibliothèque de données de référence.

Chaque fixture représente un cas métier stable et documenté. Ils dépendent
de `bound_factories` (qui lie les factories à la session SQLAlchemy de test).

Catalogue des scénarios disponibles :

  users.py :
    user_free              → plan gratuit, is_premium_active=False
    user_amateur           → plan amateur, is_premium_active=True (tokens intermédiaires)
    user_pro               → plan pro, is_premium_active=True (tokens max, stems, exclusives)
    user_premium_expired   → plan pro mais expiré, is_premium_active=False
    user_artist            → artiste pur (is_artist=True, pas beatmaker)
    user_pending           → onboarding OAuth incomplet
    user_admin             → administrateur plateforme
    user_mix_engineer_low_min    → ingénieur ref=100€, min=10€ (pas d'auto-force)
    user_mix_engineer_high_min   → ingénieur ref=100€, min=30€ (plancher élevé)
    user_mix_engineer_autoforce  → ingénieur ref=100€, min=35€ (auto-force cleaning)
    user_mix_engineer_mastering  → ingénieur certifié mastering, ref=150€
    user_mix_engineer_producer   → ingénieur certifié artistique, ref=200€
    user_stripe_ready            → ingénieur avec Stripe Connect complet

  tracks.py :
    track_default_prices   → approuvée, prix contrats = None (valeurs plateforme)
    track_custom_exclusive → prix d'exclusivité custom à 500€
    track_exclusive_sold   → is_exclusive_sold=True (410 GONE au checkout)
    track_high_price_mp3   → MP3=50€, WAV=100€, stems=150€ (seuils public_show)
    track_unapproved       → is_approved=False (masquée du catalogue public)
    track_with_files       → file_mp3 + file_wav définis (prête au téléchargement)
    track_sacem_min        → sacem_percentage_composer=0 (borne basse)
    track_sacem_max        → sacem_percentage_composer=85 (borne haute)

  mixmaster_orders.py :
    order_awaiting, order_accepted, order_delivered,
    order_revision1, order_revision2, order_completed,
    order_completed_after_rev1, order_rejected,
    order_expired, order_all_services

Utilisation dans un test :
    from tests.scenarios.users import user_pro
    from tests.scenarios.tracks import track_unapproved

    def test_unapproved_hidden(client, user_pro, track_unapproved):
        ...
"""


def _teardown_user(db, user):
    """
    Supprime un utilisateur et son wallet éventuel.
    Le wallet doit être supprimé en premier car la FK wallet.user_id → users.id
    n'a pas de CASCADE DELETE dans le schéma.
    """
    db.session.rollback()
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=user.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    existing = db.session.get(type(user), user.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()
