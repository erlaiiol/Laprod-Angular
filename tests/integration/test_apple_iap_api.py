"""
Tests d'intégration — achats intégrés Apple (abonnement LaProd+ sur iOS)

Vérifie :
  · GET  /api/apple-iap/policy         — politique par catégorie, repli sûr
  · GET  /api/apple-iap/products       — produits + jeton de compte, auth requise
  · POST /api/apple-iap/verify         — crédit, idempotence, prolongation, refus
  · POST /api/apple-iap/notifications  — remboursement → jours repris, rejouable

Apple n'est jamais appelé : la vérification de signature (utils.apple_iap.
verify_transaction / verify_notification) est mockée, sauf dans le test qui
s'assure qu'une transaction fabriquée est bien rejetée par la vraie bibliothèque.
"""
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from utils import apple_iap, plans

IAP_CONFIG = {
    'APPLE_APP_ID': '1234567890',
    'APPLE_BUNDLE_ID': 'net.laprod.app',
    'APPLE_IAP_PRODUCT_PREMIUM': 'test.premium',
    'APPLE_IAP_PRODUCT_SEMI_PRO': 'test.semipro',
    'APPLE_IAP_PRODUCT_PRO_STRUCTURE': 'test.prostructure',
    'APPLE_IAP_ALLOW_XCODE': False,
    'IOS_POLICY_SUBSCRIPTION': 'iap',
    'IOS_POLICY_BEAT_LICENSE': 'stripe',
    'IOS_POLICY_MIX_ORDER': 'stripe',
    'IOS_POLICY_CAMPAIGN_BOOST': 'unavailable',
}


@pytest.fixture()
def iap_config(app):
    """Configure l'achat intégré le temps d'un test, puis restaure."""
    saved = {k: app.config.get(k) for k in IAP_CONFIG}
    app.config.update(IAP_CONFIG)
    yield app.config
    app.config.update(saved)


def _make_user(db, **kwargs):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'iap_{uid}@test.laprod.fr', username=f'iap_{uid}',
        email_verified=True, account_status='active', user_type_selected=True,
        subscription_plan=kwargs.pop('subscription_plan', 'free'), **kwargs,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    return u


def _cleanup(db, *users):
    from models import AppleIapTransaction, Notification, User
    db.session.rollback()
    for u in users:
        AppleIapTransaction.query.filter_by(user_id=u.id).delete()
        Notification.query.filter_by(user_id=u.id).delete()
        existing = db.session.get(User, u.id)
        if existing:
            db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def free_user(db):
    u = _make_user(db)
    yield u
    _cleanup(db, u)


@pytest.fixture()
def other_user(db):
    u = _make_user(db)
    yield u
    _cleanup(db, u)


