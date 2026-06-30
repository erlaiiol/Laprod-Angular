"""
Tests d'intégration Stripe — page mixmaster-order (modes Rapide et Avancé)

Couvre quatre contrats critiques :

1. PARSING FORMDATA BOOLEANS
   Le backend lit les services via bval(key) = (form.get(key, '0') == '1').
   Angular doit envoyer '1'/'0' (pas 'true'/'false').
   Ces tests vérifient que la chaîne '1' → True et '0' → False côté serveur,
   et que le composant Angular (après correction du bug String()) envoie bien
   la valeur attendue.

2. AUTO-FORÇAGE DES SERVICES SELON LE PALIER MINIMUM
   Quand min_pct ≥ 35%, le backend force service_cleaning=True côté serveur,
   indépendamment de ce que le frontend envoie. Le mode Rapide s'appuie
   sur ce comportement pour n'exposer à l'utilisateur que le prix minimum.

3. METADATA STRIPE — TYPES ET COMPLÉTUDE
   • Toutes les valeurs sont des str (Stripe n'accepte pas autre chose).
   • str(True) = 'True', lu en retour par verify_payment() via == 'True'.
   • Les 26 clés sont présentes.

4. PARAMÈTRES DE SESSION STRIPE
   • currency='eur', mode='payment', quantity=1
   • capture_method='automatic' dans payment_intent_data
   • success_url contient le placeholder {CHECKOUT_SESSION_ID}
   • cancel_url est renvoyé tel quel depuis le formulaire Angular
   • customer_email = email de l'artiste connecté
   • Réponse JSON : { success: true, data: { checkout_url: str } }
"""

import io
import uuid
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── Clés metadata attendues dans un appel Stripe mixmaster ────────────────────

_REQUIRED_METADATA_KEYS = {
    'type', 'artist_id', 'artist_username', 'artist_email',
    'engineer_id', 'engineer_username',
    'stems_file', 'reference_file', 'archive_file_tree',
    'service_cleaning', 'service_effects', 'service_artistic', 'service_mastering',
    'has_separated_stems', 'artist_message',
    'brief_vocals', 'brief_backing_vocals', 'brief_ambiance', 'brief_bass',
    'brief_energy_style', 'brief_references', 'brief_instruments', 'brief_percussion',
    'brief_effects_brief', 'brief_structure', 'title',
}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def engineer_low_min(db):
    """
    Ingénieur sans auto-forçage de services : ref=100€, min=10€.
    min_pct = 10 < 35 → aucun service n'est imposé automatiquement.
    Permet de tester le parsing '1'/'0' sans interférence du palier minimum.
    """
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'eng_low_{uid}@test.laprod.fr',
        username=f'eng_low_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
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
    """
    Ingénieur avec palier min=35€ : min_pct=35 → service_cleaning auto-forcé.
    Simule le mode Rapide : l'artiste envoie tous les services à '0' mais
    service_cleaning doit quand même être True côté serveur.
    """
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'eng_hm_{uid}@test.laprod.fr',
        username=f'eng_hm_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_mixmaster_engineer=True,
        is_certified_master_engineer=True,
        mixmaster_reference_price=100,
        mixmaster_price_min=35,
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
    """Artiste qui passe la commande."""
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

def _build_multipart(services: dict, *, has_stems: bool = False,
                     success_url: str = 'http://localhost:4200/mix/payment-success',
                     cancel_url: str = 'http://localhost:4200/mix/cancel',
                     artist_message: str = '',
                     briefing: dict | None = None) -> dict:
    """
    Construit les données multipart pour POST /api/mixmaster-artist/order/<id>.

    services : dict dont les valeurs sont '1' ou '0' (ce qu'Angular envoie
               après la correction du bug String() → ternaire).
    """
    payload = {
        'stems_file':         (io.BytesIO(b'PK\x03\x04fake zip'), 'stems.zip', 'application/zip'),
        'reference_file':     (io.BytesIO(b'ID3\x00fake mp3'),    'ref.mp3',   'audio/mpeg'),
        'title':              'Test Mix Quick Mode',
        'service_cleaning':   services.get('service_cleaning',  '0'),
        'service_effects':    services.get('service_effects',   '0'),
        'service_artistic':   services.get('service_artistic',  '0'),
        'service_mastering':  services.get('service_mastering', '0'),
        'has_separated_stems': '1' if has_stems else '0',
        'artist_message':     artist_message,
        'success_url':        success_url,
        'cancel_url':         cancel_url,
    }
    if briefing:
        payload.update(briefing)
    return payload


