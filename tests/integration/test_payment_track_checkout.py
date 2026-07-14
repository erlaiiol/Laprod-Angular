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

from tests.factories import bound_factories  # noqa: F401
from tests.scenarios.users import user_free  # noqa: F401
from tests.scenarios.tracks import track_default_prices  # noqa: F401


# ── Fixtures locales ──────────────────────────────────────────────────────────

@pytest.fixture()
def track_with_custom_prices(db, user_free):
    """Track avec prix de droits personnalisés : exclusive=500, territory_eu=20."""
    from models import Track
    t = Track(
        title='Custom Price Beat',
        composer_id=user_free.id,
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
        # Consentement (legal_terms_accepted / withdrawal_right_waived) injecté
        # par défaut : ces tests couvrent le calcul de prix, pas le consentement
        # (cf. TestCheckoutConsentValidation pour ce dernier). `**payload` après
        # les défauts permet à un test de les surcharger explicitement.
        payload = {'legal_terms_accepted': True, 'withdrawal_right_waived': True, **payload}
        return client.post(
            f'/api/track-payment/track/{track_id}/mp3/checkout',
            data=json.dumps(payload),
            headers=headers,
        )

    def test_base_price_with_10y_duration(self, client, track_default_prices, buyer_headers):
        """
        MP3 (9.99) + durée 10 ans (CONTRACT_DURATIONS['10']=15) + France (0) = 24.99€.
        unit_amount attendu : 2499 centimes.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 10, 'territory': 'France', 'total_price': 24.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 2499

    def test_exclusive_adds_config_price(self, client, track_default_prices, buyer_headers):
        """
        is_exclusive=True → +CONTRACT_EXCLUSIVE_PRICE (150).
        9.99 + 150 + 15 (10y) = 174.99€ → unit_amount=17499.
        """
        headers, _ = buyer_headers
        payload = {
            'is_exclusive': True,
            'duration_years': 10,
            'territory': 'France',
            'total_price': 174.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 17499

    def test_exclusive_uses_custom_track_price(self, client, track_with_custom_prices, buyer_headers):
        """
        track.contract_price_exclusive=500 prime sur le config (150).
        9.99 + 500 + 15 (10y) = 524.99€ → unit_amount=52499.
        """
        headers, _ = buyer_headers
        payload = {
            'is_exclusive': True,
            'duration_years': 10,
            'territory': 'France',
            'total_price': 524.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_with_custom_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 52499

    def test_territory_world_adds_fee(self, client, track_default_prices, buyer_headers):
        """
        territory='Monde entier' → +CONTRACT_TERRITORY_WORLD (10).
        9.99 + 15 (10y) + 10 = 34.99€ → unit_amount=3499.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 10, 'territory': 'Monde entier', 'total_price': 34.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 3499

    def test_territory_europe_adds_fee(self, client, track_default_prices, buyer_headers):
        """
        territory='Europe' → +CONTRACT_TERRITORY_EUROPE (5).
        9.99 + 15 (10y) + 5 = 29.99€ → unit_amount=2999.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 10, 'territory': 'Europe', 'total_price': 29.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 2999

    def test_custom_territory_eu_price(self, client, track_with_custom_prices, buyer_headers):
        """
        track.contract_price_territory_eu=20 prime sur le config (5).
        9.99 + 15 (10y) + 20 = 44.99€ → unit_amount=4499.
        """
        headers, _ = buyer_headers
        payload = {'duration_years': 10, 'territory': 'Europe', 'total_price': 44.99}

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_with_custom_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 4499

    def test_arrangement_adds_fee(self, client, track_default_prices, buyer_headers):
        """
        arrangement=True → +CONTRACT_ARRANGEMENT_PRICE (10).
        9.99 + 15 (10y) + 10 = 34.99€ → unit_amount=3499.
        """
        headers, _ = buyer_headers
        payload = {
            'arrangement': True,
            'duration_years': 10,
            'territory': 'France',
            'total_price': 34.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 3499

    def test_mechanical_added_below_threshold(self, client, track_default_prices, buyer_headers):
        """
        mechanical_reproduction=True et intermediate < 199.99 → +CONTRACT_MECHANICAL_PRICE (30).
        intermediate = 9.99 + 15 (10y) = 24.99 < 199.99 → mécanique ajouté.
        total = 9.99 + 15 + 30 = 54.99€ → unit_amount=5499.
        """
        headers, _ = buyer_headers
        payload = {
            'mechanical_reproduction': True,
            'duration_years': 10,
            'territory': 'France',
            'total_price': 54.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 5499

    def test_mechanical_not_added_above_threshold(self, client, track_with_custom_prices, buyer_headers):
        """
        mechanical_reproduction=True mais intermediate >= 199.99 → droit auto-inclus, aucun surcoût.
        exclusive=500 → intermediate = 9.99 + 500 + 15 (10y) = 524.99 >= 199.99 → mécanique non ajouté.
        total = 524.99€ → unit_amount=52499 (identique sans mechanical).
        """
        headers, _ = buyer_headers
        payload = {
            'is_exclusive': True,
            'mechanical_reproduction': True,
            'duration_years': 10,
            'territory': 'France',
            'total_price': 524.99,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_with_custom_prices.id, headers, payload)

        assert resp.status_code == 200
        assert _unit_amount(mock_create) == 52499

    def test_price_tampered_returns_403(self, client, track_default_prices, buyer_headers):
        """
        Client envoie total_price=1.00 alors que le serveur calcule 24.99€ (9.99 + 15).
        Écart > 0.01€ → 403 PRICE_TAMPERED, Stripe n'est pas appelé.
        """
        headers, _ = buyer_headers
        payload = {
            'duration_years': 10,
            'territory': 'France',
            'total_price': 1.00,
        }

        with patch('stripe.checkout.Session.create') as mock_create:
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 403
        assert resp.json['code'] == 'PRICE_TAMPERED'
        mock_create.assert_not_called()


class TestCheckoutConsentValidation:
    """
    legal_terms_accepted et withdrawal_right_waived sont deux actes de
    consentement distincts et obligatoires (cf. routes/payment_track_api.py).
    """

    def _post(self, client, track_id, headers, payload):
        return client.post(
            f'/api/track-payment/track/{track_id}/mp3/checkout',
            data=json.dumps(payload),
            headers=headers,
        )

    def test_missing_legal_terms_accepted_returns_400(self, client, track_default_prices, buyer_headers):
        headers, _ = buyer_headers
        payload = {
            'duration_years': 10, 'territory': 'France', 'total_price': 24.99,
            'withdrawal_right_waived': True,
        }
        with patch('stripe.checkout.Session.create') as mock_create:
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 400
        assert resp.json['code'] == 'LEGAL_TERMS_REQUIRED'
        mock_create.assert_not_called()

    def test_missing_withdrawal_waiver_returns_400(self, client, track_default_prices, buyer_headers):
        headers, _ = buyer_headers
        payload = {
            'duration_years': 10, 'territory': 'France', 'total_price': 24.99,
            'legal_terms_accepted': True,
        }
        with patch('stripe.checkout.Session.create') as mock_create:
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 400
        assert resp.json['code'] == 'WITHDRAWAL_WAIVER_REQUIRED'
        mock_create.assert_not_called()

    def test_consent_flags_included_in_stripe_metadata(self, client, track_default_prices, buyer_headers):
        headers, _ = buyer_headers
        payload = {
            'duration_years': 10, 'territory': 'France', 'total_price': 24.99,
            'legal_terms_accepted': True, 'withdrawal_right_waived': True,
            'buyer_declares_original_lyrics': True,
        }
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test')
            resp = self._post(client, track_default_prices.id, headers, payload)

        assert resp.status_code == 200
        metadata = mock_create.call_args.kwargs['metadata']
        assert metadata['legal_terms_accepted'] == 'True'
        assert metadata['withdrawal_right_waived'] == 'True'
        assert metadata['buyer_declares_original_lyrics'] == 'True'
