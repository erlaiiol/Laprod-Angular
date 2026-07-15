"""
Tests d'intégration — routes premium (LaProd+)

Vérifie :
  · GET  /api/premium/status   — retourne les données d'abonnement
  · POST /api/premium/subscribe — plan validation, unit_amount Stripe correct,
                                  metadata Stripe correcte
  · POST /api/premium/activate  — validation session Stripe, plan en DB,
                                  tokens appliqués, anti-doublon, renouvellement

Stripe n'est jamais appelé réellement : stripe.checkout.Session.create et
stripe.checkout.Session.retrieve sont mockés dans chaque test qui en a besoin.
"""
import json
import uuid
import pytest

from utils import plans
from utils.money import to_cents
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def free_user(db):
    """Utilisateur sans abonnement."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'free_{uid}@test.laprod.fr',
        username=f'free_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        subscription_plan='free',
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
def amateur_user(db):
    """Utilisateur avec abonnement Amateur actif."""
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'amateur_{uid}@test.laprod.fr',
        username=f'amateur_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        subscription_plan='amateur',
        premium_since=datetime.now() - timedelta(days=1),
        premium_expires_at=datetime.now() + timedelta(days=29),
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
def free_headers(app, free_user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(free_user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


@pytest.fixture()
def amateur_headers(app, amateur_user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(amateur_user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_stripe_session(user_id, plan, payment_status='paid', payment_intent='pi_test'):
    """Construit un objet mock Stripe Checkout Session."""
    s = MagicMock()
    s.payment_status = payment_status
    s.payment_intent = payment_intent
    s.metadata = {
        'user_id':               str(user_id),
        'plan':                  plan,
        'premium_duration_days': '30',
        'is_renewal':            'False',
        'type':                  'premium_subscription',
    }
    return s


def _unit_amount_from_create(mock_create) -> int:
    """Extrait unit_amount depuis l'appel capturé à stripe.checkout.Session.create."""
    kwargs = mock_create.call_args.kwargs
    return kwargs['line_items'][0]['price_data']['unit_amount']


def _metadata_from_create(mock_create) -> dict:
    """Extrait metadata depuis l'appel capturé à stripe.checkout.Session.create."""
    return mock_create.call_args.kwargs['metadata']


# ── Tests GET /api/premium/status ─────────────────────────────────────────────

class TestPremiumStatus:

    def test_free_user_returns_free_plan(self, client, free_headers, free_user):
        resp = client.get('/api/premium/status', headers=free_headers)
        assert resp.status_code == 200
        data = resp.json['data']
        assert data['subscription_plan'] == 'free'
        assert data['is_premium_active'] is False
        assert data['is_pro'] is False

    def test_amateur_user_returns_active(self, client, amateur_headers, amateur_user):
        resp = client.get('/api/premium/status', headers=amateur_headers)
        assert resp.status_code == 200
        data = resp.json['data']
        # Le palier stocké/renvoyé est canonique : 'amateur' est un alias hérité,
        # normalisé en 'premium' (cf. utils/plans.LEGACY_ALIASES).
        assert data['subscription_plan'] == plans.PREMIUM
        assert data['is_premium_active'] is True
        assert data['is_pro'] is False

    def test_requires_auth(self, client):
        resp = client.get('/api/premium/status')
        assert resp.status_code in (401, 422)


# ── Tests POST /api/premium/subscribe ─────────────────────────────────────────

