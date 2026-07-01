"""
Tests d'intégration — exclusivité track (routes/payment_track_api.py + admin_api.py)

Couvre :
  - Blocage du checkout si is_exclusive_sold=True  → 410
  - Marquage du track après un achat exclusif
  - API admin : filtre status='exclusive', exclusive_count, sérialisation track_admin
"""
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free  # noqa: F401
from tests.scenarios.tracks import track_default_prices, track_exclusive_sold  # noqa: F401


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture()
def buyer_headers(app, db):
    from models import User
    from flask_jwt_extended import create_access_token
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'buyer_excl_{uid}@test.laprod.fr',
        username=f'buyer_excl_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    with app.app_context():
        token = create_access_token(identity=str(u.id))
    yield {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, u
    db.session.rollback()
    from models import Purchase, Contract
    buyer_purchases = db.session.query(Purchase).filter_by(buyer_id=u.id).all()
    for bp in buyer_purchases:
        db.session.query(Contract).filter_by(purchase_id=bp.id).delete()
    db.session.query(Purchase).filter_by(buyer_id=u.id).delete()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


# ── Blocage checkout ──────────────────────────────────────────────────────────

class TestCheckoutBlockedOnExclusiveSold:

    def test_returns_410_for_track_exclusive_sold(self, client, track_exclusive_sold, buyer_headers):
        headers, _buyer = buyer_headers
        resp = client.post(
            f'/api/track-payment/track/{track_exclusive_sold.id}/mp3/checkout',
            data=json.dumps({'total_price': 9.99}),
            headers=headers,
        )
        assert resp.status_code == 410
        body = resp.json
        assert body['code'] == 'TRACK_EXCLUSIVE_SOLD'

    def test_track_default_prices_checkout_not_blocked(self, client, track_default_prices, buyer_headers):
        """Un track non exclusif ne retourne pas 410 (même si Stripe échoue)."""
        headers, _buyer = buyer_headers
        with patch('stripe.checkout.Session.create', side_effect=Exception('stripe mock')):
            resp = client.post(
                f'/api/track-payment/track/{track_default_prices.id}/mp3/checkout',
                data=json.dumps({'total_price': 9.99}),
                headers=headers,
            )
        assert resp.status_code != 410


# ── Marquage après achat exclusif ────────────────────────────────────────────

class TestExclusivePurchaseMarksTrack:

    def _build_fake_session(self, track, buyer, is_exclusive: bool, payment_intent_id: str):
        """Construit un objet simulant une session Stripe Checkout."""
        meta = {
            'track_id':                str(track.id),
            'track_title':             track.title,
            'composer_id':             str(track.composer_id),
            'composer_username':       'composer_excl',
            'buyer_id':                str(buyer.id),
            'buyer_username':          buyer.username,
            'format_type':             'mp3',
            'is_exclusive':            str(is_exclusive),
            'duration_years':          '3',
            'is_lifetime':             'False',
            'territory':               'France',
            'streaming':               'true',
            'mechanical_reproduction': 'False',
            'public_show':             'False',
            'arrangement':             'False',
            'buyer_address':           '',
            'buyer_email':             buyer.email,
            'track_price':             '9.99',
        }
        session = MagicMock()
        session.payment_intent = payment_intent_id
        session.metadata = meta

        intent = MagicMock()
        intent.status = 'succeeded'
        intent.amount = 999
        intent.metadata = meta

        return session, intent

    def test_exclusive_purchase_sets_is_exclusive_sold(
        self, client, db, app, track_default_prices, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_fake_session(
            track_default_prices, buyer, is_exclusive=True, payment_intent_id=pi_id
        )

        _route = 'routes.payment_track_api'
        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve', return_value=intent), \
             patch('utils.notification_service.notify_exclusive_sold'), \
             patch('utils.email_service.send_exclusive_sold_email'), \
             patch(f'{_route}.notify_purchase_confirmed'), \
             patch(f'{_route}.notify_sale_completed'), \
             patch(f'{_route}.credit_wallet_for_beat_sale'), \
             patch(f'{_route}.send_purchase_confirmation_email'), \
             patch(f'{_route}.send_sale_notification_email'), \
             patch('utils.contract_generator.generate_contract_pdf'):
            resp = client.post(
                '/api/track-payment/verify',
                data=json.dumps({'session_id': 'cs_test_dummy'}),
                headers=headers,
            )

        assert resp.status_code == 200

        from models import Track
        db.session.expire(track_default_prices)
        refreshed = db.session.get(Track, track_default_prices.id)
        assert refreshed.is_exclusive_sold is True
        assert refreshed.exclusive_buyer_id == buyer.id
        assert refreshed.exclusive_sold_at is not None

    def test_non_exclusive_purchase_does_not_mark_track(
        self, client, db, app, track_default_prices, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_fake_session(
            track_default_prices, buyer, is_exclusive=False, payment_intent_id=pi_id
        )

        _route = 'routes.payment_track_api'
        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve', return_value=intent), \
             patch(f'{_route}.notify_purchase_confirmed'), \
             patch(f'{_route}.notify_sale_completed'), \
             patch(f'{_route}.credit_wallet_for_beat_sale'), \
             patch(f'{_route}.send_purchase_confirmation_email'), \
             patch(f'{_route}.send_sale_notification_email'), \
             patch('utils.contract_generator.generate_contract_pdf'):
            resp = client.post(
                '/api/track-payment/verify',
                data=json.dumps({'session_id': 'cs_test_dummy'}),
                headers=headers,
            )

        assert resp.status_code == 200

        from models import Track
        db.session.expire(track_default_prices)
        refreshed = db.session.get(Track, track_default_prices.id)
        assert refreshed.is_exclusive_sold is False


# ── Race condition exclusive ──────────────────────────────────────────────────

class TestExclusiveRaceCondition:
    """
    Scénario : deux acheteurs obtiennent chacun une session Stripe pour le même
    track exclusif AVANT que l'un d'eux ne vérifie son paiement.
    Le premier verify réussit et marque le track comme vendu.
    Le second verify DOIT retourner 409 — pas créer un deuxième Purchase.
    """

    def _build_session(self, track, buyer, pi_id: str):
        meta = {
            'track_id':                str(track.id),
            'track_title':             track.title,
            'composer_id':             str(track.composer_id),
            'composer_username':       'composer_excl',
            'buyer_id':                str(buyer.id),
            'buyer_username':          buyer.username,
            'format_type':             'mp3',
            'is_exclusive':            'True',
            'duration_years':          '3',
            'is_lifetime':             'False',
            'territory':               'France',
            'streaming':               'true',
            'mechanical_reproduction': 'False',
            'public_show':             'False',
            'arrangement':             'False',
            'buyer_address':           '',
            'buyer_email':             buyer.email,
            'track_price':             '9.99',
        }
        session = MagicMock()
        session.payment_intent = pi_id
        session.metadata = meta

        intent = MagicMock()
        intent.status = 'succeeded'
        intent.amount = 999
        intent.metadata = meta
        return session, intent

    def test_second_exclusive_verify_returns_409(
        self, client, db, app, track_default_prices, buyer_headers
    ):
        """
        Buyer A et Buyer B ont tous les deux obtenu une session Stripe exclusive.
        Buyer A vérifie en premier → succès.
        Buyer B vérifie ensuite → 409 TRACK_EXCLUSIVE_SOLD (et aucun Purchase créé).
        """
        from models import User, Purchase
        from flask_jwt_extended import create_access_token

        # Créer Buyer B
        uid = uuid.uuid4().hex[:8]
        buyer_b = User(
            email=f'buyer_b_{uid}@test.laprod.fr',
            username=f'buyer_b_{uid}',
            email_verified=True,
            account_status='active',
            user_type_selected=True,
        )
        buyer_b.set_password('Pass123!')
        db.session.add(buyer_b)
        db.session.commit()

        with app.app_context():
            token_b = create_access_token(identity=str(buyer_b.id))
        headers_b = {'Authorization': f'Bearer {token_b}', 'Content-Type': 'application/json'}

        headers_a, buyer_a = buyer_headers
        pi_a = f'pi_excl_a_{uuid.uuid4().hex[:8]}'
        pi_b = f'pi_excl_b_{uuid.uuid4().hex[:8]}'

        session_a, intent_a = self._build_session(track_default_prices, buyer_a, pi_a)
        session_b, intent_b = self._build_session(track_default_prices, buyer_b, pi_b)

        _route = 'routes.payment_track_api'

        # Buyer A vérifie en premier
        with patch('stripe.checkout.Session.retrieve', return_value=session_a), \
             patch('stripe.PaymentIntent.retrieve',    return_value=intent_a), \
             patch('utils.notification_service.notify_exclusive_sold'), \
             patch('utils.email_service.send_exclusive_sold_email'), \
             patch('utils.contract_generator.generate_contract_pdf'), \
             patch(f'{_route}.credit_wallet_for_beat_sale'), \
             patch(f'{_route}.notify_purchase_confirmed'), \
             patch(f'{_route}.notify_sale_completed'), \
             patch(f'{_route}.send_purchase_confirmation_email'), \
             patch(f'{_route}.send_sale_notification_email'):
            resp_a = client.post(
                '/api/track-payment/verify',
                data=json.dumps({'session_id': 'cs_buyer_a'}),
                headers=headers_a,
            )

        assert resp_a.status_code == 200

        # Buyer B vérifie ensuite — le track est déjà marqué comme vendu
        with patch('stripe.checkout.Session.retrieve', return_value=session_b), \
             patch('stripe.PaymentIntent.retrieve',    return_value=intent_b), \
             patch('utils.contract_generator.generate_contract_pdf'), \
             patch(f'{_route}.notify_purchase_confirmed'), \
             patch(f'{_route}.notify_sale_completed'), \
             patch(f'{_route}.send_purchase_confirmation_email'), \
             patch(f'{_route}.send_sale_notification_email'):
            resp_b = client.post(
                '/api/track-payment/verify',
                data=json.dumps({'session_id': 'cs_buyer_b'}),
                headers=headers_b,
            )

        assert resp_b.status_code == 409
        assert resp_b.json['code'] == 'TRACK_EXCLUSIVE_SOLD'

        # Aucun Purchase pour Buyer B ne doit exister
        count_b = db.session.query(Purchase).filter_by(
            buyer_id=buyer_b.id, track_id=track_default_prices.id
        ).count()
        assert count_b == 0, "Un Purchase ne doit pas être créé pour le second acheteur exclusif"

        # Nettoyage Buyer B
        db.session.rollback()
        existing = db.session.get(User, buyer_b.id)
        if existing:
            db.session.delete(existing)
        db.session.commit()


# ── Admin API — tracks exclusifs ──────────────────────────────────────────────

class TestAdminExclusiveTracks:
    """
    Vérifie que l'API admin expose correctement les tracks vendus en exclusivité.
    """

    def _admin_headers(self, app, db):
        from models import User
        from flask_jwt_extended import create_access_token
        uid = uuid.uuid4().hex[:8]
        u = User(
            email=f'admin_excl_{uid}@test.laprod.fr',
            username=f'admin_excl_{uid}',
            email_verified=True,
            account_status='active',
            user_type_selected=True,
            is_admin=True,
        )
        u.set_password('Pass123!')
        db.session.add(u)
        db.session.commit()
        with app.app_context():
            token = create_access_token(identity=str(u.id))
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, u

    def test_exclusive_filter_returns_only_exclusive_tracks(
        self, client, app, db, track_exclusive_sold
    ):
        """status='exclusive' ne retourne que les tracks is_exclusive_sold=True."""
        headers, admin = self._admin_headers(app, db)
        try:
            resp = client.get('/api/admin/tracks?status=exclusive', headers=headers)
            assert resp.status_code == 200
            body = resp.json
            assert body['success'] is True
            ids = [t['id'] for t in body['data']['tracks']]
            assert track_exclusive_sold.id in ids
        finally:
            db.session.rollback()
            from models import User
            existing = db.session.get(User, admin.id)
            if existing:
                db.session.delete(existing)
            db.session.commit()

    def test_exclusive_filter_excludes_non_exclusive_tracks(
        self, client, app, db, track_default_prices
    ):
        """status='exclusive' n'inclut pas les tracks non exclusivement vendus."""
        headers, admin = self._admin_headers(app, db)
        try:
            resp = client.get('/api/admin/tracks?status=exclusive', headers=headers)
            assert resp.status_code == 200
            ids = [t['id'] for t in resp.json['data']['tracks']]
            assert track_default_prices.id not in ids
        finally:
            db.session.rollback()
            from models import User
            existing = db.session.get(User, admin.id)
            if existing:
                db.session.delete(existing)
            db.session.commit()

    def test_response_includes_exclusive_count(self, client, app, db, track_exclusive_sold):
        """La réponse admin tracks inclut toujours exclusive_count."""
        headers, admin = self._admin_headers(app, db)
        try:
            resp = client.get('/api/admin/tracks?status=pending', headers=headers)
            assert resp.status_code == 200
            assert 'exclusive_count' in resp.json['data']
            assert resp.json['data']['exclusive_count'] >= 1
        finally:
            db.session.rollback()
            from models import User
            existing = db.session.get(User, admin.id)
            if existing:
                db.session.delete(existing)
            db.session.commit()

    def test_track_admin_serializer_includes_exclusive_fields(
        self, client, app, db, track_exclusive_sold
    ):
        """track_admin() expose is_exclusive_sold, exclusive_sold_at, exclusive_buyer."""
        headers, admin = self._admin_headers(app, db)
        try:
            resp = client.get('/api/admin/tracks?status=exclusive', headers=headers)
            assert resp.status_code == 200
            tracks = resp.json['data']['tracks']
            t = next((x for x in tracks if x['id'] == track_exclusive_sold.id), None)
            assert t is not None
            assert t['is_exclusive_sold'] is True
            assert 'exclusive_sold_at' in t
            assert 'exclusive_buyer' in t
        finally:
            db.session.rollback()
            from models import User
            existing = db.session.get(User, admin.id)
            if existing:
                db.session.delete(existing)
            db.session.commit()

    def test_non_admin_cannot_access_admin_tracks(self, client, app, db):
        """Un utilisateur non admin ne peut pas accéder à /api/admin/tracks."""
        from models import User
        from flask_jwt_extended import create_access_token
        uid = uuid.uuid4().hex[:8]
        u = User(
            email=f'nonadmin_{uid}@test.laprod.fr',
            username=f'nonadmin_{uid}',
            email_verified=True,
            account_status='active',
            user_type_selected=True,
        )
        u.set_password('Pass123!')
        db.session.add(u)
        db.session.commit()
        with app.app_context():
            token = create_access_token(identity=str(u.id))
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        try:
            resp = client.get('/api/admin/tracks?status=exclusive', headers=headers)
            assert resp.status_code == 403
        finally:
            db.session.rollback()
            existing = db.session.get(User, u.id)
            if existing:
                db.session.delete(existing)
            db.session.commit()
