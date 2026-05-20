"""
Tests d'intégration — exclusivité track (routes/payment_track_api.py)

Couvre :
  - Blocage du checkout si is_exclusive_sold=True  → 410
  - Marquage du track après un achat exclusif
"""
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def composer(db):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'composer_excl_{uid}@test.laprod.fr',
        username=f'composer_excl_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    db.session.rollback()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def available_track(db, composer):
    from models import Track
    t = Track(
        title='Available Beat',
        composer_id=composer.id,
        file_hash=str(uuid.uuid4()),
        audio_file='avail_preview.mp3',
        bpm=140,
        key='D minor',
        is_approved=True,
        is_exclusive_sold=False,
        price_mp3=Decimal('9.99'),
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    from models import Purchase
    db.session.query(Purchase).filter_by(track_id=t.id).delete()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def exclusive_sold_track(db, composer):
    from models import Track
    t = Track(
        title='Sold Exclusive Beat',
        composer_id=composer.id,
        file_hash=str(uuid.uuid4()),
        audio_file='sold_preview.mp3',
        bpm=140,
        key='D minor',
        is_approved=True,
        is_exclusive_sold=True,
        price_mp3=Decimal('9.99'),
    )
    db.session.add(t)
    db.session.commit()
    yield t
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


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
    from models import Purchase
    db.session.query(Purchase).filter_by(buyer_id=u.id).delete()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


# ── Blocage checkout ──────────────────────────────────────────────────────────

class TestCheckoutBlockedOnExclusiveSold:

    def test_returns_410_for_exclusive_sold_track(self, client, exclusive_sold_track, buyer_headers):
        headers, _buyer = buyer_headers
        resp = client.post(
            f'/api/track-payment/track/{exclusive_sold_track.id}/mp3/checkout',
            data=json.dumps({'total_price': 9.99}),
            headers=headers,
        )
        assert resp.status_code == 410
        body = resp.json
        assert body['code'] == 'TRACK_EXCLUSIVE_SOLD'

    def test_available_track_checkout_not_blocked(self, client, available_track, buyer_headers):
        """Un track non exclusif ne retourne pas 410 (même si Stripe échoue)."""
        headers, _buyer = buyer_headers
        with patch('stripe.checkout.Session.create', side_effect=Exception('stripe mock')):
            resp = client.post(
                f'/api/track-payment/track/{available_track.id}/mp3/checkout',
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
        self, client, db, app, available_track, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_fake_session(
            available_track, buyer, is_exclusive=True, payment_intent_id=pi_id
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
        db.session.expire(available_track)
        refreshed = db.session.get(Track, available_track.id)
        assert refreshed.is_exclusive_sold is True
        assert refreshed.exclusive_buyer_id == buyer.id
        assert refreshed.exclusive_sold_at is not None

    def test_non_exclusive_purchase_does_not_mark_track(
        self, client, db, app, available_track, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_fake_session(
            available_track, buyer, is_exclusive=False, payment_intent_id=pi_id
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
        db.session.expire(available_track)
        refreshed = db.session.get(Track, available_track.id)
        assert refreshed.is_exclusive_sold is False