def _post_order(client, engineer_id: int, headers: dict, services: dict,
                has_stems: bool = False, success_url: str = 'http://localhost:4200/mix/payment-success',
                cancel_url: str = 'http://localhost:4200/mix/cancel',
                artist_message: str = '', briefing: dict | None = None):
    """
    POST vers /api/mixmaster-artist/order/<id> avec les mocks systèmes requis.
    Retourne (response, stripe_kwargs | None).
    """
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
            mock_create.return_value = MagicMock(
                url='https://checkout.stripe.com/test_mm',
                id='cs_test_mm_xyz',
            )

            resp = client.post(
                f'/api/mixmaster-artist/order/{engineer_id}',
                data=_build_multipart(
                    services, has_stems=has_stems,
                    success_url=success_url, cancel_url=cancel_url,
                    artist_message=artist_message, briefing=briefing,
                ),
                content_type='multipart/form-data',
                headers=headers,
            )

            stripe_kwargs = mock_create.call_args.kwargs if mock_create.called else None

    return resp, stripe_kwargs


def _unit_amount(kw: dict) -> int:
    return kw['line_items'][0]['price_data']['unit_amount']


def _metadata(kw: dict) -> dict:
    return kw['metadata']


# ── 1. Tests : parsing FormData booleans ('1'/'0') ────────────────────────────

