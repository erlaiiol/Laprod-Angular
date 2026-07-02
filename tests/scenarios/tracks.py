"""
Scénarios de tracks nommés.

Les fixtures nécessitent un `composer` — à fournir via une fixture locale dans
le fichier de test, ou via un scénario utilisateur (user_free, user_pro, etc.).

Catalogue :
  track_default_prices   → approuvée, prix contrats = None (valeurs plateforme)
  track_custom_exclusive → prix d'exclusivité custom à 500€
  track_exclusive_sold   → exclusivité déjà vendue (is_exclusive_sold=True)
  track_high_price_mp3   → MP3=50€, WAV=100€, stems=150€ (seuils public_show)
  track_unapproved       → en attente d'approbation admin (is_approved=False)
  track_with_files       → fichiers complets disponibles (file_mp3 + file_wav)
  track_sacem_min        → sacem_percentage_composer=0 (limite basse)
  track_sacem_max        → sacem_percentage_composer=85 (limite haute)

Exemple :
    def test_checkout(db, bound_factories, user_free, track_default_prices):
        ...
"""

from decimal import Decimal
import uuid
import pytest


def _make_track(db, composer_id, **overrides):
    """Helper interne : crée et retourne un Track avec les overrides donnés."""
    from tests.factories.track_factory import TrackFactory
    return TrackFactory(composer_id=composer_id, **overrides)


def _teardown_track(db, track):
    """Supprime un track proprement en retirant d'abord les achats liés (pas de CASCADE)."""
    db.session.rollback()
    from models import Purchase, Topline
    db.session.query(Topline).filter_by(track_id=track.id).delete()
    db.session.query(Purchase).filter_by(track_id=track.id).delete()
    existing = db.session.get(type(track), track.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def track_default_prices(db, bound_factories, user_free):
    """Track approuvée avec tous les prix de contrat à None.
    → La plateforme utilise ses valeurs par défaut (config.py).
    C'est le scénario le plus courant pour les tests de checkout et serializers."""
    t = _make_track(db, user_free.id)
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_custom_exclusive(db, bound_factories, user_free):
    """Track avec un prix d'exclusivité personnalisé à 500€.
    Utilisé pour tester que le prix custom override le prix plateforme."""
    t = _make_track(db, user_free.id, contract_price_exclusive=500)
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_exclusive_sold(db, bound_factories, user_free):
    """Track dont l'exclusivité a déjà été vendue (is_exclusive_sold=True).
    → La caisse doit retourner 410 GONE pour une tentative d'achat exclusive."""
    t = _make_track(db, user_free.id, is_exclusive_sold=True)
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_high_price_mp3(db, bound_factories, user_free):
    """Track avec price_mp3=50€.
    Couvre le bug fix public_show auto-inclus :
      base=50, mécanique=30 → subtotalWithMechanical=80 ≥ 74.99
      → publicShowAutoIncluded=True côté Angular.
    Aussi utile pour tester les seuils de prix côté backend."""
    t = _make_track(db, user_free.id, price_mp3=Decimal('50.00'),
                    price_wav=Decimal('100.00'), price_stems=Decimal('150.00'))
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_unapproved(db, bound_factories, user_free):
    """Track en attente d'approbation admin (is_approved=False).
    → Les endpoints publics doivent la masquer ou retourner 404/403.
    Utilisé pour tester le workflow d'approbation et les gardes d'accès."""
    t = _make_track(db, user_free.id, is_approved=False)
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_with_files(db, bound_factories, user_free):
    """Track approuvée avec fichiers complets disponibles à la vente.
    file_mp3 et file_wav sont définis — simule une track prête au téléchargement
    post-achat. Utilisé pour tester les routes de téléchargement et le checkout."""
    t = _make_track(
        db, user_free.id,
        file_mp3='audio/tracks/test_beat_full.mp3',
        file_wav='audio/tracks/test_beat_full.wav',
    )
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_sacem_min(db, bound_factories, user_free):
    """Track avec sacem_percentage_composer=0 (limite basse valide).
    → 0% compositeur, 100% acheteur/interprète.
    Utilisé pour tester les calculs SACEM aux bornes."""
    t = _make_track(db, user_free.id, sacem_percentage_composer=0)
    yield t
    _teardown_track(db, t)


@pytest.fixture()
def track_sacem_max(db, bound_factories, user_free):
    """Track avec sacem_percentage_composer=85 (limite haute valide).
    → 85% compositeur, 15% acheteur/interprète.
    Utilisé pour tester les calculs SACEM aux bornes."""
    t = _make_track(db, user_free.id, sacem_percentage_composer=85)
    yield t
    _teardown_track(db, t)