def _headers(app, user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _tx(product_id='test.premium', transaction_id=None, token=None, **extra):
    """Payload de transaction tel que renvoyé par la vérification Apple."""
    fields = dict(
        transactionId=transaction_id or uuid.uuid4().hex,
        productId=product_id,
        appAccountToken=token,
        purchaseDate=int(datetime.now().timestamp() * 1000),
        revocationDate=None,
        rawEnvironment='Sandbox',
        price=4990,
        currency='EUR',
    )
    fields.update(extra)
    return SimpleNamespace(**fields)


def _verify(client, headers, tx, n=1):
    with patch('utils.apple_iap.verify_transaction', return_value=tx):
        return client.post('/api/apple-iap/verify', headers=headers,
                           json={'transactions': ['signed'] * n})


# ── Politique ─────────────────────────────────────────────────────────────────

class TestPolicy:

    def test_policy_is_public(self, client, iap_config):
        resp = client.get('/api/apple-iap/policy')
        assert resp.status_code == 200
        assert resp.json['data']['policy'] == {
            'subscription': 'iap', 'beat_license': 'stripe',
            'mix_order': 'stripe', 'campaign_boost': 'unavailable',
        }

    def test_subscription_unavailable_when_iap_not_configured(self, client, iap_config):
        iap_config['APPLE_APP_ID'] = None
        policy = client.get('/api/apple-iap/policy').json['data']['policy']
        assert policy['subscription'] == 'unavailable'

    def test_subscription_can_never_be_stripe(self, client, iap_config):
        iap_config['IOS_POLICY_SUBSCRIPTION'] = 'stripe'
        policy = client.get('/api/apple-iap/policy').json['data']['policy']
        assert policy['subscription'] == 'unavailable'

    def test_unknown_value_falls_back_to_unavailable(self, client, iap_config):
        iap_config['IOS_POLICY_BEAT_LICENSE'] = 'strpie'
        policy = client.get('/api/apple-iap/policy').json['data']['policy']
        assert policy['beat_license'] == 'unavailable'


# ── Produits ──────────────────────────────────────────────────────────────────

class TestProducts:

    def test_requires_auth(self, client, iap_config):
        assert client.get('/api/apple-iap/products').status_code == 401

    def test_returns_products_and_stable_account_token(self, app, client, iap_config, free_user):
        data = client.get('/api/apple-iap/products', headers=_headers(app, free_user)).json['data']
        assert data['configured'] is True
        assert {p['plan']: p['product_id'] for p in data['products']} == {
            plans.PREMIUM: 'test.premium',
            plans.SEMI_PRO: 'test.semipro',
            plans.PRO_STRUCTURE: 'test.prostructure',
        }
        assert data['app_account_token'] == apple_iap.account_token_for(free_user.id)
        uuid.UUID(data['app_account_token'])  # format exigé par StoreKit

    def test_no_products_when_not_configured(self, app, client, iap_config, free_user):
        iap_config['APPLE_APP_ID'] = None
        data = client.get('/api/apple-iap/products', headers=_headers(app, free_user)).json['data']
        assert data['configured'] is False
        assert data['products'] == []


# ── Vérification / crédit ─────────────────────────────────────────────────────

class TestVerify:

    def test_requires_auth(self, client, iap_config):
        assert client.post('/api/apple-iap/verify', json={'transactions': ['x']}).status_code == 401

    def test_empty_body_rejected(self, app, client, iap_config, free_user):
        resp = client.post('/api/apple-iap/verify', headers=_headers(app, free_user), json={})
        assert resp.status_code == 400
        assert resp.json['code'] == 'IAP_NO_TRANSACTION'

    def test_credits_30_days_and_plan(self, app, client, db, iap_config, free_user):
        token = apple_iap.account_token_for(free_user.id)
        resp = _verify(client, _headers(app, free_user), _tx('test.semipro', token=token))
        assert resp.status_code == 200
        data = resp.json['data']
        assert data['credited'] == 1
        assert data['subscription_plan'] == plans.SEMI_PRO
        assert data['is_premium_active'] is True

        db.session.refresh(free_user)
        assert free_user.premium_source == 'apple'
        remaining = free_user.premium_expires_at - datetime.now()
        assert timedelta(days=29, hours=23) < remaining <= timedelta(days=30)
        assert free_user.topline_tokens == plans.get(plans.SEMI_PRO).topline_cap

    def test_same_transaction_is_credited_once(self, app, client, db, iap_config, free_user):
        tx = _tx()
        headers = _headers(app, free_user)
        assert _verify(client, headers, tx).json['data']['credited'] == 1
        db.session.refresh(free_user)
        expires = free_user.premium_expires_at

        again = _verify(client, headers, tx)
        assert again.status_code == 200
        assert again.json['data']['credited'] == 0
        db.session.refresh(free_user)
        assert free_user.premium_expires_at == expires

    def test_same_transaction_twice_in_one_restore(self, app, client, db, iap_config, free_user):
        resp = _verify(client, _headers(app, free_user), _tx(), n=3)
        assert resp.json['data']['credited'] == 1

    def test_active_subscription_is_extended_not_reset(self, app, client, db, iap_config):
        expires = datetime.now() + timedelta(days=10)
        user = _make_user(db, subscription_plan='premium',
                          premium_since=datetime.now() - timedelta(days=20),
                          premium_expires_at=expires)
        try:
            _verify(client, _headers(app, user), _tx('test.premium'))
            db.session.refresh(user)
            assert user.premium_expires_at == expires + timedelta(days=30)
        finally:
            _cleanup(db, user)

    def test_transaction_of_another_account_is_refused(self, app, client, db, iap_config,
                                                       free_user, other_user):
        tx = _tx(token=apple_iap.account_token_for(other_user.id))
        resp = _verify(client, _headers(app, free_user), tx)
        assert resp.status_code == 400
        assert resp.json['code'] == 'IAP_OTHER_ACCOUNT'
        db.session.refresh(free_user)
        assert free_user.is_premium_active is False

    def test_transaction_already_claimed_cannot_be_replayed(self, app, client, db, iap_config,
                                                            free_user, other_user):
        tx = _tx()  # sans jeton de compte : premier arrivé, premier servi
        assert _verify(client, _headers(app, other_user), tx).json['data']['credited'] == 1
        resp = _verify(client, _headers(app, free_user), tx)
        assert resp.status_code == 400
        assert resp.json['code'] == 'IAP_OTHER_ACCOUNT'
        db.session.refresh(free_user)
        assert free_user.is_premium_active is False

    def test_unknown_product_is_refused(self, app, client, db, iap_config, free_user):
        resp = _verify(client, _headers(app, free_user), _tx('autre.app.produit'))
        assert resp.status_code == 400
        assert resp.json['code'] == 'IAP_UNKNOWN_PRODUCT'

    def test_refunded_transaction_is_refused(self, app, client, db, iap_config, free_user):
        tx = _tx(revocationDate=int(datetime.now().timestamp() * 1000))
        resp = _verify(client, _headers(app, free_user), tx)
        assert resp.status_code == 400
        assert resp.json['code'] == 'IAP_REVOKED'

    def test_forged_transaction_is_rejected_by_real_verifier(self, app, client, db,
                                                             iap_config, free_user):
        """Sans mock : une chaîne fabriquée ne passe pas la vérification Apple."""
        resp = client.post('/api/apple-iap/verify', headers=_headers(app, free_user),
                           json={'transactions': ['eyJhbGciOiJFUzI1NiJ9.e30.forged']})
        assert resp.status_code == 400
        assert resp.json['code'] == 'IAP_INVALID_TRANSACTION'
        db.session.refresh(free_user)
        assert free_user.is_premium_active is False

    def test_not_configured_returns_503(self, app, client, db, iap_config, free_user):
        iap_config['APPLE_APP_ID'] = None
        resp = client.post('/api/apple-iap/verify', headers=_headers(app, free_user),
                           json={'transactions': ['whatever']})
        assert resp.status_code == 503
        assert resp.json['code'] == 'IAP_NOT_CONFIGURED'


# ── Notifications serveur (remboursement) ─────────────────────────────────────

class TestNotifications:

    def _notify(self, client, notif_type, tx):
        notification = SimpleNamespace(
            rawNotificationType=notif_type,
            data=SimpleNamespace(signedTransactionInfo='signed-tx'),
        )
        with patch('utils.apple_iap.verify_notification', return_value=notification), \
             patch('utils.apple_iap.verify_transaction', return_value=tx):
            return client.post('/api/apple-iap/notifications', json={'signedPayload': 'signed'})

    def test_unsigned_body_is_rejected(self, client, iap_config):
        assert client.post('/api/apple-iap/notifications', json={}).status_code == 400
        resp = client.post('/api/apple-iap/notifications', json={'signedPayload': 'a.b.c'})
        assert resp.status_code == 400

    def test_refund_takes_days_back_and_downgrades(self, app, client, db, iap_config, free_user):
        tx = _tx('test.premium')
        _verify(client, _headers(app, free_user), tx)
        db.session.refresh(free_user)
        assert free_user.is_premium_active is True

        resp = self._notify(client, 'REFUND', tx)
        assert resp.status_code == 200
        assert resp.json['data']['handled'] is True
        db.session.refresh(free_user)
        assert free_user.is_premium_active is False
        assert free_user.plan == plans.FREE

    def test_refund_of_one_period_keeps_the_others(self, app, client, db, iap_config, free_user):
        first, second = _tx(), _tx()
        headers = _headers(app, free_user)
        _verify(client, headers, first)
        _verify(client, headers, second)

        self._notify(client, 'REFUND', second)
        db.session.refresh(free_user)
        assert free_user.is_premium_active is True
        remaining = free_user.premium_expires_at - datetime.now()
        assert timedelta(days=29) < remaining <= timedelta(days=30)

    def test_refund_is_replayable(self, app, client, db, iap_config, free_user):
        first, second = _tx(), _tx()
        headers = _headers(app, free_user)
        _verify(client, headers, first)
        _verify(client, headers, second)

        self._notify(client, 'REFUND', second)
        replay = self._notify(client, 'REFUND', second)
        assert replay.status_code == 200
        assert replay.json['data']['handled'] is False
        db.session.refresh(free_user)
        assert free_user.is_premium_active is True

    def test_other_notification_types_are_ignored(self, app, client, db, iap_config, free_user):
        tx = _tx()
        _verify(client, _headers(app, free_user), tx)
        resp = self._notify(client, 'TEST', tx)
        assert resp.status_code == 200
        assert resp.json['data']['handled'] is False
        db.session.refresh(free_user)
        assert free_user.is_premium_active is True
