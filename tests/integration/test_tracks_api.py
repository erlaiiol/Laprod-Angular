"""
Tests d'intégration — routes/tracks_api.py

Couvre : GET /track/<id>, GET /tracks, DELETE /delete/<id>, owned_licenses.
"""

import json
import uuid
from decimal import Decimal

import pytest


# ── Fixture locale ────────────────────────────────────────────────────────────

@pytest.fixture()
def track(db, user):
    """Track minimal approuvé, lié au user standard."""
    from models import Track
    t = Track(
        title='Test Beat',
        composer_id=user.id,
        file_hash=str(uuid.uuid4()),
        audio_file='test_preview.mp3',
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


# ── GET /api/tracks/track/<id> ────────────────────────────────────────────────

class TestGetTrack:

    def test_returns_404_for_nonexistent_track(self, client):
        resp = client.get('/api/tracks/track/99999')
        assert resp.status_code == 404

    def test_returns_track_data_for_existing_track(self, client, track):
        resp = client.get(f'/api/tracks/track/{track.id}')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['data']['track']['id'] == track.id


# ── GET /api/tracks/tracks ────────────────────────────────────────────────────

class TestGetTracks:

    def test_returns_list_without_authentication(self, client):
        resp = client.get('/api/tracks/tracks')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert isinstance(data['data']['tracks'], list)

    def test_pagination_fields_present(self, client):
        resp = client.get('/api/tracks/tracks')
        assert resp.status_code == 200
        pagination = json.loads(resp.data)['data']['pagination']
        assert 'page' in pagination
        assert 'total' in pagination
        assert 'per_page' in pagination
        assert 'pages' in pagination


# ── GET /api/tracks/tracks?sort=recommended — cohérence cache reco ─────────────
# Le job RQ qui calcule les recommandations tourne en fond et peut remplir
# laprod:reco:result:{user_id} entre deux requêtes de pagination du même
# utilisateur. Sans garde-fou, la page 2 basculerait sur un ordre totalement
# différent de celui vu en page 1. Le snapshot "fallback" doit rester la
# source de vérité tant qu'il existe, même si le cache perso devient dispo.

class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        val = self.store.get(key)
        return val.encode() if val is not None else None

    def setex(self, key, ttl, value):
        self.store[key] = value


class TestRecommendedPaginationConsistency:

    def test_reuses_fallback_snapshot_over_fresher_personalized_cache(self, client, db, user, track, auth_headers, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr('routes.tracks_api.redis_client', fake)

        fallback_key = f'laprod:reco:fallback:{user.id}'
        result_key   = f'laprod:reco:result:{user.id}'

        # Une pagination fallback est déjà entamée pour cet utilisateur...
        fake.store[fallback_key] = json.dumps([track.id])
        # ...et le job RQ vient de terminer son calcul perso entre-temps,
        # avec un ordre différent (ID inexistant pour bien distinguer les deux).
        fake.store[result_key] = json.dumps([999999])

        resp = client.get('/api/tracks/tracks?sort=recommended', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)['data']

        assert data['personalized'] is False
        returned_ids = [t['id'] for t in data['tracks']]
        assert track.id in returned_ids

    def test_computes_and_caches_fallback_snapshot_on_full_cache_miss(self, client, db, user, track, auth_headers, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr('routes.tracks_api.redis_client', fake)

        resp = client.get('/api/tracks/tracks?sort=recommended', headers=auth_headers)
        assert resp.status_code == 200
        data = json.loads(resp.data)['data']

        assert data['personalized'] is False
        returned_ids = [t['id'] for t in data['tracks']]
        assert track.id in returned_ids

        fallback_key = f'laprod:reco:fallback:{user.id}'
        assert fallback_key in fake.store
        assert track.id in json.loads(fake.store[fallback_key])

    def test_filters_reco_cache_while_keeping_personalized_order(self, client, db, user, auth_headers, monkeypatch):
        """Le cache reco est calculé sur tout le catalogue, sans filtre — mais
        l'ORDRE qu'il contient encode le classement de préférence. Un filtre
        actif (ex: recherche) doit restreindre les résultats au sous-ensemble
        qui matche, sans pour autant désactiver la personnalisation : le rang
        relatif des tracks retenues doit venir du cache, pas de l'ID/l'insertion."""
        from models import Track

        other = Track(
            title='Completely Different Title', composer_id=user.id,
            file_hash='other-hash-1234', audio_file='other_preview.mp3',
            bpm=90, key='D minor', is_approved=True,
        )
        match_low = Track(
            title='Trap Banger Beta', composer_id=user.id,
            file_hash='match-low-hash', audio_file='match_low_preview.mp3',
            bpm=140, key='A minor', is_approved=True,
        )
        match_high = Track(
            title='Trap Banger Alpha', composer_id=user.id,
            file_hash='match-high-hash', audio_file='match_high_preview.mp3',
            bpm=140, key='A minor', is_approved=True,
        )
        db.session.add_all([other, match_low, match_high])
        db.session.commit()

        fake = _FakeRedis()
        monkeypatch.setattr('routes.tracks_api.redis_client', fake)

        # Cache reco (tout le catalogue, sans filtre) : match_low classé avant
        # match_high, avec other quelque part au milieu.
        result_key = f'laprod:reco:result:{user.id}'
        fake.store[result_key] = json.dumps([match_low.id, other.id, match_high.id])

        resp = client.get(
            '/api/tracks/tracks?sort=recommended&search=Trap+Banger',
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)['data']

        # La personnalisation reste active : 'other' (hors-filtre) est exclu,
        # mais l'ordre entre match_low et match_high reflète le cache, pas l'ID.
        assert data['personalized'] is True
        returned_ids = [t['id'] for t in data['tracks']]
        assert other.id not in returned_ids
        assert returned_ids == [match_low.id, match_high.id]

        db.session.delete(other)
        db.session.delete(match_low)
        db.session.delete(match_high)
        db.session.commit()


# ── DELETE /api/tracks/delete/<id> ────────────────────────────────────────────

class TestDeleteTrack:

    def test_requires_authentication(self, client, track):
        resp = client.delete(f'/api/tracks/delete/{track.id}')
        assert resp.status_code == 401

    def test_owner_can_delete_own_track(self, client, db, user, auth_headers, app):
        from models import Track
        t = Track(
            title='Deletable Beat',
            composer_id=user.id,
            file_hash=str(uuid.uuid4()),
            audio_file='deletable.mp3',
            bpm=100,
            key='A minor',
            is_approved=True,
        )
        db.session.add(t)
        db.session.commit()
        track_id = t.id

        resp = client.delete(f'/api/tracks/delete/{track_id}', headers=auth_headers)
        assert resp.status_code == 200

    def test_other_user_cannot_delete_track(self, client, track, db, app):
        """Un utilisateur non propriétaire et non admin reçoit 403."""
        from models import User
        from flask_jwt_extended import create_access_token

        other = User(
            email='other_tracks@test.laprod.fr',
            username='other_user_tracks',
            email_verified=True,
            account_status='active',
            user_type_selected=True,
        )
        other.set_password('OtherPass123!')
        db.session.add(other)
        db.session.commit()

        with app.app_context():
            token = create_access_token(identity=str(other.id))
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

        resp = client.delete(f'/api/tracks/delete/{track.id}', headers=headers)

        db.session.delete(other)
        db.session.commit()

        assert resp.status_code == 403


# ── Exclusivité vendue ────────────────────────────────────────────────────────

class TestExclusiveSold:

    def test_exclusive_sold_track_absent_from_index(self, client, db, user):
        """Un track is_exclusive_sold=True ne doit pas apparaître dans l'index."""
        from models import Track
        t = Track(
            title='Exclusive Beat',
            composer_id=user.id,
            file_hash=str(uuid.uuid4()),
            audio_file='excl_preview.mp3',
            bpm=130,
            key='G major',
            is_approved=True,
            is_exclusive_sold=True,
        )
        db.session.add(t)
        db.session.commit()

        resp = client.get('/api/tracks/tracks')
        assert resp.status_code == 200
        ids = [tr['id'] for tr in resp.json['data']['tracks']]
        assert t.id not in ids

        db.session.delete(db.session.get(Track, t.id))
        db.session.commit()

    def test_get_track_includes_contract_prices(self, client, track):
        """GET /api/tracks/track/<id> retourne un objet contract_prices."""
        resp = client.get(f'/api/tracks/track/{track.id}')
        assert resp.status_code == 200
        data = resp.json['data']['track']
        assert 'contract_prices' in data
        cp = data['contract_prices']
        for key in ('exclusive', 'duration_3y', 'duration_5y', 'duration_10y',
                    'lifetime', 'mechanical', 'public_show', 'arrangement',
                    'territory_eu', 'territory_world'):
            assert key in cp

    def test_get_track_includes_is_exclusive_sold(self, client, track):
        """GET /api/tracks/track/<id> retourne is_exclusive_sold."""
        resp = client.get(f'/api/tracks/track/{track.id}')
        assert resp.status_code == 200
        assert 'is_exclusive_sold' in resp.json['data']['track']


# ── owned_licenses dans le détail du track ───────────────────────────────────

class TestOwnedLicenses:
    """GET /api/tracks/track/<id> doit retourner owned_licenses selon le JWT."""

    def _make_purchase(self, db, track, buyer, format_purchased='mp3',
                       is_lifetime=False, duration_years=None, expires_at=None,
                       license_status='active'):
        from models import Purchase
        p = Purchase(
            track_id=track.id,
            buyer_id=buyer.id,
            buyer_name=buyer.username,
            format_purchased=format_purchased,
            price_paid=Decimal('9.99'),
            track_price=Decimal('9.99'),
            contract_price=Decimal('0'),
            platform_fee=Decimal('1.00'),
            composer_revenue=Decimal('8.99'),
            stripe_payment_intent_id=f'pi_test_{uuid.uuid4().hex[:16]}',
            is_exclusive=False,
            duration_years=duration_years,
            is_lifetime=is_lifetime,
            expires_at=expires_at,
            license_status=license_status,
        )
        db.session.add(p)
        db.session.commit()
        return p

    def test_owned_licenses_empty_without_auth(self, client, track):
        resp = client.get(f'/api/tracks/track/{track.id}')
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert owned == {}

    def test_owned_licenses_empty_when_no_purchase(self, client, app, track, user, auth_headers):
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert owned == {}

    def test_owned_licenses_mp3_active(self, client, app, db, track, user, auth_headers):
        p = self._make_purchase(db, track, user, format_purchased='mp3')
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert 'mp3' in owned
        assert owned['mp3']['purchase_id'] == p.id
        assert owned['mp3']['license_status'] == 'active'
        from models import Purchase
        db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()

    def test_owned_licenses_wav_active(self, client, app, db, track, user, auth_headers):
        p = self._make_purchase(db, track, user, format_purchased='wav')
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert 'wav' in owned
        assert 'mp3' not in owned
        from models import Purchase
        db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()

    def test_owned_licenses_stems_active(self, client, app, db, track, user, auth_headers):
        p = self._make_purchase(db, track, user, format_purchased='stems')
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert 'stems' in owned
        assert 'mp3' not in owned
        assert 'wav' not in owned
        from models import Purchase
        db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()

    def test_owned_licenses_lifetime_flag(self, client, app, db, track, user, auth_headers):
        p = self._make_purchase(db, track, user, format_purchased='mp3', is_lifetime=True)
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert owned['mp3']['is_lifetime'] is True
        assert owned['mp3']['expires_at'] is None
        from models import Purchase
        db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()

    def test_expired_license_not_in_owned(self, client, app, db, track, user, auth_headers):
        p = self._make_purchase(db, track, user, format_purchased='mp3', license_status='expired')
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert 'mp3' not in owned
        from models import Purchase
        db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()

    def test_multiple_formats_independently_tracked(self, client, app, db, track, user, auth_headers):
        p_mp3  = self._make_purchase(db, track, user, format_purchased='mp3')
        p_wav  = self._make_purchase(db, track, user, format_purchased='wav')
        resp   = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned  = resp.json['data']['track']['owned_licenses']
        assert 'mp3' in owned
        assert 'wav' in owned
        assert 'stems' not in owned
        from models import Purchase
        for p in (p_mp3, p_wav):
            db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()

    def test_streaming_only_license_included(self, client, app, db, track, user, auth_headers):
        """Licence streaming seul (is_lifetime=False, duration_years=None) → active."""
        p = self._make_purchase(db, track, user, format_purchased='mp3',
                                is_lifetime=False, duration_years=None)
        resp = client.get(f'/api/tracks/track/{track.id}', headers=auth_headers)
        assert resp.status_code == 200
        owned = resp.json['data']['track']['owned_licenses']
        assert 'mp3' in owned
        assert owned['mp3']['is_lifetime'] is False
        assert owned['mp3']['expires_at'] is None
        from models import Purchase
        db.session.delete(db.session.get(Purchase, p.id))
        db.session.commit()


# ── PUT contract prices ───────────────────────────────────────────────────────

class TestPutContractPrices:

    def test_put_saves_contract_price_exclusive(self, client, db, track, auth_headers):
        """PUT avec contract_price_exclusive persiste la valeur."""
        resp = client.put(
            f'/api/tracks/put/{track.id}',
            data={
                'title': track.title,
                'bpm': str(track.bpm),
                'key': track.key or 'C major',
                'style': track.style or 'Trap',
                'price_mp3': '9.99',
                'price_wav': '19.99',
                'price_stems': '39.99',
                'contract_price_exclusive': '500',
            },
            headers=auth_headers,
            content_type='multipart/form-data',
        )
        assert resp.status_code == 200

        from models import Track
        db.session.expire(track)
        refreshed = db.session.get(Track, track.id)
        assert refreshed.contract_price_exclusive == 500

    def test_put_rejects_negative_contract_price(self, client, track, auth_headers):
        """Un prix négatif retourne 200 ou 4xx selon la validation."""
        resp = client.put(
            f'/api/tracks/put/{track.id}',
            data={
                'title': track.title,
                'bpm': str(track.bpm),
                'key': track.key or 'C major',
                'style': track.style or 'Trap',
                'price_mp3': '9.99',
                'price_wav': '19.99',
                'price_stems': '39.99',
                'contract_price_exclusive': '-1',
            },
            headers=auth_headers,
            content_type='multipart/form-data',
        )
        assert resp.status_code in (400, 422)
