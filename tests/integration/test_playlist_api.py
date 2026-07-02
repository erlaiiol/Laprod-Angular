"""
Tests d'intégration — routes/playlist_api.py

Couvre :
  POST   /api/playlists                              → créer
  GET    /api/playlists/my                           → mes playlists
  GET    /api/playlists/<id>                         → détail public
  PUT    /api/playlists/<id>                         → modifier
  DELETE /api/playlists/<id>                         → supprimer
  POST   /api/playlists/<id>/tracks                  → ajouter track
  DELETE /api/playlists/<id>/tracks/<track_id>       → retirer track
  GET    /api/playlists/by-beatmaker/<username>       → playlists d'un beatmaker
  GET    /api/playlists/containing/<tid>/by/<uname>  → IDs des playlists contenant le track
"""

import json
import uuid

import pytest


# ── Fixtures locales ───────────────────────────────────────────────────────────

@pytest.fixture()
def track(db, user):
    from models import Track
    t = Track(
        title='Playlist Test Beat',
        composer_id=user.id,
        file_hash=str(uuid.uuid4()),
        audio_file='pl_test_preview.mp3',
        bpm=128,
        key='D minor',
        is_approved=True,
    )
    db.session.add(t)
    db.session.commit()
    yield t
    existing = db.session.get(Track, t.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


@pytest.fixture()
def playlist(db, user):
    from models import Playlist
    pl = Playlist(beatmaker_id=user.id, title='Ma Playlist Test')
    db.session.add(pl)
    db.session.commit()
    yield pl
    existing = db.session.get(Playlist, pl.id)
    if existing:
        db.session.delete(existing)
        db.session.commit()


@pytest.fixture()
def playlist_with_track(db, user, playlist, track):
    """Playlist contenant déjà le track."""
    from models import playlist_track as pt
    db.session.execute(pt.insert().values(playlist_id=playlist.id, track_id=track.id, position=1))
    db.session.commit()
    yield playlist


@pytest.fixture()
def other_user(db):
    from models import User
    u = User(
        email='other_pl@test.laprod.fr',
        username='other_pl_user',
        email_verified=True,
        account_status='active',
        user_type_selected=True,
        is_beatmaker=True,
    )
    u.set_password('OtherPass123!')
    db.session.add(u)
    db.session.commit()
    yield u
    from models import Wallet
    wallet = db.session.query(Wallet).filter_by(user_id=u.id).first()
    if wallet:
        db.session.delete(wallet)
        db.session.flush()
    db.session.delete(u)
    db.session.commit()


@pytest.fixture()
def other_headers(app, other_user):
    from flask_jwt_extended import create_access_token
    with app.app_context():
        token = create_access_token(identity=str(other_user.id))
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


# ── POST /api/playlists ────────────────────────────────────────────────────────

class TestCreatePlaylist:

    def test_creates_playlist_for_beatmaker(self, client, auth_headers):
        resp = client.post(
            '/api/playlists',
            data={'title': 'Nouvelle Playlist'},
            headers={k: v for k, v in auth_headers.items() if k != 'Content-Type'},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 201
        data = resp.json['data']
        assert data['title'] == 'Nouvelle Playlist'
        assert data['id'] is not None

    def test_requires_authentication(self, client):
        resp = client.post('/api/playlists', data={'title': 'Anon'}, content_type='multipart/form-data')
        assert resp.status_code == 401

    def test_requires_title(self, client, auth_headers):
        resp = client.post(
            '/api/playlists',
            data={'title': '   '},
            headers={k: v for k, v in auth_headers.items() if k != 'Content-Type'},
            content_type='multipart/form-data',
        )
        assert resp.status_code in (400, 403)

    def test_non_beatmaker_cannot_create(self, client, db, app):
        from models import User
        from flask_jwt_extended import create_access_token
        artist = User(
            email='artist_pl@test.laprod.fr',
            username='artist_pl',
            email_verified=True,
            account_status='active',
            user_type_selected=True,
            is_artist=True,
            is_beatmaker=False,
        )
        artist.set_password('ArtPass123!')
        db.session.add(artist)
        db.session.commit()
        with app.app_context():
            token = create_access_token(identity=str(artist.id))
        headers = {'Authorization': f'Bearer {token}'}
        resp = client.post('/api/playlists', data={'title': 'Test'}, headers=headers,
                           content_type='multipart/form-data')
        assert resp.status_code == 403
        db.session.delete(artist)
        db.session.commit()


# ── GET /api/playlists/my ─────────────────────────────────────────────────────

class TestGetMyPlaylists:

    def test_returns_own_playlists(self, client, auth_headers, playlist):
        resp = client.get('/api/playlists/my', headers=auth_headers)
        assert resp.status_code == 200
        ids = [p['id'] for p in resp.json['data']]
        assert playlist.id in ids

    def test_requires_authentication(self, client):
        resp = client.get('/api/playlists/my')
        assert resp.status_code == 401

    def test_does_not_return_other_user_playlists(self, client, auth_headers, other_user, db):
        from models import Playlist
        other_pl = Playlist(beatmaker_id=other_user.id, title='Other')
        db.session.add(other_pl)
        db.session.commit()
        resp = client.get('/api/playlists/my', headers=auth_headers)
        ids = [p['id'] for p in resp.json['data']]
        assert other_pl.id not in ids
        db.session.delete(other_pl)
        db.session.commit()


# ── GET /api/playlists/<id> ───────────────────────────────────────────────────

class TestGetPlaylist:

    def test_returns_playlist_detail(self, client, playlist):
        resp = client.get(f'/api/playlists/{playlist.id}')
        assert resp.status_code == 200
        assert resp.json['data']['id'] == playlist.id
        assert resp.json['data']['title'] == playlist.title
        assert 'tracks' in resp.json['data']

    def test_returns_404_for_unknown(self, client):
        resp = client.get('/api/playlists/999999')
        assert resp.status_code == 404

    def test_includes_tracks_when_populated(self, client, playlist_with_track, track):
        resp = client.get(f'/api/playlists/{playlist_with_track.id}')
        assert resp.status_code == 200
        track_ids = [t['id'] for t in resp.json['data']['tracks']]
        assert track.id in track_ids


# ── PUT /api/playlists/<id> ───────────────────────────────────────────────────

class TestUpdatePlaylist:

    def test_owner_can_rename(self, client, auth_headers, playlist):
        resp = client.put(
            f'/api/playlists/{playlist.id}',
            data={'title': 'Nouveau Titre'},
            headers={k: v for k, v in auth_headers.items() if k != 'Content-Type'},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 200
        assert resp.json['data']['title'] == 'Nouveau Titre'

    def test_other_user_cannot_update(self, client, other_headers, playlist):
        resp = client.put(
            f'/api/playlists/{playlist.id}',
            data={'title': 'Hacked'},
            headers={k: v for k, v in other_headers.items() if k != 'Content-Type'},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403


# ── DELETE /api/playlists/<id> ────────────────────────────────────────────────

class TestDeletePlaylist:

    def test_owner_can_delete(self, client, auth_headers, db, user):
        from models import Playlist
        pl = Playlist(beatmaker_id=user.id, title='À supprimer')
        db.session.add(pl)
        db.session.commit()
        pl_id = pl.id
        resp = client.delete(f'/api/playlists/{pl_id}', headers=auth_headers)
        assert resp.status_code == 200
        assert db.session.get(Playlist, pl_id) is None

    def test_other_user_cannot_delete(self, client, other_headers, playlist):
        resp = client.delete(f'/api/playlists/{playlist.id}', headers=other_headers)
        assert resp.status_code == 403

    def test_requires_authentication(self, client, playlist):
        resp = client.delete(f'/api/playlists/{playlist.id}')
        assert resp.status_code == 401


# ── POST /api/playlists/<id>/tracks ──────────────────────────────────────────

class TestAddTrack:

    def test_owner_can_add_own_track(self, client, auth_headers, playlist, track):
        resp = client.post(
            f'/api/playlists/{playlist.id}/tracks',
            data=json.dumps({'track_id': track.id}),
            headers=auth_headers,
        )
        assert resp.status_code == 201

    def test_cannot_add_other_beatmakers_track(self, client, other_headers, db, other_user, playlist):
        from models import Track
        other_track = Track(
            title='Other Track',
            composer_id=other_user.id,
            file_hash=str(uuid.uuid4()),
            audio_file='other.mp3',
            bpm=100,
            key='C major',
            is_approved=True,
        )
        db.session.add(other_track)
        db.session.commit()
        # other_user tente d'ajouter son track dans la playlist de user
        # → 403 car playlist.beatmaker_id != other_user.id
        resp = client.post(
            f'/api/playlists/{playlist.id}/tracks',
            data=json.dumps({'track_id': other_track.id}),
            headers=other_headers,
        )
        assert resp.status_code == 403
        db.session.delete(other_track)
        db.session.commit()

    def test_cannot_add_to_someone_elses_playlist(self, client, auth_headers, db, other_user, track):
        from models import Playlist
        other_pl = Playlist(beatmaker_id=other_user.id, title='Other PL')
        db.session.add(other_pl)
        db.session.commit()
        resp = client.post(
            f'/api/playlists/{other_pl.id}/tracks',
            data=json.dumps({'track_id': track.id}),
            headers=auth_headers,
        )
        assert resp.status_code == 403
        db.session.delete(other_pl)
        db.session.commit()

    def test_duplicate_add_returns_200(self, client, auth_headers, playlist_with_track, track):
        resp = client.post(
            f'/api/playlists/{playlist_with_track.id}/tracks',
            data=json.dumps({'track_id': track.id}),
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_requires_authentication(self, client, playlist, track):
        resp = client.post(f'/api/playlists/{playlist.id}/tracks',
                           data=json.dumps({'track_id': track.id}),
                           content_type='application/json')
        assert resp.status_code == 401


# ── DELETE /api/playlists/<id>/tracks/<track_id> ─────────────────────────────

class TestRemoveTrack:

    def test_owner_can_remove_track(self, client, auth_headers, playlist_with_track, track):
        resp = client.delete(
            f'/api/playlists/{playlist_with_track.id}/tracks/{track.id}',
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_remove_absent_track_returns_404(self, client, auth_headers, playlist, track):
        resp = client.delete(
            f'/api/playlists/{playlist.id}/tracks/{track.id}',
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_other_user_cannot_remove(self, client, other_headers, playlist_with_track, track):
        resp = client.delete(
            f'/api/playlists/{playlist_with_track.id}/tracks/{track.id}',
            headers=other_headers,
        )
        assert resp.status_code == 403


# ── GET /api/playlists/by-beatmaker/<username> ────────────────────────────────

class TestGetByBeatmaker:

    def test_returns_playlists_for_existing_beatmaker(self, client, user, playlist):
        resp = client.get(f'/api/playlists/by-beatmaker/{user.username}')
        assert resp.status_code == 200
        ids = [p['id'] for p in resp.json['data']]
        assert playlist.id in ids

    def test_returns_404_for_unknown_user(self, client):
        resp = client.get('/api/playlists/by-beatmaker/nonexistentuser99')
        assert resp.status_code == 404

    def test_returns_empty_for_user_with_no_playlists(self, client, other_user):
        resp = client.get(f'/api/playlists/by-beatmaker/{other_user.username}')
        assert resp.status_code == 200
        assert resp.json['data'] == []


# ── GET /api/playlists/containing/<tid>/by/<uname> ───────────────────────────

class TestGetContaining:

    def test_returns_playlist_id_when_track_present(self, client, user, playlist_with_track, track):
        resp = client.get(f'/api/playlists/containing/{track.id}/by/{user.username}')
        assert resp.status_code == 200
        assert playlist_with_track.id in resp.json['data']

    def test_returns_empty_when_track_not_in_any_playlist(self, client, user, playlist, track):
        resp = client.get(f'/api/playlists/containing/{track.id}/by/{user.username}')
        assert resp.status_code == 200
        assert resp.json['data'] == []

    def test_returns_404_for_unknown_user(self, client, track):
        resp = client.get(f'/api/playlists/containing/{track.id}/by/nonexistent99')
        assert resp.status_code == 404
