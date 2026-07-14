"""
Tests d'intégration — renouvellement de licence

Couvre :
  - POST /api/track-payment/track/<id>/renew/<pid> → checkout_url
  - Renouvellement d'un track non possédé → 403
  - Double renouvellement (renewed_to_id déjà défini) → 409
  - POST /api/track-payment/verify-renewal → nouveau Purchase + liaison ancien
  - Idempotence verify-renewal (double appel) → 200 sans doublon
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
def buyer_with_license(app, db, bound_factories, track_default_prices):
    """Crée un acheteur qui possède déjà une licence active sur track_default_prices."""
    from models import User, Purchase
    from tests.factories.purchase_factory import PurchaseFactory
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'renew_buyer_{uid}@test.laprod.fr',
        username=f'renew_buyer_{uid}',
        email_verified=True, account_status='active', user_type_selected=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()

    expires = datetime.now() + timedelta(days=10)
    p = PurchaseFactory(
        track_id=track_default_prices.id,
        buyer_id=u.id,
        license_status='active',
        is_exclusive=False,
        is_lifetime=False,
        duration_years=3,
        expires_at=expires,
        territory='France',
    )
    db.session.commit()

    with app.app_context():
        token_str = _make_token(app, u.id)

    yield u, p, {'Authorization': f'Bearer {token_str}', 'Content-Type': 'application/json'}

    db.session.rollback()
    from models import Contract
    buyer_purchases = db.session.query(Purchase).filter_by(buyer_id=u.id).all()
    for bp in buyer_purchases:
        db.session.query(Contract).filter_by(purchase_id=bp.id).delete()
    db.session.query(Purchase).filter_by(buyer_id=u.id).delete()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def other_buyer_headers(app, db, bound_factories):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'other_buyer_{uid}@test.laprod.fr',
        username=f'other_buyer_{uid}',
        email_verified=True, account_status='active', user_type_selected=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    with app.app_context():
        token_str = _make_token(app, u.id)
    yield u, {'Authorization': f'Bearer {token_str}', 'Content-Type': 'application/json'}
    db.session.rollback()
    from models import User
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


def _make_token(app, user_id: int) -> str:
    from flask_jwt_extended import create_access_token
    with app.app_context():
        return create_access_token(identity=str(user_id))


# ── POST /renew — initier le renouvellement ───────────────────────────────────

class TestInitiateRenewal:

    def test_renew_returns_checkout_url(self, client, db, app, buyer_with_license, track_default_prices):
        buyer, purchase, headers = buyer_with_license

        fake_session = MagicMock()
        fake_session.url = 'https://checkout.stripe.com/test_renewal'

        with patch('stripe.checkout.Session.create', return_value=fake_session):
            resp = client.post(
                f'/api/track-payment/track/{track_default_prices.id}/renew/{purchase.id}',
                data=json.dumps({'legal_terms_accepted': True, 'withdrawal_right_waived': True}),
                headers=headers,
            )

        assert resp.status_code == 200
        body = resp.json
        assert body['success'] is True
        assert 'checkout_url' in body['data']

    def test_renew_by_non_owner_returns_403(
        self, client, db, app, buyer_with_license, other_buyer_headers, track_default_prices
    ):
        buyer, purchase, _ = buyer_with_license
        _other, other_headers = other_buyer_headers

        resp = client.post(
            f'/api/track-payment/track/{track_default_prices.id}/renew/{purchase.id}',
            data=json.dumps({}),
            headers=other_headers,
        )
        assert resp.status_code == 403

    def test_renew_already_renewed_returns_409(self, client, db, app, buyer_with_license, track_default_prices):
        buyer, purchase, headers = buyer_with_license

        from models import Purchase
        purchase.renewed_to_id = 9999
        db.session.commit()

        resp = client.post(
            f'/api/track-payment/track/{track_default_prices.id}/renew/{purchase.id}',
            data=json.dumps({}),
            headers=headers,
        )
        assert resp.status_code == 409

        purchase.renewed_to_id = None
        db.session.commit()


# ── POST /verify-renewal ──────────────────────────────────────────────────────

class TestVerifyRenewal:

    def _build_renewal_session(self, track, buyer, old_purchase, pi_id: str):
        meta = {
            'track_id':                str(track.id),
            'track_title':             track.title,
            'composer_id':             str(track.composer_id),
            'composer_username':       'test_composer',
            'buyer_id':                str(buyer.id),
            'buyer_username':          buyer.username,
            'format_type':             'mp3',
            'is_exclusive':            'False',
            'duration_years':          '3',
            'is_lifetime':             'False',
            'territory':               'France',
            'renewal_of_purchase_id':  str(old_purchase.id),
            'streaming':               'true',
            'mechanical_reproduction': 'False',
            'public_show':             'False',
            'arrangement':             'False',
            'buyer_address':           '',
            'buyer_email':             buyer.email,
            'track_price':             '9.99',
            'legal_terms_accepted':           'True',
            'withdrawal_right_waived':        'True',
            'buyer_declares_original_lyrics': 'False',
        }
        session = MagicMock()
        session.payment_intent = pi_id
        session.metadata = meta
        intent = MagicMock()
        intent.status = 'succeeded'
        intent.amount = 999
        intent.metadata = meta
        return session, intent

    def test_verify_renewal_creates_new_purchase(
        self, client, db, app, buyer_with_license, track_default_prices
    ):
        buyer, old_purchase, headers = buyer_with_license
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'
        session, intent = self._build_renewal_session(
            track_default_prices, buyer, old_purchase, pi_id
        )

        with patch('stripe.checkout.Session.retrieve', return_value=session), \
             patch('stripe.PaymentIntent.retrieve', return_value=intent), \
             patch('utils.notification_service.notify_renewal_confirmed'), \
             patch('utils.email_service.send_renewal_confirmation_email'), \
             patch('utils.wallet_service.credit_wallet_for_beat_sale'), \
             patch('utils.contract_data_builder.generate_contract_pdf'):
            resp = client.post(
                '/api/track-payment/verify-renewal',
                data=json.dumps({'session_id': 'cs_test_dummy'}),
                headers=headers,
            )

        assert resp.status_code == 200
        body = resp.json
        assert body['success'] is True
        assert 'purchase_id' in body['data']

        new_pid = body['data']['purchase_id']
        from models import Purchase
        new_p = db.session.get(Purchase, new_pid)
        assert new_p is not None
        assert new_p.renewed_from_id == old_purchase.id

        # Le consentement du renouvellement est bien capturé sur le nouveau Contract
        # (pas hérité silencieusement de l'ancien) — cf. contract_data_builder.build_contract_data.
        assert new_p.contract is not None
        assert new_p.contract.legal_terms_accepted is True
        assert new_p.contract.withdrawal_right_waived is True
        assert new_p.contract.consent_recorded_at is not None

        db.session.refresh(old_purchase)
        assert old_purchase.license_status == 'renewed'
        assert old_purchase.renewed_to_id == new_pid

    def test_verify_renewal_idempotent(
        self, client, db, app, buyer_with_license, track_default_prices
    ):
        """Deux appels avec le même payment_intent_id ne créent qu'un Purchase."""
        buyer, old_purchase, headers = buyer_with_license
        pi_id = f'pi_test_{uuid.uuid4().hex[:12]}'

        old_purchase.license_status = 'active'
        old_purchase.renewed_to_id = None
        db.session.commit()

        session, intent = self._build_renewal_session(
            track_default_prices, buyer, old_purchase, pi_id
        )

        _patches = dict(
            s1=patch('stripe.checkout.Session.retrieve', return_value=session),
            s2=patch('stripe.PaymentIntent.retrieve', return_value=intent),
            s3=patch('utils.notification_service.notify_renewal_confirmed'),
            s4=patch('utils.email_service.send_renewal_confirmation_email'),
            s5=patch('utils.wallet_service.credit_wallet_for_beat_sale'),
            s6=patch('utils.contract_data_builder.generate_contract_pdf'),
        )

        with _patches['s1'], _patches['s2'], _patches['s3'], \
             _patches['s4'], _patches['s5'], _patches['s6']:
            r1 = client.post(
                '/api/track-payment/verify-renewal',
                data=json.dumps({'session_id': 'cs_test_dummy'}),
                headers=headers,
            )
        assert r1.status_code == 200

        with _patches['s1'], _patches['s2'], _patches['s3'], \
             _patches['s4'], _patches['s5'], _patches['s6']:
            r2 = client.post(
                '/api/track-payment/verify-renewal',
                data=json.dumps({'session_id': 'cs_test_dummy'}),
                headers=headers,
            )
        assert r2.status_code == 200
        # Le même purchase_id est retourné
        assert r1.json['data']['purchase_id'] == r2.json['data']['purchase_id']

        from models import Purchase
        count = db.session.query(Purchase).filter_by(
            stripe_payment_intent_id=pi_id
        ).count()
        assert count == 1
