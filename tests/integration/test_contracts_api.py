"""
Tests d'intégration — routes/contracts_api.py

Couvre : GET /api/contracts/my, GET /api/contracts/sales.
"""

import json
import uuid

import pytest


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture()
def track(db, user):
    """Track minimal approuvé, lié au user standard (compositeur)."""
    from models import Track
    t = Track(
        title='Sales Test Beat',
        composer_id=user.id,
        file_hash=str(uuid.uuid4()),
        audio_file='sales_preview.mp3',
        bpm=90,
        key='G minor',
        is_approved=True,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


@pytest.fixture()
def purchase(db, track, user):
    """Purchase minimal lié au track du user (user = compositeur ET acheteur simulé)."""
    from models import Purchase
    p = Purchase(
        track_id=track.id,
        buyer_id=user.id,
        format_purchased='mp3',
        price_paid=9.99,
        buyer_name='Test Buyer',
        track_price=9.99,
        contract_price=0.0,
        platform_fee=1.00,
        composer_revenue=8.99,
        stripe_payment_intent_id=f'pi_test_{uuid.uuid4().hex[:16]}',
    )
    db.session.add(p)
    db.session.commit()
    yield p
    existing = db.session.get(Purchase, p.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


# ── GET /api/contracts/my ─────────────────────────────────────────────────────

class TestGetMyPurchases:

    def test_requires_authentication(self, client):
        resp = client.get('/api/contracts/my')
        assert resp.status_code == 401

    def test_returns_empty_list_for_new_user(self, client, auth_headers):
        resp = client.get('/api/contracts/my', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data['data']['purchases'], list)


# ── GET /api/contracts/sales ──────────────────────────────────────────────────

class TestGetMySales:

    def test_requires_authentication(self, client):
        resp = client.get('/api/contracts/sales')
        assert resp.status_code == 401

    def test_returns_sales_for_composer(self, client, auth_headers, purchase):
        """Un compositeur voit ses ventes et le total des revenus."""
        resp = client.get('/api/contracts/sales', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data['data']['sales']) >= 1
        assert data['data']['total_revenue'] >= 0
