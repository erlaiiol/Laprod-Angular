"""
Tests d'intégration — API de téléchargement de factures (routes/invoice_api.py)

Couvre :
  - GET /api/invoices/purchase/<id>             → 200 PDF / 403 / 404
  - GET /api/invoices/purchase/<id>/statement   → 200 PDF / 403 / 404
  - GET /api/invoices/mixmaster/<id>            → 200 PDF / 403 / 404
  - GET /api/invoices/mixmaster/<id>/earnings/<stage> → 200 PDF / 400 (stage invalide) / 403
  - GET /api/admin/invoices                     → 200 liste / 401 non-admin
  - Routes admin de téléchargement              → 200 PDF admin bypass
"""
import uuid
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from tests.factories import bound_factories  # noqa: F401


# ── Factories minimales ────────────────────────────────────────────────────────

def _make_user(db, *, is_admin=False):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'inv_user_{uid}@test.laprod.fr',
        username=f'inv_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_admin=is_admin,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.flush()
    return u


def _make_track(db, composer):
    from models import Track
    t = Track(
        title=f'Test Track {uuid.uuid4().hex[:6]}',
        composer_id=composer.id,
        file_hash=uuid.uuid4().hex,
        audio_file=f'audio/tracks/test_{uuid.uuid4().hex[:8]}.mp3',
        bpm=120,
        key='Am',
        style='Trap',
        price_mp3=Decimal('9.99'),
        is_approved=True,
    )
    db.session.add(t)
    db.session.flush()
    return t


def _make_purchase(db, track, buyer):
    from models import Purchase
    p = Purchase(
        track_id=track.id,
        buyer_id=buyer.id,
        format_purchased='mp3',
        price_paid=Decimal('9.99'),
        buyer_name=buyer.username,
        track_price=Decimal('9.99'),
        contract_price=Decimal('0.00'),
        platform_fee=Decimal('1.00'),
        composer_revenue=Decimal('8.99'),
        stripe_payment_intent_id=f'pi_test_{uuid.uuid4().hex[:16]}',
    )
    db.session.add(p)
    db.session.flush()
    return p


def _make_mm(db, artist, engineer):
    from models import MixMasterRequest
    mm = MixMasterRequest(
        title='Test Mix',
        artist_id=artist.id,
        engineer_id=engineer.id,
        original_file='audio/test.zip',
        total_price=Decimal('100.00'),
        deposit_amount=Decimal('30.00'),
        remaining_amount=Decimal('70.00'),
        platform_fee=Decimal('10.00'),
        engineer_revenue=Decimal('90.00'),
        status='accepted',
        revision_count=0,
    )
    db.session.add(mm)
    db.session.flush()
    return mm


def _token(app, user_id):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        return create_access_token(identity=str(user_id))


def _headers(app, user_id):
    return {'Authorization': f'Bearer {_token(app, user_id)}',
            'Content-Type': 'application/json'}


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def invoice_setup(app, db):
    """Crée buyer, composer, track, purchase, artist, engineer, mm."""
    buyer    = _make_user(db)
    composer = _make_user(db)
    admin    = _make_user(db, is_admin=True)
    artist   = _make_user(db)
    engineer = _make_user(db)
    track    = _make_track(db, composer)
    purchase = _make_purchase(db, track, buyer)
    mm       = _make_mm(db, artist, engineer)
    db.session.commit()

    yield {
        'buyer': buyer, 'composer': composer, 'admin': admin,
        'artist': artist, 'engineer': engineer,
        'track': track, 'purchase': purchase, 'mm': mm,
    }

    db.session.rollback()
    from models import Purchase, MixMasterRequest, Track, User
    db.session.query(Purchase).filter_by(id=purchase.id).delete()
    db.session.query(MixMasterRequest).filter_by(id=mm.id).delete()
    db.session.query(Track).filter_by(id=track.id).delete()
    for u in [buyer, composer, admin, artist, engineer]:
        existing = db.session.get(User, u.id)
        if existing:
            db.session.delete(existing)
    db.session.commit()


# ══════════════════════════════════════════════════════════════════════════════
# Facture acheteur — /api/invoices/purchase/<id>
# ══════════════════════════════════════════════════════════════════════════════

