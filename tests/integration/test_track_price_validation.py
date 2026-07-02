"""
Tests de sécurité — validation des prix de track (post_track / put_track)

Vérifie qu'un beatmaker ne peut pas enregistrer un prix négatif, nul ou hors plage
(0.50€ – 999.99€) qui pourrait créer des situations de paiement invalides côté Stripe.
"""

import io
import uuid
import pytest
from decimal import Decimal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mp3_bytes() -> bytes:
    """ID3v2 header minimal reconnu comme MP3 par file_validator."""
    return b'ID3' + b'\x03\x00' + b'\x00' * 5 + b'\x00' * 100


def _make_beatmaker(db):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'bm_price_{uid}@test.laprod.fr',
        username=f'bm_price_{uid}',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_beatmaker=True,
        subscription_plan='pro',
    )
    u.set_password('Pass123!')
    db.session.add(u)
    db.session.commit()
    return u


def _auth_headers(app, user_id: int) -> dict:
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {'Authorization': f'Bearer {token}'}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def beatmaker(db):
    u = _make_beatmaker(db)
    yield u
    db.session.rollback()
    from models import User
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def owned_track(db, beatmaker):
    from models import Track
    t = Track(
        title='Price Test Beat',
        composer_id=beatmaker.id,
        file_hash=str(uuid.uuid4()),
        audio_file='audio/price_preview.mp3',
        file_mp3='audio/price_full.mp3',
        bpm=140,
        key='C minor',
        is_approved=False,
        is_exclusive_sold=False,
        price_mp3=9.99,
        price_wav=19.99,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


# ── Tests POST /api/tracks/post — création ────────────────────────────────────

class TestPostTrackPriceValidation:
    """
    L'endpoint POST /api/tracks/post requiert un fichier MP3 réel.
    On utilise un faux fichier MP3 pour tester uniquement la logique de prix.
    Si la validation de prix est faite AVANT la validation du fichier,
    on obtiendra l'erreur de prix attendue.
    Si elle est faite APRÈS, on obtient l'erreur de validation de fichier,
    ce qui signifie que le bug de prix serait accessible (test échoue).

    Stratégie : appel sans fichier MP3 valide — on ne peut pas tester le chemin complet
    sans un vrai encoder audio. On utilise le endpoint PUT sur un track existant
    qui accepte un body sans fichier.
    """
    pass  # Voir TestPutTrackPriceValidation


# ── Tests PUT /api/tracks/<id> — modification ─────────────────────────────────

class TestPutTrackPriceValidation:
    """
    PUT /api/tracks/<id> accepte les modifications de prix sans fichier audio.
    C'est le vecteur principal de manipulation de prix (le beatmaker peut
    modifier les prix d'un track déjà publié via l'interface d'édition).
    """

    def _put(self, client, track_id, headers, data: dict):
        return client.put(
            f'/api/tracks/put/{track_id}',
            data={
                'title': 'Price Test Beat',
                'bpm': '140',
                'key': 'C minor',
                'style': 'Trap',
                **data,
            },
            headers=headers,
        )

    def test_negative_mp3_price_rejected(self, client, app, owned_track, beatmaker):
        """price_mp3 négatif doit retourner une erreur — pas être enregistré."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {'price_mp3': '-10.00'})
        assert resp.status_code in (400, 422), \
            f"price_mp3=-10 doit être rejeté, reçu {resp.status_code}"
        data = resp.get_json()
        assert data.get('success') is False

    def test_zero_mp3_price_rejected(self, client, app, owned_track, beatmaker):
        """price_mp3=0 doit être rejeté (pas de track gratuit)."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {'price_mp3': '0.00'})
        assert resp.status_code in (400, 422), \
            f"price_mp3=0 doit être rejeté, reçu {resp.status_code}"

    def test_below_minimum_price_rejected(self, client, app, owned_track, beatmaker):
        """price_mp3=0.49 sous le minimum (0.50€) doit être rejeté."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {'price_mp3': '0.49'})
        assert resp.status_code in (400, 422)

    def test_excessive_price_rejected(self, client, app, owned_track, beatmaker):
        """price_mp3=99999 hors plage doit être rejeté."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {'price_mp3': '99999.00'})
        assert resp.status_code in (400, 422)

    def test_negative_wav_price_rejected(self, client, app, owned_track, beatmaker):
        """price_wav négatif doit être rejeté même si price_mp3 est valide."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {
            'price_mp3': '9.99',
            'price_wav': '-1.00',
        })
        assert resp.status_code in (400, 422)

    def test_valid_prices_accepted(self, client, app, owned_track, beatmaker):
        """Des prix valides (dans la plage) doivent être acceptés."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {
            'price_mp3': '9.99',
            'price_wav': '19.99',
        })
        # 200 = mis à jour, ou autre code non-4xx
        # On vérifie simplement que ce n'est PAS un rejet de prix
        data = resp.get_json()
        if not data.get('success'):
            msg = data.get('feedback', {}).get('message', '')
            assert 'prix' not in msg.lower(), \
                f"Un prix valide ne doit pas être rejeté, message: {msg}"

    def test_boundary_minimum_price_accepted(self, client, app, owned_track, beatmaker):
        """price_mp3=0.50€ exactement (le minimum) doit être accepté."""
        headers = _auth_headers(app, beatmaker.id)
        resp = self._put(client, owned_track.id, headers, {'price_mp3': '0.50'})
        data = resp.get_json()
        if not data.get('success'):
            msg = data.get('feedback', {}).get('message', '')
            assert 'prix' not in msg.lower(), \
                f"0.50€ est le minimum valide, message: {msg}"

    def test_other_user_cannot_edit_track_prices(self, client, app, owned_track, db):
        """Un autre beatmaker ne doit pas pouvoir modifier les prix d'un track qui ne lui appartient pas."""
        other = _make_beatmaker(db)
        try:
            headers = _auth_headers(app, other.id)
            resp = self._put(client, owned_track.id, headers, {'price_mp3': '1.00'})
            assert resp.status_code in (403, 404), \
                f"Un tiers ne doit pas pouvoir modifier les prix, reçu {resp.status_code}"
        finally:
            db.session.rollback()
            from models import User
            existing = db.session.get(User, other.id)
            if existing:
                db.session.delete(existing)
            db.session.commit()
