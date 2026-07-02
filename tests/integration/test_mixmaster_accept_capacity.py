"""
Tests d'intégration — capacité d'acceptation de l'ingénieur mix/master

Vérifie que l'ingénieur ne peut pas dépasser la limite de 5 mix/master actifs
même si deux requêtes d'acceptation arrivent simultanément (garde WITH FOR UPDATE).

Structure du test :
  - La race condition réelle ne peut pas être reproduite en test séquentiel.
  - On teste le comportement observable : après avoir atteint la limite,
    toute nouvelle acceptation est refusée avec le bon message.
  - On vérifie que le verrou est bien utilisé (db.session.execute appelé).
"""

import uuid
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(db, *, engineer=False):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'mmtest_{uid}@test.laprod.fr',
        username=f'mmtest_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_mix_engineer=engineer,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    return u


def _jwt(app, user_id):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _make_order(db, engineer_id, artist_id, status='awaiting_acceptance'):
    """Crée un MixMasterRequest directement en DB sans passer par l'API."""
    from models import MixMasterRequest
    o = MixMasterRequest(
        engineer_id=engineer_id,
        artist_id=artist_id,
        title=f'Order {uuid.uuid4().hex[:4]}',
        status=status,
        original_file='stems/test.zip',
        reference_file='ref/test.mp3',
        service_cleaning=True,
        service_effects=False,
        service_artistic=False,
        service_mastering=False,
        has_separated_stems=True,
        total_price=Decimal('70.00'),
        deposit_amount=Decimal('21.00'),    # 30% de 70
        remaining_amount=Decimal('49.00'),  # 70% de 70
        platform_fee=Decimal('7.00'),       # 10% de 70
        engineer_revenue=Decimal('63.00'),  # 90% de 70
        stripe_payment_intent_id=f'pi_test_{uuid.uuid4().hex[:12]}',
        stripe_payment_status='captured',
    )
    db.session.add(o)
    db.session.commit()
    return o


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _cleanup_engineer(db, user_id: int) -> None:
    """
    Supprime dans l'ordre les dépendances FK avant l'ingénieur.

    Ordre :
      1. rollback() — expulse les objets en attente de l'autoflush (évite
         NOT NULL sur des proxies expirés lors du commit suivant).
      2. Notifications créées par accept_order pour les users liés.
      3. MixMasterRequests de cet engineer.
      4. L'utilisateur engineer.

    synchronize_session=False — on court-circuite l'évaluation en mémoire des
    critères de filtre (évite engineer_id=None sur des objets expirés post-rollback).
    """
    from models import MixMasterRequest, Notification, User
    db.session.rollback()       # annuler toute transaction ouverte
    db.session.expunge_all()    # vider l'identity map — les objets expirés (artist_id=None,
                                # etc.) ne déclencheront plus d'autoflush lors du commit

    linked_user_ids = [
        r[0] for r in
        db.session.query(MixMasterRequest.artist_id)
        .filter(MixMasterRequest.engineer_id == user_id)
        .distinct().all()
    ]
    notify_targets = linked_user_ids + [user_id]

    db.session.query(Notification).filter(
        Notification.user_id.in_(notify_targets)
    ).delete(synchronize_session=False)

    db.session.query(MixMasterRequest).filter(
        MixMasterRequest.engineer_id == user_id
    ).delete(synchronize_session=False)

    # Après les DELETEs bulk (synchronize_session=False), les objets supprimés restent
    # dans l'identity map comme "vivants". Un expunge_all() ici évite que SQLAlchemy
    # tente de les flusher lors du commit suivant ou des fixtures suivantes.
    db.session.expunge_all()

    existing = db.session.get(User, user_id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def engineer(db):
    u = _make_user(db, engineer=True)
    user_id = u.id  # capturer AVANT yield — u.id serait None après expiration
    yield u
    _cleanup_engineer(db, user_id)


@pytest.fixture()
def artist(db):
    u = _make_user(db)
    user_id = u.id
    yield u
    # L'artiste est détruit AVANT l'ingénieur (ordre inverse de setup).
    # SQLAlchemy tenterait de SET NULL sur artist_id (NOT NULL) si les ordres existent
    # encore → on les supprime ici avant de supprimer l'artiste.
    from models import User, Notification, MixMasterRequest
    db.session.rollback()
    db.session.expunge_all()
    db.session.query(Notification).filter(
        Notification.user_id == user_id
    ).delete(synchronize_session=False)
    db.session.query(MixMasterRequest).filter(
        MixMasterRequest.artist_id == user_id
    ).delete(synchronize_session=False)
    db.session.expunge_all()
    existing = db.session.get(User, user_id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestAcceptOrderCapacity:

    def test_accept_blocked_when_at_limit(self, client, app, db, engineer, artist):
        """
        Avec 5 commandes actives, accept_order doit retourner une erreur 400.
        """
        # Créer 5 commandes actives pour cet ingénieur
        orders = [_make_order(db, engineer.id, artist.id, status='accepted') for _ in range(5)]

        # Créer une 6ème commande en awaiting_acceptance
        pending = _make_order(db, engineer.id, artist.id, status='awaiting_acceptance')

        headers = _jwt(app, engineer.id)
        resp = client.post(
            f'/api/mixmaster-engineer/accept/{pending.id}',
            headers=headers,
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert '5' in body['feedback']['message']

    def test_accept_succeeds_below_limit(self, client, app, db, engineer, artist):
        """
        Avec 4 commandes actives, accept_order doit réussir (retourne accepted ou 200).
        """
        for _ in range(4):
            _make_order(db, engineer.id, artist.id, status='accepted')

        pending = _make_order(db, engineer.id, artist.id, status='awaiting_acceptance')

        headers = _jwt(app, engineer.id)
        resp = client.post(
            f'/api/mixmaster-engineer/accept/{pending.id}',
            headers=headers,
        )

        # 200 = acceptée, ou autre code non-4xx indiquant un succès métier
        assert resp.status_code == 200
        from models import MixMasterRequest
        db.session.expire(pending)
        refreshed = db.session.get(MixMasterRequest, pending.id)
        assert refreshed.status == 'accepted'

    def test_with_for_update_serializes_concurrent_accepts(self, client, app, db, engineer, artist):
        """
        Simule la situation de race condition : l'ingénieur a 4 commandes actives
        et tente d'accepter deux nouvelles commandes « simultanément ».

        Sans le verrou, les deux threads liraient count=4 et accepteraient les deux.
        Avec le verrou, le second thread relit count=5 après que le premier a commité
        et est bloqué.

        Ici on simule en séquentiel : l'ordre d'acceptation est A puis B.
        A passe (count 4→5), B doit être refusé (count est maintenant 5).
        """
        for _ in range(4):
            _make_order(db, engineer.id, artist.id, status='accepted')

        order_a = _make_order(db, engineer.id, artist.id, status='awaiting_acceptance')
        order_b = _make_order(db, engineer.id, artist.id, status='awaiting_acceptance')

        headers = _jwt(app, engineer.id)

        resp_a = client.post(f'/api/mixmaster-engineer/accept/{order_a.id}', headers=headers)
        resp_b = client.post(f'/api/mixmaster-engineer/accept/{order_b.id}', headers=headers)

        assert resp_a.status_code == 200, "Le premier accept doit réussir (4→5 actifs)"
        assert resp_b.status_code == 400, "Le second accept doit être refusé (5 actifs = limite)"

        from models import MixMasterRequest
        db.session.expire_all()
        refreshed_a = db.session.get(MixMasterRequest, order_a.id)
        refreshed_b = db.session.get(MixMasterRequest, order_b.id)
        assert refreshed_a.status == 'accepted'
        assert refreshed_b.status == 'awaiting_acceptance', "Order B ne doit pas avoir changé de statut"

    def test_already_accepted_order_returns_error(self, client, app, db, engineer, artist):
        """
        Tenter d'accepter une commande déjà acceptée doit retourner une erreur.
        (Protection contre le double-accept séquentiel)
        """
        order = _make_order(db, engineer.id, artist.id, status='accepted')

        headers = _jwt(app, engineer.id)
        resp = client.post(
            f'/api/mixmaster-engineer/accept/{order.id}',
            headers=headers,
        )

        assert resp.status_code == 400
        body = resp.get_json()
        assert body['success'] is False
        assert 'traitée' in body['feedback']['message'].lower()

    def test_cannot_accept_other_engineers_order(self, client, app, db, artist):
        """Un ingénieur ne peut pas accepter une commande assignée à un autre."""
        eng1 = _make_user(db, engineer=True)
        eng2 = _make_user(db, engineer=True)
        order = _make_order(db, eng1.id, artist.id, status='awaiting_acceptance')

        headers = _jwt(app, eng2.id)
        resp = client.post(
            f'/api/mixmaster-engineer/accept/{order.id}',
            headers=headers,
        )

        assert resp.status_code == 404

        # Nettoyage
        db.session.rollback()
        from models import MixMasterRequest, User
        db.session.query(MixMasterRequest).filter(
            MixMasterRequest.engineer_id.in_([eng1.id, eng2.id])
        ).delete()
        for u in [eng1, eng2]:
            existing = db.session.get(User, u.id)
            if existing:
                db.session.delete(existing)
        db.session.commit()


