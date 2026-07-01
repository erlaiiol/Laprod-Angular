"""
Scénarios de test nommés — couche 2 de la bibliothèque de données de référence.

Chaque fixture représente un cas métier stable et documenté. Ils dépendent
de `bound_factories` (qui lie les factories à la session SQLAlchemy de test).

Catalogue des scénarios disponibles :
  users.py          → user_free, user_pro, user_artist, user_pending,
                       user_admin, user_mix_engineer_low_min,
                       user_mix_engineer_high_min, user_mix_engineer_mastering,
                       user_mix_engineer_producer, user_stripe_ready
  tracks.py         → track_default_prices, track_custom_exclusive,
                       track_exclusive_sold, track_high_price_mp3
  mixmaster_orders.py → order_awaiting, order_accepted, order_delivered,
                         order_revision1, order_revision2, order_completed,
                         order_completed_after_rev1, order_rejected,
                         order_expired, order_all_services

Utilisation dans un test :
    from tests.scenarios.users import user_mix_engineer_low_min

    def test_pricing(client, user_mix_engineer_low_min, artist_headers):
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
