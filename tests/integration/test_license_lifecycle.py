"""
Tests d'intégration — cycle de vie des licences

Couvre :
  - compute_expires_at() : calcul de la date d'expiration
  - build_duration_text() : libellé de durée
  - Achat exclusif crée Purchase.is_exclusive=True + Contract lié
  - is_sole_licensee() : détection de l'unique licencié
  - get_user_licenses() : liste ordonnée
"""
import uuid
import json
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal
from datetime import datetime, timedelta

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free  # noqa: F401
from tests.scenarios.tracks import track_default_prices  # noqa: F401


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def buyer(db, bound_factories):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'lifecycle_buyer_{uid}@test.laprod.fr',
        username=f'lifecycle_buyer_{uid}',
        email_verified=True, account_status='active', user_type_selected=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    db.session.rollback()
    from models import Purchase, Contract
    db.session.query(Contract).filter(
        Contract.client_id == u.id
    ).delete()
    db.session.query(Purchase).filter_by(buyer_id=u.id).delete()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def buyer_headers(app, buyer):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(buyer.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}, buyer


# ── compute_expires_at ────────────────────────────────────────────────────────

class TestComputeExpiresAt:

    def test_lifetime_returns_none(self, app):
        with app.app_context():
            from utils.license_service import compute_expires_at
            assert compute_expires_at(is_lifetime=True, duration_years=None) is None

    def test_3_years_returns_correct_date(self, app):
        with app.app_context():
            from utils.license_service import compute_expires_at
            result = compute_expires_at(is_lifetime=False, duration_years=3)
            assert result is not None
            expected = datetime.now() + timedelta(days=3 * 365)
            # tolérance ±5 secondes
            assert abs((result - expected).total_seconds()) < 5

    def test_none_duration_returns_none(self, app):
        with app.app_context():
            from utils.license_service import compute_expires_at
            assert compute_expires_at(is_lifetime=False, duration_years=None) is None


# ── build_duration_text ───────────────────────────────────────────────────────

class TestBuildDurationText:

    def test_lifetime_text(self, app):
        with app.app_context():
            from utils.license_service import build_duration_text
            assert 'vie' in build_duration_text(True, None).lower()

    def test_years_text(self, app):
        with app.app_context():
            from utils.license_service import build_duration_text
            text = build_duration_text(False, 5)
            assert '5' in text

    def test_streaming_text(self, app):
        with app.app_context():
            from utils.license_service import build_duration_text
            text = build_duration_text(False, None)
            assert text  # doit retourner quelque chose (ex: "Streaming")


# ── Purchase avec champs licence ─────────────────────────────────────────────

class TestVerifyPaymentStoreLicenseFields:
    """Vérifie que verify_payment() stocke bien les champs licence sur Purchase."""

    def _build_session(self, track, buyer, is_exclusive: bool, pi_id: str,
                       duration_years: int = 3, is_lifetime: bool = False):
        meta = {
            'track_id':                str(track.id),
            'track_title':             track.title,
            'composer_id':             str(track.composer_id),
            'composer_username':       'test_composer',
            'buyer_id':                str(buyer.id),
            'buyer_username':          buyer.username,
            'format_type':             'mp3',
            'is_exclusive':            str(is_exclusive),
            'duration_years':          str(duration_years),
            'is_lifetime':             str(is_lifetime),
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

    def test_exclusive_purchase_sets_is_exclusive_true(
        self, client, db, app, track_default_prices, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_session(
            track_default_prices, buyer, is_exclusive=True, pi_id=pi_id
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

        from models import Purchase
        p = db.session.query(Purchase).filter_by(
            buyer_id=buyer.id, track_id=track_default_prices.id
        ).order_by(Purchase.id.desc()).first()
        assert p is not None
        assert p.is_exclusive is True
        assert p.duration_years == 3
        assert p.is_lifetime is False
        assert p.territory == 'France'
        assert p.expires_at is not None
        assert p.license_status == 'active'

    def test_exclusive_purchase_creates_contract_record(
        self, client, db, app, track_default_prices, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_session(
            track_default_prices, buyer, is_exclusive=True, pi_id=pi_id
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

        from models import Purchase, Contract
        p = db.session.query(Purchase).filter_by(
            buyer_id=buyer.id, track_id=track_default_prices.id
        ).order_by(Purchase.id.desc()).first()
        assert p is not None

        contract = db.session.query(Contract).filter_by(
            purchase_id=p.id
        ).first()
        assert contract is not None
        assert contract.track_id == track_default_prices.id
        assert contract.is_exclusive is True
        assert contract.status == 'active'

    def test_lifetime_purchase_has_no_expiry(
        self, client, db, app, track_default_prices, buyer_headers
    ):
        headers, buyer = buyer_headers
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_session(
            track_default_prices, buyer, is_exclusive=False, pi_id=pi_id,
            duration_years=0, is_lifetime=True,
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

        from models import Purchase
        p = db.session.query(Purchase).filter_by(
            buyer_id=buyer.id, track_id=track_default_prices.id
        ).order_by(Purchase.id.desc()).first()
        assert p is not None
        assert p.is_lifetime is True
        assert p.expires_at is None


# ── is_sole_licensee ──────────────────────────────────────────────────────────

class TestIsSoleLicensee:

    def test_sole_when_only_active_purchase(self, app, db, bound_factories, track_default_prices):
        from tests.factories.user_factory import UserFactory
        from tests.factories.purchase_factory import PurchaseFactory
        uid = uuid.uuid4().hex[:8]
        buyer = UserFactory(email=f'sole_{uid}@test.fr', username=f'sole_{uid}')
        db.session.commit()

        p = PurchaseFactory(
            track_id=track_default_prices.id,
            buyer_id=buyer.id,
            license_status='active',
        )
        db.session.commit()

        with app.app_context():
            from utils.license_service import is_sole_licensee
            from models import Purchase
            purchase = db.session.get(Purchase, p.id)
            assert is_sole_licensee(purchase) is True

    def test_not_sole_when_two_active_purchases(self, app, db, bound_factories, track_default_prices):
        from tests.factories.user_factory import UserFactory
        from tests.factories.purchase_factory import PurchaseFactory
        uid = uuid.uuid4().hex[:8]
        b1 = UserFactory(email=f'sole1_{uid}@test.fr', username=f'sole1_{uid}')
        b2 = UserFactory(email=f'sole2_{uid}@test.fr', username=f'sole2_{uid}')
        db.session.commit()

        p1 = PurchaseFactory(track_id=track_default_prices.id, buyer_id=b1.id, license_status='active')
        PurchaseFactory(track_id=track_default_prices.id, buyer_id=b2.id, license_status='active')
        db.session.commit()

        with app.app_context():
            from utils.license_service import is_sole_licensee
            from models import Purchase
            purchase = db.session.get(Purchase, p1.id)
            assert is_sole_licensee(purchase) is False
