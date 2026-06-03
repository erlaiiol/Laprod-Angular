"""
Tests d'intégration — calcul du prix MixMasterRequest envoyé à Stripe

Vérifie que unit_amount (en centimes) passé à stripe.checkout.Session.create()
reflète exactement le calcul serveur selon les services cochés et le bonus stems.

Chaîne de calcul (MixMasterRequestPriceCalculator) :
  base_price  = reference_price × somme des % services sélectionnés
                  cleaning=35%, effects=45%, artistic=60%, mastering=20%
  stems_bonus = reference_price × 20%  (si has_separated_stems)
  total       = max(base_price + stems_bonus, price_min)
  unit_amount = int(total * 100)
"""
import io
import uuid
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def engineer(db):
    """Ingénieur certifié : ref=100€, min=10€ — pas d'auto-sélection de services."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'engineer_{uid}@test.laprod.fr',
        username=f'engineer_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,   # requis pour service_mastering
        mixmaster_reference_price=100,
        mixmaster_price_min=10,
        is_certified_producer_arranger=False,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    db.session.rollback()
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def engineer_high_min(db):
    """Ingénieur avec prix minimum élevé : ref=100€, min=30€ — teste le plancher de prix."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'eng_hm_{uid}@test.laprod.fr',
        username=f'eng_hm_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,   # requis pour service_mastering
        mixmaster_reference_price=100,
        mixmaster_price_min=30,
        is_certified_producer_arranger=False,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    db.session.rollback()
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def artist(db):
    """Artiste qui commande le mix/master."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'artist_{uid}@test.laprod.fr',
        username=f'artist_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    db.session.rollback()
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def artist_headers(app, artist):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(artist.id))
    return {'Authorization': f'Bearer {token}'}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _unit_amount(mock_create) -> int:
    """Retourne unit_amount (centimes) capturé depuis l'appel à stripe.checkout.Session.create."""
    kwargs = mock_create.call_args.kwargs
    return kwargs['line_items'][0]['price_data']['unit_amount']


def _order_payload(services: dict, has_stems: bool = False) -> dict:
    """
    Construit les données multipart pour POST /api/mixmaster-artist/order/<id>.

    services : dict avec clés 'service_cleaning', 'service_effects',
               'service_artistic', 'service_mastering' → True/False.
    """
    return {
        'stems_file':    (io.BytesIO(b'PK\x03\x04fake zip'), 'stems.zip', 'application/zip'),
        'reference_file': (io.BytesIO(b'ID3\x00fake mp3'), 'ref.mp3',   'audio/mpeg'),
        'title':          'Test Mix/Master',
        'service_cleaning':  '1' if services.get('service_cleaning')  else '0',
        'service_effects':   '1' if services.get('service_effects')   else '0',
        'service_artistic':  '1' if services.get('service_artistic')  else '0',
        'service_mastering': '1' if services.get('service_mastering') else '0',
        'has_separated_stems': '1' if has_stems else '0',
        'success_url': 'http://localhost:4200/mix/success',
        'cancel_url':  'http://localhost:4200/mix/cancel',
    }


def _post_order(client, engineer_id, headers, services, has_stems=False):
    """POST vers /api/mixmaster-artist/order/<engineer_id> avec les mocks systèmes requis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        with patch('routes.mixmaster_api.VALIDATION_AVAILABLE', True), \
             patch('routes.mixmaster_api.validate_stems_archive',
                   return_value=(True, None), create=True), \
             patch('routes.mixmaster_api.validate_audio_file',
                   return_value=(True, None), create=True), \
             patch('routes.mixmaster_api.get_archive_file_tree', return_value=None), \
             patch('routes.mixmaster_api.log_stripe_checkout_session_created'), \
             patch('routes.mixmaster_api.config') as mock_cfg, \
             patch('stripe.checkout.Session.create') as mock_create:

            mock_cfg.MIXMASTER_UPLOADS_FOLDER = tmp_path
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')

            resp = client.post(
                f'/api/mixmaster-artist/order/{engineer_id}',
                data=_order_payload(services, has_stems),
                content_type='multipart/form-data',
                headers=headers,
            )

            unit_amt = _unit_amount(mock_create) if mock_create.called else None

    return resp, unit_amt


# ── Tests ────────────────────────────────────────────────────────────────────

class TestMixMasterCheckoutUnitAmount:
    """
    Vérifie que unit_amount (centimes) envoyé à Stripe reflète le calcul
    exact des services sélectionnés et du bonus stems.

    Ingénieur de référence : reference_price=100€, price_min=10€.
    min_pct=(10/100)*100=10 < 35 → aucun service n'est auto-forcé.
    """

    def test_cleaning_only_unit_amount(self, client, engineer, artist_headers):
        """
        service_cleaning=True → base = 100 × 35% = 35.00€.
        unit_amount attendu : 3500 centimes.
        """
        resp, unit_amt = _post_order(
            client, engineer.id, artist_headers,
            {'service_cleaning': True},
        )
        assert resp.status_code == 200, resp.data
        assert unit_amt == 3500

    def test_mastering_only_unit_amount(self, client, engineer, artist_headers):
        """
        service_mastering=True → base = 100 × 20% = 20.00€.
        unit_amount attendu : 2000 centimes.
        """
        resp, unit_amt = _post_order(
            client, engineer.id, artist_headers,
            {'service_mastering': True},
        )
        assert resp.status_code == 200, resp.data
        assert unit_amt == 2000

    def test_cleaning_effects_mastering_unit_amount(self, client, engineer, artist_headers):
        """
        cleaning+effects+mastering → base = 100 × (35+45+20)% = 100.00€.
        unit_amount attendu : 10000 centimes.
        """
        resp, unit_amt = _post_order(
            client, engineer.id, artist_headers,
            {'service_cleaning': True, 'service_effects': True, 'service_mastering': True},
        )
        assert resp.status_code == 200, resp.data
        assert unit_amt == 10000

    def test_stems_bonus_adds_20_percent(self, client, engineer, artist_headers):
        """
        cleaning + has_separated_stems=True.
        base = 100 × 35% = 35€, stems_bonus = 100 × 20% = 20€.
        total = 55.00€ → unit_amount=5500.
        """
        resp, unit_amt = _post_order(
            client, engineer.id, artist_headers,
            {'service_cleaning': True},
            has_stems=True,
        )
        assert resp.status_code == 200, resp.data
        assert unit_amt == 5500

    def test_minimum_price_floor_applied(self, client, engineer_high_min, artist_headers):
        """
        Ingénieur avec price_min=30€.
        mastering seul → base=20€ < min=30€ → total=30.00€.
        unit_amount attendu : 3000 centimes.

        Note : min_pct=(30/100)*100=30 < 35 → aucun service auto-forcé.
        """
        resp, unit_amt = _post_order(
            client, engineer_high_min.id, artist_headers,
            {'service_mastering': True},
        )
        assert resp.status_code == 200, resp.data
        assert unit_amt == 3000

    def test_minimum_not_applied_when_above(self, client, engineer, artist_headers):
        """
        Ingénieur avec price_min=10€.
        cleaning seul → base=35€ > min=10€ → min non appliqué, total=35.00€.
        unit_amount attendu : 3500 centimes (idem test_cleaning_only).
        """
        resp, unit_amt = _post_order(
            client, engineer.id, artist_headers,
            {'service_cleaning': True},
        )
        assert resp.status_code == 200, resp.data
        assert unit_amt == 3500