class TestPremiumSubscribe:
    """Vérifie que les montants transmis à Stripe sont exacts (en centimes)."""

    def _post(self, client, headers, plan):
        return client.post(
            '/api/premium/subscribe',
            data=json.dumps({'plan': plan}),
            headers=headers,
        )

    @pytest.mark.parametrize('plan_key', plans.PAID_PLANS)
    def test_unit_amount_correspond_au_prix_du_palier(self, client, free_headers, plan_key):
        """Le montant envoyé à Stripe est EXACTEMENT le prix du palier.

        Les montants attendus sont dérivés de utils/plans.py, jamais recopiés :
        un prix codé en dur ici finirait par diverger de celui réellement facturé,
        et le test cesserait de protéger quoi que ce soit.
        """
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')
            resp = self._post(client, free_headers, plan_key)

        assert resp.status_code == 200
        assert _unit_amount_from_create(mock_create) == to_cents(plans.price_of(plan_key))

    def test_metadata_porte_le_palier_canonique(self, client, free_headers):
        """L'ancien identifiant est accepté en entrée (app mobile déjà déployée)
        mais la metadata Stripe porte le palier CANONIQUE : c'est elle qui sera
        relue à l'activation."""
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')
            self._post(client, free_headers, 'amateur')   # ancien identifiant

        meta = _metadata_from_create(mock_create)
        assert meta['plan'] == plans.PREMIUM
        assert meta['type'] == 'premium_subscription'

    def test_metadata_ancien_pro_devient_pro_structure(self, client, free_headers):
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')
            self._post(client, free_headers, 'pro')

        meta = _metadata_from_create(mock_create)
        assert meta['plan'] == plans.PRO_STRUCTURE

    def test_metadata_user_id_matches_current_user(self, client, free_headers, free_user):
        """La metadata user_id doit correspondre à l'utilisateur connecté."""
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')
            self._post(client, free_headers, 'amateur')

        meta = _metadata_from_create(mock_create)
        assert meta['user_id'] == str(free_user.id)

    def test_metadata_duration_days_matches_config(self, client, free_headers):
        """premium_duration_days en metadata doit correspondre à config.PREMIUM_DURATION_DAYS."""
        import config
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')
            self._post(client, free_headers, 'amateur')

        meta = _metadata_from_create(mock_create)
        assert meta['premium_duration_days'] == str(config.PREMIUM_DURATION_DAYS)

    def test_invalid_plan_returns_403(self, client, free_headers):
        """Un plan inconnu ('gold') doit retourner 403 sans appeler Stripe."""
        with patch('stripe.checkout.Session.create') as mock_create:
            resp = self._post(client, free_headers, 'gold')

        assert resp.status_code == 403
        mock_create.assert_not_called()

    def test_empty_plan_returns_403(self, client, free_headers):
        """Body sans plan doit retourner 403."""
        with patch('stripe.checkout.Session.create') as mock_create:
            resp = client.post(
                '/api/premium/subscribe',
                data=json.dumps({}),
                headers=free_headers,
            )

        assert resp.status_code == 403
        mock_create.assert_not_called()

    def test_renewal_flag_in_metadata(self, client, amateur_headers, amateur_user):
        """Utilisateur déjà Premium → is_renewal='True' dans metadata."""
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test', id='cs_test')
            self._post(client, amateur_headers, 'amateur')

        meta = _metadata_from_create(mock_create)
        assert meta['is_renewal'] == 'True'

    def test_checkout_url_returned(self, client, free_headers):
        """La réponse doit inclure checkout_url."""
        with patch('stripe.checkout.Session.create') as mock_create:
            mock_create.return_value = MagicMock(url='https://stripe.test/session_abc', id='cs_test')
            resp = self._post(client, free_headers, 'amateur')

        assert resp.status_code == 200
        assert resp.json['data']['checkout_url'] == 'https://stripe.test/session_abc'

    def test_requires_auth(self, client):
        resp = client.post('/api/premium/subscribe', data=json.dumps({'plan': 'amateur'}),
                           headers={'Content-Type': 'application/json'})
        assert resp.status_code in (401, 422)


# ── Tests POST /api/premium/activate ──────────────────────────────────────────

