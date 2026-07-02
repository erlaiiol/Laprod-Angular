"""
Tests d'intégration Stripe — page track-contract-config (modes Rapide et Avancé)

Vérifie que les paramètres transmis à stripe.checkout.Session.create() sont
corrects en termes de types, de structure et de valeurs pour les deux modes :

  • Mode Rapide (preset Starter) :
      is_exclusive=False, is_lifetime=False, duration_years=3,
      territory='France', mechanical_reproduction=False,
      public_show=False, arrangement=False
  • Mode Avancé : options complètes, y compris is_exclusive=True

Invariants testés indépendamment du mode :
  • unit_amount est un int (pas un float) — Stripe l'exige
  • currency == 'eur'
  • mode == 'payment'
  • quantity == 1
  • Toutes les valeurs de metadata sont des chaînes Python
  • Les 19 clés de metadata obligatoires sont présentes
  • success_url contient le placeholder {CHECKOUT_SESSION_ID}
  • cancel_url pointe vers /contract/{track_id}/{format}
  • La réponse JSON contient data.checkout_url (str) et data.total (nombre)
"""

import uuid
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch


# ── Constantes de test ──────────────────────────────────────────────────────────

# Prix configurés dans conftest.py
_DURATION_3Y  = 5    # CONTRACT_DURATIONS['3']
_TERRITORY_EU = 5    # CONTRACT_TERRITORY_EUROPE
_MECHANICAL   = 30   # CONTRACT_MECHANICAL_REPRODUCTION_PRICE
_PUBLIC_SHOW  = 40   # CONTRACT_PUBLIC_SHOW_PRICE
_ARRANGEMENT  = 10   # CONTRACT_ARRANGEMENT_PRICE

_PRICE_MP3    = Decimal('9.99')
_PRICE_WAV    = Decimal('14.99')
_PRICE_STEMS  = Decimal('24.99')

# Preset "Starter" = mode Rapide : streaming seul, France, 3 ans, sans options
_QUICK_MODE_BODY = {
    'is_exclusive':            False,
    'is_lifetime':             False,
    'duration_years':          3,
    'territory':               'France',
    'mechanical_reproduction': False,
    'public_show':             False,
    'arrangement':             False,
    'total_price':             float(_PRICE_MP3 + _DURATION_3Y),  # 14.99
}

