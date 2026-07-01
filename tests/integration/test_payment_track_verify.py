"""
Tests d'intégration — POST /api/track-payment/verify

Couvre les cas d'erreur et de validation du endpoint de vérification de paiement :
  - session_id manquant → 400
  - paiement non confirmé (statut Stripe ≠ 'succeeded') → 400
  - acheteur JWT ≠ metadata buyer_id → 403
  - idempotence : achat déjà créé → 200 sans doublon
  - succès : Purchase créé, wallet crédité

Les tests qui vérifient la création complète du Purchase (avec génération PDF,
marquage exclusif, etc.) sont dans test_payment_track_exclusive.py.
"""
import json
import uuid
import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free  # noqa: F401


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture()
def track(db, user_free):
    from models import Track
    t = Track(
        title='Verify Test Beat',
        composer_id=user_free.id,
        file_hash=str(uuid.uuid4()),
        audio_file='verify_preview.mp3',
        bpm=140,
        key='A minor',
        is_approved=True,
        is_exclusive_sold=False,
        price_mp3=Decimal('14.99'),
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    from models import Purchase, Contract
    track_purchases = db.session.query(Purchase).filter_by(track_id=t.id).all()
    for tp in track_purchases:
        db.session.query(Contract).filter_by(purchase_id=tp.id).delete()
    db.session.query(Contract).filter_by(track_id=t.id).delete()
    db.session.query(Purchase).filter_by(track_id=t.id).delete()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def buyer_data(app, db):
    """Retourne (headers, user) pour un acheteur valide."""
    from models import User
    from flask_jwt_extended import create_access_token
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'buyer_vrf_{uid}@test.laprod.fr',
        username=f'buyer_vrf_{uid}',
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
    yield headers, u
    db.session.rollback()
    from models import Purchase, Contract, Wallet
    buyer_purchases = db.session.query(Purchase).filter_by(buyer_id=u.id).all()
    for bp in buyer_purchases:
        db.session.query(Contract).filter_by(purchase_id=bp.id).delete()
    db.session.query(Purchase).filter_by(buyer_id=u.id).delete()
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


def _make_stripe_session(meta: dict, pi_status='succeeded', pi_id='pi_test_xxx'):
    """Construit un mock de stripe.checkout.Session."""
    session = MagicMock()
    session.payment_intent = pi_id
    session.metadata       = meta

    pi = MagicMock()
    pi.status   = pi_status
    pi.amount   = int(float(meta.get('track_price', '14.99')) * 100)
    pi.metadata = meta

    return session, pi


# ── Tests — validation des entrées ────────────────────────────────────────────

class TestVerifyPaymentInputValidation:

    def test_requires_authentication(self, client):
        resp = client.post('/api/track-payment/verify', json={'session_id': 'cs_test'})
        assert resp.status_code == 401

    def test_missing_session_id_returns_400(self, client, buyer_data):
        headers, _ = buyer_data
        resp = client.post('/api/track-payment/verify', headers=headers, json={})
        assert resp.status_code == 400
        assert json.loads(resp.data)['code'] == 'MISSING_SESSION'

    def test_empty_session_id_returns_400(self, client, buyer_data):
        headers, _ = buyer_data
        resp = client.post('/api/track-payment/verify', headers=headers, json={'session_id': '  '})
        assert resp.status_code == 400

    def test_payment_not_succeeded_returns_400(self, client, buyer_data, track):
        """Un paiement avec statut 'requires_payment_method' → 400."""
        headers, buyer = buyer_data

        meta = {
            'track_id':       str(track.id),
            'buyer_id':       str(buyer.id),
            'format_type':    'mp3',
            'is_exclusive':   'False',
            'territory':      'France',
            'track_price':    '14.99',
            'duration_years': '3',
            'is_lifetime':    'False',
        }
        session, pi = _make_stripe_session(meta, pi_status='requires_payment_method')

        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve',    return_value=pi):
            resp = client.post(
                '/api/track-payment/verify',
                headers=headers,
                json={'session_id': 'cs_not_paid'},
            )

        assert resp.status_code == 400
        assert json.loads(resp.data)['code'] == 'PAYMENT_NOT_SUCCEEDED'

    def test_buyer_mismatch_returns_403(self, client, buyer_data, track):
        """L'acheteur JWT est différent du buyer_id en metadata → 403."""
        headers, buyer = buyer_data

        meta = {
            'track_id':       str(track.id),
            'buyer_id':       '999999',   # ← ne correspond pas au buyer JWT
            'format_type':    'mp3',
            'is_exclusive':   'False',
            'territory':      'France',
            'track_price':    '14.99',
            'duration_years': '3',
            'is_lifetime':    'False',
        }
        session, pi = _make_stripe_session(meta)

        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve',    return_value=pi):
            resp = client.post(
                '/api/track-payment/verify',
                headers=headers,
                json={'session_id': 'cs_mismatch'},
            )

        assert resp.status_code == 403
        assert json.loads(resp.data)['code'] == 'UNAUTHORIZED'

    def test_stripe_api_error_returns_502(self, client, buyer_data):
        """Si l'API Stripe est indisponible lors de la vérification → 502."""
        import stripe._error as stripe_error
        headers, _ = buyer_data

        with patch(
            'stripe.checkout.Session.retrieve',
            side_effect=stripe_error.APIConnectionError('Connection refused'),
        ):
            resp = client.post(
                '/api/track-payment/verify',
                headers=headers,
                json={'session_id': 'cs_stripe_down'},
            )

        assert resp.status_code == 502
        assert json.loads(resp.data)['code'] == 'STRIPE_ERROR'


# ── Tests — idempotence ───────────────────────────────────────────────────────

class TestVerifyPaymentIdempotence:

    def test_duplicate_verify_returns_existing_purchase(self, client, db, buyer_data, track):
        """
        Si un Purchase existe déjà pour ce payment_intent_id, la route retourne
        200 avec purchase_id sans en créer un deuxième.
        """
        from models import Purchase
        headers, buyer = buyer_data

        pi_id = f'pi_idempotent_{uuid.uuid4().hex[:8]}'

        # Créer un Purchase existant
        existing = Purchase(
            track_id=track.id,
            buyer_id=buyer.id,
            format_purchased='mp3',
            price_paid=Decimal('14.99'),
            buyer_name=buyer.username,
            contract_price=0,
            track_price=Decimal('14.99'),
            platform_fee=Decimal('1.50'),
            composer_revenue=Decimal('13.49'),
            stripe_payment_intent_id=pi_id,
        )
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id

        meta = {
            'track_id':       str(track.id),
            'buyer_id':       str(buyer.id),
            'format_type':    'mp3',
            'is_exclusive':   'False',
            'territory':      'France',
            'track_price':    '14.99',
            'duration_years': '3',
            'is_lifetime':    'False',
        }
        session, pi = _make_stripe_session(meta, pi_id=pi_id)

        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve',    return_value=pi):
            resp = client.post(
                '/api/track-payment/verify',
                headers=headers,
                json={'session_id': 'cs_idempotent'},
            )

        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert body['data']['purchase_id'] == existing_id

        # Aucun doublon créé
        count = db.session.query(Purchase).filter_by(
            stripe_payment_intent_id=pi_id
        ).count()
        assert count == 1


# ── Tests — succès ────────────────────────────────────────────────────────────

class TestVerifyPaymentSuccess:

    def test_creates_purchase_and_credits_wallet(self, client, db, buyer_data, track):
        """
        Un paiement valide crée un Purchase et crédite le wallet du compositeur.
        """
        from models import Purchase, Wallet
        headers, buyer = buyer_data

        pi_id = f'pi_success_{uuid.uuid4().hex[:8]}'
        meta = {
            'track_id':               str(track.id),
            'buyer_id':               str(buyer.id),
            'format_type':            'mp3',
            'is_exclusive':           'False',
            'territory':              'France',
            'track_price':            '14.99',
            'duration_years':         '3',
            'is_lifetime':            'False',
            'mechanical_reproduction': 'False',
            'public_show':            'False',
            'arrangement':            'False',
            'buyer_address':          '',
            'buyer_email':            buyer.email,
            'composer_id':            str(track.composer_id),
            'composer_username':      track.composer_user.username,
            'buyer_username':         buyer.username,
        }
        session, pi = _make_stripe_session(meta, pi_id=pi_id)

        _route = 'routes.payment_track_api'
        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve',    return_value=pi), \
             patch('utils.contract_generator.generate_contract_pdf'), \
             patch(f'{_route}.notify_purchase_confirmed'), \
             patch(f'{_route}.notify_sale_completed'), \
             patch(f'{_route}.send_purchase_confirmation_email'), \
             patch(f'{_route}.send_sale_notification_email'):
            resp = client.post(
                '/api/track-payment/verify',
                headers=headers,
                json={'session_id': 'cs_success'},
            )

        assert resp.status_code == 200
        body = json.loads(resp.data)
        assert 'purchase_id' in body['data']

        # Purchase présent en DB
        purchase = db.session.get(Purchase, body['data']['purchase_id'])
        assert purchase is not None
        assert purchase.track_id == track.id
        assert purchase.buyer_id == buyer.id
        assert purchase.format_purchased == 'mp3'

        # Wallet du compositeur crédité avec le montant exact
        # track_price=14.99, commission=10% → platform_fee=1.50, composer_revenue=13.49
        # 14.99 × 0.10 = 1.499 → ROUND_HALF_UP → 1.50 ; 14.99 - 1.50 = 13.49
        composer_wallet = db.session.query(Wallet).filter_by(
            user_id=track.composer_id
        ).first()
        assert composer_wallet is not None
        assert composer_wallet.balance_pending == Decimal('13.49')

    def test_track_not_found_returns_404(self, client, db, buyer_data):
        """Si le track_id en metadata n'existe pas → 404."""
        headers, buyer = buyer_data

        pi_id = f'pi_notfound_{uuid.uuid4().hex[:8]}'
        meta = {
            'track_id':    '99999999',   # n'existe pas
            'buyer_id':    str(buyer.id),
            'format_type': 'mp3',
            'track_price': '14.99',
            'is_exclusive': 'False',
        }
        session, pi = _make_stripe_session(meta, pi_id=pi_id)

        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve',    return_value=pi):
            resp = client.post(
                '/api/track-payment/verify',
                headers=headers,
                json={'session_id': 'cs_notrack'},
            )

        assert resp.status_code == 404


# ── Tests — checkout (guards) ─────────────────────────────────────────────────

class TestCheckoutGuards:
    """Guards de base du endpoint /checkout non couverts par test_payment_track_checkout.py."""

    def test_requires_authentication(self, client, track):
        resp = client.post(f'/api/track-payment/track/{track.id}/mp3/checkout', json={})
        assert resp.status_code == 401

    def test_invalid_format_returns_400(self, client, buyer_data, track):
        headers, _ = buyer_data
        resp = client.post(
            f'/api/track-payment/track/{track.id}/flac/checkout',
            headers=headers,
            json={},
        )
        assert resp.status_code == 400
        assert json.loads(resp.data)['code'] == 'INVALID_FORMAT'

    def test_nonexistent_track_returns_404(self, client, buyer_data):
        headers, _ = buyer_data
        resp = client.post(
            '/api/track-payment/track/999999/mp3/checkout',
            headers=headers,
            json={},
        )
        assert resp.status_code == 404

    def test_composer_cannot_buy_own_track(self, client, app, db, track):
        """Le compositeur ne peut pas acheter son propre beat → 403."""
        from flask_jwt_extended import create_access_token
        with app.app_context():
            token = create_access_token(identity=str(track.composer_id))
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

        resp = client.post(
            f'/api/track-payment/track/{track.id}/mp3/checkout',
            headers=headers,
            json={'duration_years': 3, 'territory': 'France', 'total_price': 14.99},
        )
        assert resp.status_code == 403
        assert json.loads(resp.data)['code'] == 'OWN_TRACK'

    def test_unapproved_track_returns_403(self, client, db, buyer_data, user_free):
        """Un track non approuvé ne peut pas être acheté → 403."""
        from models import Track
        t = Track(
            title='Unapproved',
            composer_id=user_free.id,
            file_hash=str(uuid.uuid4()),
            audio_file='unap.mp3',
            bpm=140,
            key='C minor',
            is_approved=False,
            price_mp3=Decimal('9.99'),
        )
        db.session.add(t)
        db.session.commit()

        headers, _ = buyer_data
        resp = client.post(
            f'/api/track-payment/track/{t.id}/mp3/checkout',
            headers=headers,
            json={'duration_years': 3, 'territory': 'France'},
        )

        db.session.delete(t)
        db.session.commit()

        assert resp.status_code == 403
        assert json.loads(resp.data)['code'] == 'TRACK_UNAVAILABLE'
