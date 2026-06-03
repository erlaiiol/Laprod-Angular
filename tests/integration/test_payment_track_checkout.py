"""
Tests d'intégration — calcul du prix Track envoyé à Stripe

Vérifie que unit_amount (en centimes) passé à stripe.checkout.Session.create()
reflète exactement le calcul serveur selon les options de contrat cochées.

Config de test (conftest.py) — IDENTIQUE à la production (config.py) :
  CONTRACT_EXCLUSIVE_PRICE                : 150
  CONTRACT_DURATIONS                      : {'3': 5, '5': 10, '10': 15, 'lifetime': 50}
  CONTRACT_MECHANICAL_REPRODUCTION_PRICE  : 30
  CONTRACT_PUBLIC_SHOW_PRICE              : 40
  CONTRACT_ARRANGEMENT_PRICE              : 10
  CONTRACT_TERRITORY_EUROPE               : 5
  CONTRACT_TERRITORY_WORLD                : 10
  Seuils auto-inclusion : mechanical >= 199.99€ / public_show >= 74.99€
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
        email=f'composer_chk_{uid}@test.laprod.fr',
        username=f'composer_chk_{uid}',
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
def track_standard(db, composer):
    """Track standard : price_mp3=9.99, prix de droits = défauts plateforme."""
    from models import Track
    t = Track(
        title='Checkout Test Beat',
        composer_id=composer.id,
        file_hash=str(uuid.uuid4()),
        audio_file='checkout_preview.mp3',
        bpm=140,
        key='C minor',
        is_approved=True,
        is_exclusive_sold=False,
        price_mp3=Decimal('9.99'),
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def track_with_custom_prices(db, composer):
    """Track avec prix de droits personnalisés : exclusive=500, territory_eu=20."""
    from models import Track
    t = Track(
        title='Custom Price Beat',
        composer_id=composer.id,
        file_hash=str(uuid.uuid4()),
        audio_file='custom_preview.mp3',
        bpm=140,
        key='C minor',
        is_approved=True,
        is_exclusive_sold=False,
        price_mp3=Decimal('9.99'),
        contract_price_exclusive=500,
        contract_price_territory_eu=20,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
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
        email=f'buyer_chk_{uid}@test.laprod.fr',
        username=f'buyer_chk_{uid}',
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


# ── Helper ────────────────────────────────────────────────────────────────────

def _unit_amount(mock_create) -> int:
    """Retourne unit_amount (centimes) capturé depuis l'appel à stripe.checkout.Session.create."""
    kwargs = mock_create.call_args.kwargs
    return kwargs['line_items'][0]['price_data']['unit_amount']


# ── Tests ────────────────────────────────────────────────────────────────────

class TestTrackCheckoutUnitAmount:
    """
    Chaque test couvre une option de contrat spécifique et vérifie
    que le montant transmis à Stripe (unit_amount en centimes) est exact.
    """

    def _post(self, client, track_id, headers, payload):
        return client.post(
            f'/api/track-payment/track/{track_id}/mp3/checkout',
            data=json.dumps(payload),
            headers=headers,
        )

    def test_base_price_with_3y_duration(self, client, track_standard, buyer_headers):
        """
        MP3 (9.99) + durée 3 ans (CONTRACT_DURATIONS['3']=5) + France (0) = 14.99€.
        unit_amount attendu : 1499 centimes.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 3, 'territory': 'France', 'total_price': 14.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 1499

    def test_exclusive_adds_config_price(self, client, track_standard, buyer_headers):
        """
        is_exclusive=True → +CONTRACT_EXCLUSIVE_PRICE (150).
        9.99 + 150 + 5 (3y) = 164.99€ → unit_amount=16499.
        """
        headers, _ = buyer_headers
        payload = {
            'is_exclusive': True,
            'duration_years': 3,
            'territory': 'France',
            'total_price': 164.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 16499

    def test_exclusive_uses_custom_track_price(self, client, track_with_custom_prices, buyer_headers):
        """
        track.contract_price_exclusive=500 prime sur le config (150).
        9.99 + 500 + 5 (3y) = 514.99€ → unit_amount=51499.
        """
        headers, _ = buyer_headers
        payload = {
            'is_exclusive': True,
            'duration_years': 3,
            'territory': 'France',
            'total_price': 514.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_with_custom_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 51499

    def test_territory_world_adds_fee(self, client, track_standard, buyer_headers):
        """
        territory='Monde entier' → +CONTRACT_TERRITORY_WORLD (10).
        9.99 + 5 (3y) + 10 = 24.99€ → unit_amount=2499.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 3, 'territory': 'Monde entier', 'total_price': 24.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 2499

    def test_territory_europe_adds_fee(self, client, track_standard, buyer_headers):
        """
        territory='Europe' → +CONTRACT_TERRITORY_EUROPE (5).
        9.99 + 5 (3y) + 5 = 19.99€ → unit_amount=1999.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 3, 'territory': 'Europe', 'total_price': 19.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 1999

    def test_custom_territory_eu_price(self, client, track_with_custom_prices, buyer_headers):
        """
        track.contract_price_territory_eu=20 prime sur le config (5).
        9.99 + 5 (3y) + 20 = 34.99€ → unit_amount=3499.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 3, 'territory': 'Europe', 'total_price': 34.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_with_custom_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 3499

    def test_arrangement_adds_fee(self, client, track_standard, buyer_headers):
        """
        arrangement=True → +CONTRACT_ARRANGEMENT_PRICE (10).
        9.99 + 5 (3y) + 10 = 24.99€ → unit_amount=2499.
        """
        headers, _ = buyer_headers
        payload = {
            'arrangement': True,
            'duration_years': 3,
            'territory': 'France',
            'total_price': 24.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 2499

    def test_mechanical_added_below_threshold(self, client, track_standard, buyer_headers):
        """
        mechanical_reproduction=True et intermediate < 199.99 → +CONTRACT_MECHANICAL_PRICE (30).
        intermediate = 9.99 + 5 (3y) = 14.99 < 199.99 → mécanique ajouté.
        total = 9.99 + 5 + 30 = 44.99€ → unit_amount=4499.
        """
        headers, _ = buyer_headers
        payload = {
            'mechanical_reproduction': True,
            'duration_years': 3,
            'territory': 'France',
            'total_price': 44.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 4499

    def test_mechanical_not_added_above_threshold(self, client, track_with_custom_prices, buyer_headers):
        """
        mechanical_reproduction=True mais intermediate >= 199.99 → droit auto-inclus, aucun surcoût.
        exclusive=500 → intermediate = 9.99 + 500 + 5 (3y) = 514.99 >= 199.99 → mécanique non ajouté.
        total = 514.99€ → unit_amount=51499 (identique sans mechanical).
        """
        headers, _ = buyer_headers
        payload = {
            'is_exclusive': True,
            'mechanical_reproduction': True,
            'duration_years': 3,
            'territory': 'France',
            'total_price': 514.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_with_custom_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 51499

    def test_price_tampered_returns_403(self, client, track_standard, buyer_headers):
        """
        Client envoie total_price=1.00 alors que le serveur calcule 14.99€ (9.99 + 5).
        Écart > 0.01€ → 403 PRICE_TAMPERED, Stripe n'est pas appelé.
        """
        headers, _ = buyer_headers
        payload = {
            'duration_years': 3,
            'territory': 'France',
            'total_price': 1.00,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            resp = self._post(client, track_standard.id, headers, payload)

        assert resp.status_code == 403
        assert resp.json['code'] == 'PRICE_TAMPERED'
        mock_create.assert_not_called()