# Toutes les clés attendues dans metadata
_REQUIRED_METADATA_KEYS = {
    'track_id', 'track_title', 'composer_id', 'composer_username',
    'buyer_id', 'buyer_username', 'format_type', 'is_exclusive',
    'duration_years', 'is_lifetime', 'territory', 'streaming',
    'mechanical_reproduction', 'public_show', 'arrangement',
    'buyer_address', 'buyer_email', 'track_price',
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def composer(db):
    """Beatmaker propriétaire du track."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'composer_{uid}@test.laprod.fr',
        username=f'composer_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_beatmaker=True,
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
def buyer(db):
    """Artiste qui achète la licence."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'buyer_{uid}@test.laprod.fr',
        username=f'buyer_{uid}',
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
def buyer_headers(app, buyer):
    """Headers JWT pour le buyer."""
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(buyer.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def approved_track(db, composer):
    """Track approuvé avec prix de base."""
    from models import Track
    uid = uuid.uuid4().hex[:8]
    t = Track(
        title='Starter Mode Test Track',
        composer_id=composer.id,
        file_hash=f'testhash_{uid}',
        audio_file=f'previews/preview_{uid}.mp3',
        price_mp3=_PRICE_MP3,
        price_wav=_PRICE_WAV,
        price_stems=_PRICE_STEMS,
        bpm=120,
        key='Am',
        is_approved=True,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _post_checkout(client, track_id: int, format_type: str, headers: dict, body: dict):
    """
    POST vers /api/track-payment/track/<id>/<format>/checkout avec Stripe mocké.
    Retourne (response, stripe_kwargs) — stripe_kwargs est None si Stripe n'a pas été appelé.
    """
    with patch('stripe.checkout.Session.create') as mock_create:
        mock_create.return_value = MagicMock(
            url='https://checkout.stripe.com/test_cs_abc',
            id='cs_test_abc123',
        )
        resp = client.post(
            f'/api/track-payment/track/{track_id}/{format_type}/checkout',
            json=body,
            headers=headers,
        )
        stripe_kwargs = mock_create.call_args.kwargs if mock_create.called else None

    return resp, stripe_kwargs


def _unit_amount(kwargs: dict) -> int:
    return kwargs['line_items'][0]['price_data']['unit_amount']


def _metadata(kwargs: dict) -> dict:
    return kwargs['metadata']


# ── Tests : paramètres Stripe invariants ───────────────────────────────────────

class TestStripeCheckoutInvariants:
    """
    Paramètres que Stripe exige quelle que soit la configuration choisie
    par l'utilisateur (mode Rapide ou Avancé).
    """

    def test_unit_amount_is_strict_integer(self, client, approved_track, buyer, buyer_headers):
        """
        Stripe refuse les floats dans unit_amount.
        Le backend doit toujours appeler int(server_total * 100).
        """
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert kw is not None, "stripe.checkout.Session.create n'a pas été appelé"
        assert isinstance(_unit_amount(kw), int), "unit_amount doit être un int, pas un float"

    def test_currency_is_eur(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        currency = kw['line_items'][0]['price_data']['currency']
        assert currency == 'eur'

    def test_mode_is_payment(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert kw['mode'] == 'payment'

    def test_quantity_is_1(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert kw['line_items'][0]['quantity'] == 1

    def test_customer_email_is_buyer_email(self, client, approved_track, buyer, buyer_headers):
        """customer_email doit correspondre à l'email JWT du buyer (pas un email quelconque)."""
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert kw['customer_email'] == buyer.email

    def test_success_url_contains_session_id_placeholder(self, client, approved_track, buyer, buyer_headers):
        """
        Stripe substitue {CHECKOUT_SESSION_ID} par l'ID de session dans success_url.
        Si le placeholder est absent, la redirection post-paiement ne contiendra jamais
        session_id et verify_payment() ne pourra pas récupérer la session.
        """
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert '{CHECKOUT_SESSION_ID}' in kw['success_url'], (
            f"success_url ne contient pas le placeholder Stripe : {kw['success_url']!r}"
        )

    def test_cancel_url_points_to_contract_page(self, client, approved_track, buyer, buyer_headers):
        """
        En cas d'annulation, Stripe redirige vers la page de config du contrat.
        Le format attendu est : {FRONTEND_URL}/contract/{track_id}/{format}.
        """
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        expected_suffix = f'/contract/{approved_track.id}/mp3'
        assert kw['cancel_url'].endswith(expected_suffix), (
            f"cancel_url devrait terminer par {expected_suffix!r}, "
            f"obtenu : {kw['cancel_url']!r}"
        )


# ── Tests : metadata — structure et types ──────────────────────────────────────

class TestStripeCheckoutMetadata:
    """
    Stripe n'accepte que des valeurs de type str dans metadata.
    Le verify_payment() côté Flask lit ces strings et les compare (ex: == 'True').
    Un int ou bool passé directement à Stripe lèverait une StripeInvalidRequestError.
    """

    def test_all_required_keys_present(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        meta = _metadata(kw)
        missing = _REQUIRED_METADATA_KEYS - set(meta.keys())
        assert not missing, f"Clés manquantes dans metadata : {missing}"

    def test_all_metadata_values_are_strings(self, client, approved_track, buyer, buyer_headers):
        """
        Stripe rejetterait tout type non-str dans metadata.
        Cette assertion garantit qu'aucune refactorisation future n'introduit
        accidentellement un int/bool/Decimal.
        """
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        meta = _metadata(kw)
        non_strings = {k: type(v).__name__ for k, v in meta.items() if not isinstance(v, str)}
        assert not non_strings, f"Valeurs non-str dans metadata : {non_strings}"

    def test_track_id_is_stringified_int(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        meta = _metadata(kw)
        assert meta['track_id'] == str(approved_track.id)
        assert meta['track_id'].isdigit()

    def test_buyer_id_matches_jwt_user(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        meta = _metadata(kw)
        assert meta['buyer_id'] == str(buyer.id)

    def test_streaming_is_always_true_string(self, client, approved_track, buyer, buyer_headers):
        """streaming est toujours inclus et vaut 'true' (minuscule) — convention du backend."""
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        meta = _metadata(kw)
        assert meta['streaming'] == 'true'

    def test_track_price_is_decimal_string(self, client, approved_track, buyer, buyer_headers):
        """
        track_price stocke la valeur calculée par le serveur (pas la valeur client).
        Elle doit être une représentation de Decimal parseable par Decimal().
        """
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        meta = _metadata(kw)
        from decimal import Decimal as D, InvalidOperation
        try:
            D(meta['track_price'])
        except InvalidOperation:
            pytest.fail(f"track_price n'est pas un Decimal valide : {meta['track_price']!r}")


# ── Tests : mode Rapide — valeurs metadata ──────────────────────────────────────

class TestStripeCheckoutQuickMode:
    """
    Le preset Starter (mode Rapide) envoie les valeurs les moins chères.
    Ces tests vérifient que chaque option est correctement sérialisée en string
    et transmise avec la valeur attendue dans la metadata Stripe.
    """

    def test_is_exclusive_false_string_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['is_exclusive'] == 'False'

    def test_is_lifetime_false_string_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['is_lifetime'] == 'False'

    def test_territory_france_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['territory'] == 'France'

    def test_duration_years_3_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['duration_years'] == '3'

    def test_mechanical_reproduction_false_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['mechanical_reproduction'] == 'False'

    def test_public_show_false_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['public_show'] == 'False'

    def test_arrangement_false_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['arrangement'] == 'False'

    def test_format_type_in_metadata(self, client, approved_track, buyer, buyer_headers):
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert _metadata(kw)['format_type'] == 'mp3'

    def test_response_shape_has_checkout_url(self, client, approved_track, buyer, buyer_headers):
        """La réponse doit contenir data.checkout_url (string) que Angular utilise pour la redirection."""
        resp, _ = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        assert resp.status_code == 200, resp.data
        json_data = resp.get_json()
        assert json_data['success'] is True
        assert isinstance(json_data['data']['checkout_url'], str)
        assert json_data['data']['checkout_url'].startswith('https://')

    def test_response_shape_has_total_number(self, client, approved_track, buyer, buyer_headers):
        """data.total doit être un nombre (Decimal sérialisé en float par Flask)."""
        resp, _ = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, _QUICK_MODE_BODY)
        json_data = resp.get_json()
        assert 'total' in json_data['data']
        assert isinstance(json_data['data']['total'], (int, float))


# ── Tests : mode Avancé — valeurs metadata ──────────────────────────────────────

class TestStripeCheckoutAdvancedMode:
    """
    Mode Avancé : l'utilisateur choisit des options supplémentaires.
    Vérifie que chaque option choisie est fidèlement répercutée dans metadata.
    """

    def test_is_exclusive_true_string_in_metadata(self, client, approved_track, buyer, buyer_headers):
        body = {**_QUICK_MODE_BODY, 'is_exclusive': True, 'total_price': 164.99}
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, body)
        assert _metadata(kw)['is_exclusive'] == 'True'

    def test_territory_world_in_metadata(self, client, approved_track, buyer, buyer_headers):
        price = float(_PRICE_MP3 + _DURATION_3Y + _TERRITORY_EU + _TERRITORY_EU)  # territoire monde = eu+monde
        body = {**_QUICK_MODE_BODY, 'territory': 'Monde entier', 'total_price': price}
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, body)
        assert _metadata(kw)['territory'] == 'Monde entier'

    def test_mechanical_true_string_in_metadata(self, client, approved_track, buyer, buyer_headers):
        price = float(_PRICE_MP3 + _DURATION_3Y + _MECHANICAL)
        body = {**_QUICK_MODE_BODY, 'mechanical_reproduction': True, 'total_price': price}
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, body)
        assert _metadata(kw)['mechanical_reproduction'] == 'True'

    def test_is_lifetime_true_string_in_metadata(self, client, approved_track, buyer, buyer_headers):
        lifetime_price = 50  # CONTRACT_DURATIONS['lifetime']
        price = float(_PRICE_MP3 + lifetime_price)
        body = {**_QUICK_MODE_BODY, 'is_lifetime': True, 'duration_years': 3, 'total_price': price}
        _, kw = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, body)
        assert _metadata(kw)['is_lifetime'] == 'True'

    def test_price_tampered_returns_403(self, client, approved_track, buyer, buyer_headers):
        """
        Le backend recalcule le prix côté serveur et rejette toute manipulation.
        Envoyer un total_price intentionnellement erroné doit retourner 403.
        """
        body = {**_QUICK_MODE_BODY, 'total_price': 0.01}
        resp, _ = _post_checkout(client, approved_track.id, 'mp3', buyer_headers, body)
        assert resp.status_code == 403
        assert resp.get_json()['success'] is False

    def test_wav_format_in_metadata(self, client, approved_track, buyer, buyer_headers):
        """Le format de la track achetée (mp3/wav/stems) est stocké dans metadata."""
        wav_body = {**_QUICK_MODE_BODY, 'total_price': float(_PRICE_WAV + _DURATION_3Y)}
        _, kw = _post_checkout(client, approved_track.id, 'wav', buyer_headers, wav_body)
        assert _metadata(kw)['format_type'] == 'wav'
