"""
Tests de sécurité — routes/streaming_service.py

Couvre :
1. Path traversal dans _send() — valeur de DB corrompue avec '../..'
2. /tracks/<id>/full est public (écoute libre du titre entier, streaming pur)
3. /tracks/<id>/preview reste public (comportement attendu)
4. /tracks/<id>/download/<format> requiert JWT + achat
5. /stream/contracts/<purchase_id> requiert JWT + être acheteur ou compositeur
"""

import json
import uuid
import pytest
from unittest.mock import patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def composer(db):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'stream_composer_{uid}@test.laprod.fr',
        username=f'stream_composer_{uid}',
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
    existing = db.session.get(User, u.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


@pytest.fixture()
def buyer(db):
    from models import User
    uid = uuid.uuid4().hex[:8]
    u = User(
        email=f'stream_buyer_{uid}@test.laprod.fr',
        username=f'stream_buyer_{uid}',
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
def approved_track(db, composer):
    """Track approuvé avec audio_file et file_mp3 valides (fichiers inexistants sur disque)."""
    from models import Track
    uid = uuid.uuid4().hex[:8]
    t = Track(
        title='Security Test Beat',
        composer_id=composer.id,
        file_hash=str(uuid.uuid4()),
        audio_file=f'audio/safe_preview_{uid}.mp3',
        file_mp3=f'audio/safe_full_{uid}.mp3',
        bpm=140,
        key='C minor',
        is_approved=True,
        is_exclusive_sold=False,
        price_mp3=9.99,
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
def traversal_track(db, composer):
    """Track avec audio_file contenant une tentative de path traversal."""
    from models import Track
    t = Track(
        title='Traversal Beat',
        composer_id=composer.id,
        file_hash=str(uuid.uuid4()),
        audio_file='../../config.py',  # path traversal payload
        file_mp3='../../config.py',
        bpm=120,
        key='D major',
        is_approved=True,
        is_exclusive_sold=False,
        price_mp3=9.99,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    db.session.rollback()
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
    db.session.commit()


def _jwt_headers(app, user_id: int) -> dict:
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(user_id))
    return {'Authorization': f'Bearer {token}'}


# ── 1. Path traversal ─────────────────────────────────────────────────────────

class TestPathTraversal:

    def test_preview_blocks_path_traversal(self, client, app, traversal_track):
        """
        Si audio_file en DB = '../../config.py', _send() doit retourner 403.
        Avant le fix : Flask servirait config.py (le fichier existe sur disque).
        Après le fix : is_relative_to(db_assets) = False → abort(403).
        """
        resp = client.get(f'/api/stream/tracks/{traversal_track.id}/preview')
        assert resp.status_code == 403, (
            "Path traversal non bloqué : audio_file='../../config.py' ne doit pas être servi"
        )

    def test_preview_blocks_absolute_path_injection(self, client, app, db, composer):
        """Un chemin absolu ('/etc/passwd') ne doit pas sortir de db_assets."""
        from models import Track
        t = Track(
            title='AbsPath Beat',
            composer_id=composer.id,
            file_hash=str(uuid.uuid4()),
            audio_file='/etc/passwd',
            bpm=120,
            key='C minor',
            is_approved=True,
            is_exclusive_sold=False,
            price_mp3=9.99,
        )
        db.session.add(t)
        db.session.commit()

        resp = client.get(f'/api/stream/tracks/{t.id}/preview')
        assert resp.status_code in (403, 404)

        db.session.delete(t)
        db.session.commit()

    def test_safe_path_returns_404_when_file_missing(self, client, app, approved_track):
        """
        Un chemin légitime dans db_assets/ doit passer le check path traversal.
        Le 404 ici vient du fichier manquant sur disque (normal en test), pas du check sécurité.
        """
        resp = client.get(f'/api/stream/tracks/{approved_track.id}/preview')
        assert resp.status_code == 404, "Un chemin valide doit retourner 404 si le fichier est absent"


# ── 2. /full est public (écoute libre du titre entier) ────────────────────────

class TestFullStreamAuth:

    def test_full_accessible_without_jwt(self, client, approved_track):
        """
        Le MP3 complet est en écoute libre (streaming, pas de téléchargement) :
        aucune authentification requise. Retourne 404 (fichier absent en test), pas 401.
        """
        resp = client.get(f'/api/stream/tracks/{approved_track.id}/full')
        assert resp.status_code == 404, (
            "/full doit être public — 404 attendu (fichier absent en test), pas 401"
        )

    def test_full_returns_404_for_unapproved_track(self, client, db, composer):
        """Un track non approuvé doit retourner 404 sur /full, comme /preview."""
        from models import Track
        t = Track(
            title='Pending Beat Full',
            composer_id=composer.id,
            file_hash=str(uuid.uuid4()),
            audio_file='audio/pending_preview.mp3',
            file_mp3='audio/pending_full.mp3',
            bpm=120,
            key='C minor',
            is_approved=False,
            is_exclusive_sold=False,
            price_mp3=9.99,
        )
        db.session.add(t)
        db.session.commit()

        resp = client.get(f'/api/stream/tracks/{t.id}/full')
        assert resp.status_code == 404

        db.session.delete(t)
        db.session.commit()

    def test_full_blocks_path_traversal(self, client, app, traversal_track):
        """Path traversal doit être bloqué même sans authentification requise."""
        resp = client.get(f'/api/stream/tracks/{traversal_track.id}/full')
        assert resp.status_code == 403


# ── 3. /preview reste public ─────────────────────────────────────────────────

class TestPreviewIsPublic:

    def test_preview_accessible_without_jwt(self, client, approved_track):
        """
        La preview watermarquée doit rester publique.
        Retourne 404 (fichier absent en test), pas 401.
        """
        resp = client.get(f'/api/stream/tracks/{approved_track.id}/preview')
        assert resp.status_code != 401, "La preview publique ne doit pas exiger un JWT"

    def test_preview_returns_404_for_unapproved_track(self, client, db, composer):
        """Un track non approuvé doit retourner 404 sur /preview."""
        from models import Track
        t = Track(
            title='Pending Beat',
            composer_id=composer.id,
            file_hash=str(uuid.uuid4()),
            audio_file='audio/pending.mp3',
            bpm=120,
            key='C minor',
            is_approved=False,
            is_exclusive_sold=False,
            price_mp3=9.99,
        )
        db.session.add(t)
        db.session.commit()

        resp = client.get(f'/api/stream/tracks/{t.id}/preview')
        assert resp.status_code == 404

        db.session.delete(t)
        db.session.commit()


# ── 4. /download/<format> requiert JWT + achat ────────────────────────────────

class TestDownloadAuth:

    def test_download_returns_401_without_jwt(self, client, approved_track):
        """Aucun format de téléchargement sans JWT."""
        for fmt in ('mp3', 'wav', 'stems'):
            resp = client.get(f'/api/stream/tracks/{approved_track.id}/download/{fmt}')
            assert resp.status_code == 401, f"download/{fmt} doit exiger JWT"

    def test_download_returns_403_without_purchase(self, client, app, approved_track, buyer):
        """JWT valide mais aucun achat → 403."""
        headers = _jwt_headers(app, buyer.id)
        resp = client.get(
            f'/api/stream/tracks/{approved_track.id}/download/mp3', headers=headers
        )
        assert resp.status_code == 403

    def test_composer_can_download_own_track(self, client, app, approved_track, composer):
        """Le compositeur peut télécharger ses propres fichiers sans achat (fichier absent → 404)."""
        headers = _jwt_headers(app, composer.id)
        resp = client.get(
            f'/api/stream/tracks/{approved_track.id}/download/mp3', headers=headers
        )
        assert resp.status_code == 404, (
            "Le compositeur doit passer la vérification d'achat (404 = fichier absent en test)"
        )


# ── 5. /contracts/<id> — isolation acheteur/compositeur ──────────────────────

class TestContractDownloadIsolation:

    def test_contract_requires_jwt(self, client):
        """Aucun accès aux contrats sans JWT."""
        resp = client.get('/api/stream/contracts/1')
        assert resp.status_code == 401

    def test_third_party_cannot_access_contract(self, client, app, db, composer, buyer):
        """Un tiers sans lien avec l'achat doit recevoir 403."""
        from models import Track, Purchase
        from decimal import Decimal

        t = Track(
            title='Contract Test Beat',
            composer_id=composer.id,
            file_hash=str(uuid.uuid4()),
            audio_file='audio/ct_preview.mp3',
            bpm=140,
            key='A minor',
            is_approved=True,
            is_exclusive_sold=False,
            price_mp3=9.99,
        )
        db.session.add(t)
        db.session.flush()

        p = Purchase(
            track_id=t.id,
            buyer_id=composer.id,  # le compositeur s'est acheté son propre track (edge case)
            format_purchased='mp3',
            price_paid=Decimal('9.99'),
            buyer_name=composer.username,
            contract_price=0,
            track_price=Decimal('9.99'),
            platform_fee=Decimal('1.00'),
            composer_revenue=Decimal('8.99'),
            stripe_payment_intent_id=f'pi_test_{uuid.uuid4().hex}',
            contract_file='contract_test.pdf',
        )
        db.session.add(p)
        db.session.commit()

        # buyer est un tiers non lié à cet achat
        third_party_headers = _jwt_headers(app, buyer.id)
        resp = client.get(f'/api/stream/contracts/{p.id}', headers=third_party_headers)
        assert resp.status_code == 403

        db.session.delete(p)
        db.session.delete(t)
        db.session.commit()