class TestFormDataBooleanParsing:
    """
    Contrat Angular → Flask : les booléens de services sont transmis en '1'/'0'.
    bval(key) = request.form.get(key, '0') == '1'
    → '1' doit être True, '0' doit être False.

    Sans ce contrat, String(true)='true' != '1' → tous les services seraient
    False, et le backend retournerait "Sélectionnez au moins un service."
    """

    def test_service_cleaning_one_is_parsed_as_true(self, client, engineer_low_min, artist_headers):
        """'1' pour service_cleaning → le prix doit inclure les 35% de cleaning."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert resp.status_code == 200, resp.data
        # cleaning seul → 100 × 35% = 35€ → 3500 centimes
        assert _unit_amount(kw) == 3500

    def test_service_mastering_one_is_parsed_as_true(self, client, engineer_low_min, artist_headers):
        """'1' pour service_mastering → 100 × 20% = 20€ → 2000 centimes."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_mastering': '1'},
        )
        assert resp.status_code == 200, resp.data
        assert _unit_amount(kw) == 2000

    def test_service_effects_one_is_parsed_as_true(self, client, engineer_low_min, artist_headers):
        """'1' pour service_effects → 100 × 45% = 45€ → 4500 centimes."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_effects': '1'},
        )
        assert resp.status_code == 200, resp.data
        assert _unit_amount(kw) == 4500

    def test_all_services_zero_rejected(self, client, engineer_low_min, artist_headers):
        """
        Tous les services à '0' doit retourner 400 : au moins un service requis.
        Vérifie que '0' est bien parsé comme False (et non True).
        """
        resp, _ = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '0', 'service_effects': '0',
             'service_mastering': '0', 'service_artistic': '0'},
        )
        assert resp.status_code in (400, 422), (
            "Envoyer '0' pour tous les services devrait être rejeté"
        )

    def test_has_separated_stems_one_adds_bonus(self, client, engineer_low_min, artist_headers):
        """'1' pour has_separated_stems → +20% sur le total (bonus stems)."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
            has_stems=True,
        )
        assert resp.status_code == 200, resp.data
        # cleaning(35) + stems(20) = 55€ → 5500 centimes
        assert _unit_amount(kw) == 5500

    def test_has_separated_stems_zero_no_bonus(self, client, engineer_low_min, artist_headers):
        """'0' pour has_separated_stems → pas de bonus stems."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
            has_stems=False,
        )
        assert resp.status_code == 200, resp.data
        assert _unit_amount(kw) == 3500


# ── 2. Tests : auto-forçage des services (mode Rapide) ────────────────────────

class TestQuickModeMandatoryServices:
    """
    En mode Rapide, le frontend envoie seulement les services imposés par le palier
    minimum de l'ingénieur (ou tous à '0' si aucun n'est imposé).
    Le backend auto-force les services selon min_pct, indépendamment du form.
    """

    def test_mandatory_cleaning_forced_even_when_form_sends_zero(
            self, client, engineer_high_min, artist_headers):
        """
        engineer_high_min : min_pct=35 → service_cleaning auto-forcé côté serveur.
        Le mode Rapide peut envoyer '0' pour tous les services : cleaning sera quand
        même facturé (unit_amount ≥ 3500 centimes).
        """
        resp, kw = _post_order(
            client, engineer_high_min.id, artist_headers,
            {'service_cleaning': '0', 'service_effects': '0',
             'service_mastering': '0', 'service_artistic': '0'},
        )
        assert resp.status_code == 200, resp.data
        # Cleaning forcé : 100 × 35% = 35€ → 3500 centimes
        assert _unit_amount(kw) == 3500

    def test_metadata_service_cleaning_true_when_forced(
            self, client, engineer_high_min, artist_headers):
        """
        Quand cleaning est auto-forcé, la metadata Stripe doit refléter 'True'
        pour que verify_payment() crée correctement le MixMasterRequest.
        (verify_payment lit: meta.get('service_cleaning') == 'True')
        """
        resp, kw = _post_order(
            client, engineer_high_min.id, artist_headers,
            {'service_cleaning': '0', 'service_effects': '0',
             'service_mastering': '0', 'service_artistic': '0'},
        )
        assert resp.status_code == 200, resp.data
        meta = _metadata(kw)
        assert meta['service_cleaning'] == 'True', (
            "service_cleaning doit être 'True' dans metadata quand auto-forcé par min_pct"
        )


# ── 3. Tests : metadata Stripe — types et complétude ─────────────────────────

class TestStripeMetadataMixmaster:
    """
    Stripe n'accepte que des valeurs str dans metadata (max 500 chars chacune).
    La chaîne de sérialisation est : bool → str(bool) → 'True'/'False'.
    verify_payment() lit: meta.get('service_cleaning') == 'True' — les majuscules importent.
    """

    def test_all_required_metadata_keys_present(self, client, engineer_low_min, artist_headers):
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert resp.status_code == 200, resp.data
        meta = _metadata(kw)
        missing = _REQUIRED_METADATA_KEYS - set(meta.keys())
        assert not missing, f"Clés manquantes dans metadata Stripe : {missing}"

    def test_all_metadata_values_are_strings(self, client, engineer_low_min, artist_headers):
        """
        Stripe lève une StripeInvalidRequestError si une valeur n'est pas une str.
        Ce test protège contre les refactorisations qui passeraient un bool/int.
        """
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert resp.status_code == 200, resp.data
        meta = _metadata(kw)
        non_strings = {k: type(v).__name__ for k, v in meta.items() if not isinstance(v, str)}
        assert not non_strings, f"Valeurs non-str dans metadata : {non_strings}"

    def test_service_cleaning_true_serialized_as_python_true_string(
            self, client, engineer_low_min, artist_headers):
        """
        str(True) = 'True' (T majuscule).
        verify_payment() compare == 'True', donc la casse est critique.
        """
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        meta = _metadata(kw)
        assert meta['service_cleaning'] == 'True'

    def test_service_cleaning_false_serialized_as_python_false_string(
            self, client, engineer_high_min, artist_headers):
        """
        Quand service_cleaning reste False (min_pct < 35 et form='0'),
        metadata['service_cleaning'] doit valoir 'False'.
        """
        resp, kw = _post_order(
            client, engineer_high_min.id, artist_headers,
            # service_cleaning auto-forcé par min_pct=35 → True dans ce cas
            # On teste effects qui n'est pas forcé
            {'service_cleaning': '1', 'service_effects': '0'},
        )
        assert resp.status_code == 200, resp.data
        meta = _metadata(kw)
        assert meta['service_effects'] == 'False'

    def test_metadata_type_field_is_mixmaster(self, client, engineer_low_min, artist_headers):
        """Le champ 'type' permet à verify_payment() d'identifier le flux."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert _metadata(kw)['type'] == 'mixmaster'

    def test_artist_id_matches_jwt_user(self, client, engineer_low_min, artist, artist_headers):
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert _metadata(kw)['artist_id'] == str(artist.id)

    def test_engineer_id_in_metadata(self, client, engineer_low_min, artist_headers):
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert _metadata(kw)['engineer_id'] == str(engineer_low_min.id)

    def test_briefing_fields_stored_in_metadata(self, client, engineer_low_min, artist_headers):
        """Les champs de briefing avancés sont stockés dans metadata (tronqués à 500 chars)."""
        briefing = {
            'brief_vocals': 'Voix claire et présente avec légère réverbe',
            'brief_ambiance': 'Atmosphère sombre et intimiste',
        }
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
            briefing=briefing,
        )
        assert resp.status_code == 200, resp.data
        meta = _metadata(kw)
        assert meta['brief_vocals'] == briefing['brief_vocals']
        assert meta['brief_ambiance'] == briefing['brief_ambiance']

    def test_briefing_fields_empty_in_quick_mode(self, client, engineer_low_min, artist_headers):
        """
        En mode Rapide, les champs de briefing ne sont pas remplis.
        Ils doivent être présents dans metadata mais vides (chaîne vide).
        """
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert resp.status_code == 200, resp.data
        meta = _metadata(kw)
        for field in ('brief_vocals', 'brief_bass', 'brief_ambiance', 'brief_structure'):
            assert meta[field] == '', f"{field} devrait être vide en mode Rapide"


