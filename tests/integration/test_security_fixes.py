"""
Tests d'intégration — correctifs de sécurité (audit).

Couvre :
- C1 : /db_assets/ ne dessert plus les sous-dossiers sensibles (audio complet,
       contrats, factures, mixmaster) → 404.
- H2 : /api/stream/tracks/<id>/full exige un achat (ou d'être le compositeur).
- H3 : /api/stripe/webhook rejette toute requête sans signature Stripe valide.
"""

import uuid

import pytest


# ── C1 — allowlist /db_assets/ ────────────────────────────────────────────────

class TestDbAssetsAllowlist:
    """Les contenus sensibles ne doivent jamais être servis en accès direct."""

    @pytest.mark.parametrize('path', [
        '/db_assets/audio/beat_1234_full.mp3',
        '/db_assets/audio/beat_1234_full.wav',
        '/db_assets/audio/beat_1234_stems.zip',
        '/db_assets/contracts/contract_1_1.pdf',
        '/db_assets/invoices/facture_2026_1.pdf',
        '/db_assets/mixmaster/uploads/anything.zip',
    ])
    def test_sensitive_paths_blocked(self, client, path):
        resp = client.get(path)
        assert resp.status_code == 404

    @pytest.mark.parametrize('path', [
        '/db_assets/../config.py',
        '/db_assets/audio/../contracts/contract_1_1.pdf',
    ])
    def test_traversal_attempts_blocked(self, client, path):
        resp = client.get(path)
        assert resp.status_code in (403, 404)


# ── H2 — stream full = achat requis ───────────────────────────────────────────

class TestStreamFullRequiresPurchase:

    @pytest.fixture()
    def paid_track(self, db, user):
        """Track approuvé du `user` (compositeur) avec un MP3 complet payant."""
        from models import Track
        t = Track(
            title='Paid Beat',
            composer_id=user.id,
            file_hash=str(uuid.uuid4()),
            audio_file='preview.mp3',
            file_mp3='audio/paidbeat_full.mp3',
            bpm=120,
            key='C major',
            is_approved=True,
        )
        db.session.add(t)
        db.session.commit()
        yield t
        existing = db.session.get(Track, t.id)
        if existing:
            db.session.delete(existing)
            db.session.commit()

    def _headers_for(self, app, user_id):
        from flask_jwt_extended import create_access_token
        with app.app_context():
            token = create_access_token(identity=str(user_id))
        return {'Authorization': f'Bearer {token}'}

    def test_non_buyer_gets_403(self, app, client, db, paid_track, bound_factories):
        """Un autre utilisateur sans achat ne peut pas streamer le MP3 complet."""
        from tests.factories.user_factory import UserFactory
        attacker = UserFactory(is_beatmaker=True)
        db.session.commit()

        resp = client.get(
            f'/api/stream/tracks/{paid_track.id}/full',
            headers=self._headers_for(app, attacker.id),
        )
        assert resp.status_code == 403

    def test_anonymous_gets_401(self, client, paid_track):
        """Sans JWT, l'accès est refusé (jwt_required)."""
        resp = client.get(f'/api/stream/tracks/{paid_track.id}/full')
        assert resp.status_code == 401

    def test_composer_is_not_forbidden(self, app, client, paid_track, user):
        """Le compositeur n'est pas bloqué par la vérif d'achat (403) — il atteint
        le service du fichier (404 ici car le fichier n'existe pas sur disque)."""
        resp = client.get(
            f'/api/stream/tracks/{paid_track.id}/full',
            headers=self._headers_for(app, user.id),
        )
        assert resp.status_code != 403


# ── H3 — webhook Stripe : signature obligatoire ───────────────────────────────

class TestStripeWebhookSignature:

    def test_missing_signature_rejected(self, client):
        resp = client.post('/api/stripe/webhook', data=b'{"id":"evt_1","type":"charge.refunded"}')
        assert resp.status_code == 400

    def test_invalid_signature_rejected(self, client):
        resp = client.post(
            '/api/stripe/webhook',
            data=b'{"id":"evt_1","type":"charge.refunded"}',
            headers={'Stripe-Signature': 't=123,v1=deadbeef'},
        )
        assert resp.status_code == 400


# ── H4 — purge RGPD : PII liées effacées ──────────────────────────────────────

class TestGdprPurgeRelatedPii:

    @pytest.fixture()
    def purchase_scenario(self, db, bound_factories):
        """Acheteur + compositeur + track + achat, avec nettoyage complet
        (l'ordre respecte les FK : purchase → track → users)."""
        from models import Track, Purchase, User
        from tests.factories.user_factory import UserFactory
        from tests.factories.purchase_factory import PurchaseFactory

        buyer    = UserFactory(is_beatmaker=True)
        composer = UserFactory(is_beatmaker=True)
        db.session.commit()

        track = Track(
            title='Beat', composer_id=composer.id, file_hash=str(uuid.uuid4()),
            audio_file='p.mp3', bpm=120, key='C major', is_approved=True,
        )
        db.session.add(track)
        db.session.commit()

        purchase = PurchaseFactory(track_id=track.id, buyer_id=buyer.id, buyer_name='Jean Dupont')
        db.session.commit()

        ids = {'buyer': buyer.id, 'composer': composer.id, 'track': track.id, 'purchase': purchase.id}
        yield buyer, ids

        db.session.rollback()
        for model, key in ((Purchase, 'purchase'), (Track, 'track'), (User, 'composer'), (User, 'buyer')):
            obj = db.session.get(model, ids[key])
            if obj:
                db.session.delete(obj)
        db.session.commit()

    def test_anonymize_clears_buyer_name_and_user_pii(self, db, purchase_scenario):
        """La purge d'un compte efface le nom d'acheteur de ses achats ET les PII
        de la table User."""
        from models import Purchase
        from utils.gdpr_purge import anonymize_user

        buyer, ids = purchase_scenario

        anonymize_user(buyer, db)
        db.session.expire_all()

        refreshed = db.session.get(Purchase, ids['purchase'])
        assert refreshed.buyer_name != 'Jean Dupont'
        assert buyer.account_status == 'deleted'
        assert buyer.email.endswith('@laprod-deleted.fr')