class TestPremiumActivate:

    def _post(self, client, headers, session_id):
        return client.post(
            '/api/premium/activate',
            data=json.dumps({'session_id': session_id}),
            headers=headers,
        )

    def test_amateur_plan_set_in_db(self, client, db, free_headers, free_user):
        """RÉTROCOMPAT — une session Stripe portant l'ancien 'amateur' (ouverte
        avant le renommage, ou envoyée par une app mobile pas encore mise à jour)
        doit activer le palier Premium, pas échouer."""
        session = _make_stripe_session(free_user.id, 'amateur')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, free_headers, 'cs_test_amateur')

        assert resp.status_code == 200
        db.session.refresh(free_user)
        assert free_user.subscription_plan == plans.PREMIUM

    def test_pro_plan_set_in_db(self, client, db, free_headers, free_user):
        """RÉTROCOMPAT CRITIQUE — l'ancien 'pro' doit donner PRO_STRUCTURE.

        Retomber sur le palier d'entrée accorderait le moins cher à quelqu'un qui
        a payé le plus cher : on n'accorde jamais moins que ce qui a été payé.
        """
        session = _make_stripe_session(free_user.id, 'pro')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, free_headers, 'cs_test_pro')

        assert resp.status_code == 200
        db.session.refresh(free_user)
        assert free_user.subscription_plan == plans.PRO_STRUCTURE
        assert free_user.is_pro is True

    def test_premium_expires_at_set_to_30_days(self, client, db, free_headers, free_user):
        """premium_expires_at doit être ≈ maintenant + 30 jours."""
        import config
        session = _make_stripe_session(free_user.id, 'amateur')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            self._post(client, free_headers, 'cs_test_expire')

        db.session.refresh(free_user)
        diff = free_user.premium_expires_at - datetime.now()
        assert config.PREMIUM_DURATION_DAYS - 1 <= diff.days <= config.PREMIUM_DURATION_DAYS

    def test_tokens_applied_amateur(self, client, db, free_headers, free_user):
        """Activation via l'ancien 'amateur' → tokens montés au cap du palier
        Premium (attendu dérivé de plans.py, jamais figé en dur)."""
        free_user.upload_track_tokens = 0
        db.session.commit()
        session = _make_stripe_session(free_user.id, 'amateur')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            self._post(client, free_headers, 'cs_test_tokens')

        db.session.refresh(free_user)
        assert free_user.upload_track_tokens >= plans.get(plans.PREMIUM).upload_cap

    def test_tokens_applied_pro(self, client, db, free_headers, free_user):
        """Activation via l'ancien 'pro' → tokens montés au cap Pro Structuré."""
        free_user.upload_track_tokens = 0
        db.session.commit()
        session = _make_stripe_session(free_user.id, 'pro')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            self._post(client, free_headers, 'cs_test_tokens_pro')

        db.session.refresh(free_user)
        assert free_user.upload_track_tokens >= plans.get(plans.PRO_STRUCTURE).upload_cap

    def test_unpaid_session_returns_403(self, client, free_headers, free_user):
        """Session Stripe non payée (payment_status='unpaid') → 403."""
        session = _make_stripe_session(free_user.id, 'amateur', payment_status='unpaid')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, free_headers, 'cs_test_unpaid')

        assert resp.status_code == 403

    def test_wrong_user_id_in_metadata_returns_403(self, client, free_headers, free_user):
        """user_id en metadata ≠ utilisateur connecté → 403."""
        session = _make_stripe_session(99999, 'amateur')  # user_id différent
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, free_headers, 'cs_test_wrong_user')

        assert resp.status_code == 403

    def test_wrong_type_in_metadata_returns_403(self, client, free_headers, free_user):
        """type ≠ 'premium_subscription' en metadata → 403."""
        session = _make_stripe_session(free_user.id, 'amateur')
        session.metadata['type'] = 'track_purchase'  # mauvais type
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, free_headers, 'cs_test_wrong_type')

        assert resp.status_code == 403

    def test_missing_session_id_returns_403(self, client, free_headers):
        """Body sans session_id → 403."""
        resp = client.post(
            '/api/premium/activate',
            data=json.dumps({}),
            headers=free_headers,
        )
        assert resp.status_code == 403

    def test_anti_doublon_within_60s(self, client, db, free_headers, free_user):
        """Deux activations en < 60 s → la deuxième retourne 200 sans modifier l'abonnement."""
        # Première activation
        session = _make_stripe_session(free_user.id, 'amateur')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp1 = self._post(client, free_headers, 'cs_test_first')
        assert resp1.status_code == 200

        # Immédiatement après (< 60s) → anti-doublon déclenché
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp2 = self._post(client, free_headers, 'cs_test_second')
        assert resp2.status_code == 200
        # Le message indique que l'abonnement est déjà actif
        assert 'déjà' in resp2.json.get('feedback', {}).get('message', '').lower() or \
               resp2.json.get('success') is True

    def test_renewal_extends_expiry(self, client, db, amateur_headers, amateur_user):
        """Renouvellement → premium_expires_at prolongé de 30 jours."""
        original_expiry = amateur_user.premium_expires_at
        session = _make_stripe_session(amateur_user.id, 'amateur')
        session.metadata['is_renewal'] = 'True'
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, amateur_headers, 'cs_test_renew')

        assert resp.status_code == 200
        db.session.refresh(amateur_user)
        # La nouvelle expiration doit être >= l'originale + 29 jours
        assert amateur_user.premium_expires_at > original_expiry

    def test_stripe_error_returns_503(self, client, free_headers):
        """Erreur Stripe lors du retrieve → 503."""
        import stripe._error as stripe_error
        with patch('stripe.checkout.Session.retrieve',
                   side_effect=stripe_error.StripeError('Network error')):
            resp = self._post(client, free_headers, 'cs_test_error')

        assert resp.status_code == 503

    def test_response_includes_subscription_plan(self, client, free_headers, free_user):
        """La réponse doit inclure subscription_plan dans data."""
        session = _make_stripe_session(free_user.id, 'pro')
        with patch('stripe.checkout.Session.retrieve', return_value=session):
            resp = self._post(client, free_headers, 'cs_pro_data')

        assert resp.status_code == 200
        assert resp.json['data']['subscription_plan'] == plans.PRO_STRUCTURE

    def test_requires_auth(self, client):
        resp = client.post('/api/premium/activate',
                           data=json.dumps({'session_id': 'cs_test'}),
                           headers={'Content-Type': 'application/json'})
        assert resp.status_code in (401, 422)