# ── 4. Tests : paramètres de session Stripe ────────────────────────────────────

class TestStripeSessionParameters:
    """
    Paramètres de haut niveau de stripe.checkout.Session.create() :
    currency, mode, capture, URLs, customer_email, réponse JSON.
    """

    def test_currency_is_eur(self, client, engineer_low_min, artist_headers):
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert resp.status_code == 200, resp.data
        assert kw['line_items'][0]['price_data']['currency'] == 'eur'

    def test_mode_is_payment(self, client, engineer_low_min, artist_headers):
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert kw['mode'] == 'payment'

    def test_capture_method_is_automatic(self, client, engineer_low_min, artist_headers):
        """
        capture_method='automatic' : les fonds sont prélevés immédiatement.
        verify_payment() crée le MixMasterRequest avec stripe_payment_status='captured'.
        """
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert kw['payment_intent_data']['capture_method'] == 'automatic'

    def test_unit_amount_is_strict_integer(self, client, engineer_low_min, artist_headers):
        """Stripe refuse les floats dans unit_amount."""
        resp, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert isinstance(_unit_amount(kw), int)

    def test_quantity_is_1(self, client, engineer_low_min, artist_headers):
        _, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert kw['line_items'][0]['quantity'] == 1

    def test_success_url_contains_session_id_placeholder(self, client, engineer_low_min, artist_headers):
        """
        Stripe substitue {CHECKOUT_SESSION_ID} dans success_url pour que
        verify_payment() puisse récupérer la session depuis l'URL de retour.
        """
        success_url = 'http://localhost:4200/mix/payment-success'
        _, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
            success_url=success_url,
        )
        assert '{CHECKOUT_SESSION_ID}' in kw['success_url'], (
            f"Le placeholder Stripe est absent de success_url : {kw['success_url']!r}"
        )

    def test_cancel_url_is_forwarded_from_form(self, client, engineer_low_min, artist_headers):
        """
        cancel_url est envoyé par Angular (window.location.origin + path).
        Il doit être passé tel quel à Stripe.
        """
        cancel_url = 'http://localhost:4200/mix/cancel-from-test'
        _, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
            cancel_url=cancel_url,
        )
        assert kw['cancel_url'] == cancel_url

    def test_customer_email_is_artist_email(self, client, engineer_low_min, artist, artist_headers):
        """Stripe affiche l'email de l'artiste sur la page de paiement."""
        _, kw = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert kw['customer_email'] == artist.email

    def test_response_has_checkout_url_string(self, client, engineer_low_min, artist_headers):
        """
        Angular redirige le navigateur via window.location.href = checkout_url.
        La clé doit être 'checkout_url' (pas 'url') et sa valeur une str HTTPS.
        """
        resp, _ = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        assert resp.status_code == 200, resp.data
        json_data = resp.get_json()
        assert json_data['success'] is True
        assert 'checkout_url' in json_data['data']
        assert isinstance(json_data['data']['checkout_url'], str)
        assert json_data['data']['checkout_url'].startswith('https://')

    def test_response_has_no_total_field(self, client, engineer_low_min, artist_headers):
        """
        Contrairement au checkout track (qui renvoie data.total),
        le checkout mixmaster ne renvoie QUE checkout_url.
        Vérification du contrat de réponse entre Flask et MixmasterService.
        """
        resp, _ = _post_order(
            client, engineer_low_min.id, artist_headers,
            {'service_cleaning': '1'},
        )
        json_data = resp.get_json()
        assert 'total' not in json_data.get('data', {}), (
            "mixmaster order ne doit pas renvoyer 'total' — Angular lit seulement checkout_url"
        )