class TestPurchaseInvoiceDownload:

    def test_buyer_gets_pdf(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/purchase/{s["purchase"].id}',
            headers=_headers(app, s['buyer'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:4] == b'%PDF'

    def test_requires_auth(self, client, invoice_setup):
        s = invoice_setup
        resp = client.get(f'/api/invoices/purchase/{s["purchase"].id}')
        assert resp.status_code == 401

    def test_non_buyer_gets_403(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/purchase/{s["purchase"].id}',
            headers=_headers(app, s['composer'].id),
        )
        assert resp.status_code == 403

    def test_missing_purchase_returns_404(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            '/api/invoices/purchase/9999999',
            headers=_headers(app, s['buyer'].id),
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Relevé de vente compositeur — /api/invoices/purchase/<id>/statement
# ══════════════════════════════════════════════════════════════════════════════

class TestSaleStatementDownload:

    def test_composer_gets_pdf(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/purchase/{s["purchase"].id}/statement',
            headers=_headers(app, s['composer'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:4] == b'%PDF'

    def test_requires_auth(self, client, invoice_setup):
        s = invoice_setup
        resp = client.get(f'/api/invoices/purchase/{s["purchase"].id}/statement')
        assert resp.status_code == 401

    def test_buyer_cannot_access_statement(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/purchase/{s["purchase"].id}/statement',
            headers=_headers(app, s['buyer'].id),
        )
        assert resp.status_code == 403

    def test_missing_purchase_returns_404(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            '/api/invoices/purchase/9999999/statement',
            headers=_headers(app, s['composer'].id),
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Facture artiste MixMaster — /api/invoices/mixmaster/<id>
# ══════════════════════════════════════════════════════════════════════════════

class TestMixmasterInvoiceDownload:

    def test_artist_gets_pdf(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/mixmaster/{s["mm"].id}',
            headers=_headers(app, s['artist'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:4] == b'%PDF'

    def test_requires_auth(self, client, invoice_setup):
        s = invoice_setup
        resp = client.get(f'/api/invoices/mixmaster/{s["mm"].id}')
        assert resp.status_code == 401

    def test_engineer_cannot_access_artist_invoice(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/mixmaster/{s["mm"].id}',
            headers=_headers(app, s['engineer'].id),
        )
        assert resp.status_code == 403

    def test_missing_mm_returns_404(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            '/api/invoices/mixmaster/9999999',
            headers=_headers(app, s['artist'].id),
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Relevé gains ingénieur — /api/invoices/mixmaster/<id>/earnings/<stage>
# ══════════════════════════════════════════════════════════════════════════════

class TestMixmasterEarningsDownload:

    @pytest.mark.parametrize('stage', ['deposit', 'revision1', 'revision2', 'final'])
    def test_engineer_gets_pdf_for_all_stages(self, client, app, invoice_setup, stage):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/mixmaster/{s["mm"].id}/earnings/{stage}',
            headers=_headers(app, s['engineer'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'
        assert resp.data[:4] == b'%PDF'

    def test_invalid_stage_returns_400(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/mixmaster/{s["mm"].id}/earnings/invalid_stage',
            headers=_headers(app, s['engineer'].id),
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, invoice_setup):
        s = invoice_setup
        resp = client.get(f'/api/invoices/mixmaster/{s["mm"].id}/earnings/deposit')
        assert resp.status_code == 401

    def test_artist_cannot_access_engineer_statement(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/invoices/mixmaster/{s["mm"].id}/earnings/deposit',
            headers=_headers(app, s['artist'].id),
        )
        assert resp.status_code == 403


# ══════════════════════════════════════════════════════════════════════════════
# Admin — liste /api/admin/invoices
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminInvoicesList:

    def test_admin_gets_list(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            '/api/admin/invoices',
            headers=_headers(app, s['admin'].id),
        )
        assert resp.status_code == 200
        body = resp.json
        assert body['success'] is True
        assert 'purchases' in body['data']
        assert 'mm_requests' in body['data']
        assert 'totals' in body['data']
        # Le purchase créé dans le setup doit apparaître
        ids = [p['id'] for p in body['data']['purchases']]
        assert s['purchase'].id in ids

    def test_non_admin_gets_403(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            '/api/admin/invoices',
            headers=_headers(app, s['buyer'].id),
        )
        assert resp.status_code == 403

    def test_requires_auth(self, client, invoice_setup):
        resp = client.get('/api/admin/invoices')
        assert resp.status_code == 401

    def test_totals_structure(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get('/api/admin/invoices', headers=_headers(app, s['admin'].id))
        totals = resp.json['data']['totals']
        assert 'purchases_count' in totals
        assert 'mm_count' in totals
        assert 'purchases_revenue' in totals
        assert 'mm_revenue' in totals


# ══════════════════════════════════════════════════════════════════════════════
# Admin — téléchargement bypass (accès sans être buyer/composer/artist/engineer)
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminDownloadRoutes:

    def test_admin_download_purchase_invoice(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/admin/invoices/purchase/{s["purchase"].id}',
            headers=_headers(app, s['admin'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'

    def test_admin_download_sale_statement(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/admin/invoices/purchase/{s["purchase"].id}/statement',
            headers=_headers(app, s['admin'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'

    def test_admin_download_mixmaster_invoice(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/admin/invoices/mixmaster/{s["mm"].id}',
            headers=_headers(app, s['admin'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'

    def test_admin_download_mixmaster_earnings(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/admin/invoices/mixmaster/{s["mm"].id}/earnings/deposit',
            headers=_headers(app, s['admin'].id),
        )
        assert resp.status_code == 200
        assert resp.content_type == 'application/pdf'

    def test_non_admin_blocked_from_admin_routes(self, client, app, invoice_setup):
        s = invoice_setup
        resp = client.get(
            f'/api/admin/invoices/purchase/{s["purchase"].id}',
            headers=_headers(app, s['buyer'].id),
        )
        assert resp.status_code == 403
