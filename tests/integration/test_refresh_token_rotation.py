"""Refresh rotation against an isolated Redis process (including the atomic Lua script)."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import timedelta
import shutil
import tempfile
import subprocess
import time

import pytest
from flask_jwt_extended import create_refresh_token, decode_token


@pytest.fixture()
def token_redis(tmp_path, monkeypatch):
    executable = shutil.which('redis-server')
    if not executable:
        pytest.skip('redis-server is needed to exercise atomic rotation')
    import redis
    import extensions
    directory = tempfile.TemporaryDirectory(prefix='laprod-jwt-', dir='/tmp')
    socket = str(Path(directory.name) / 'redis.sock')
    process = subprocess.Popen([
        executable, '--port', '0', '--unixsocket', socket,
        '--save', '', '--appendonly', 'no',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    connection = redis.Redis(
        unix_socket_path=socket, decode_responses=True, socket_timeout=1,
        retry=redis.retry.Retry(redis.backoff.NoBackoff(), 0),
    )
    try:
        for _ in range(100):
            try:
                if connection.ping():
                    break
            except redis.ConnectionError:
                time.sleep(0.02)
        else:
            raise RuntimeError('Test Redis failed to start')
        monkeypatch.setattr(extensions, 'redis_client', connection)
        yield connection
    finally:
        connection.close()
        process.terminate()
        process.wait(timeout=5)
        directory.cleanup()


def make_refresh(user, days=30):
    from helpers import store_refresh_token
    token = create_refresh_token(identity=str(user.id), expires_delta=timedelta(days=days))
    claims = decode_token(token)
    store_refresh_token(user.id, claims['jti'], days * 86400)
    return token, claims


def refresh(client, token):
    return client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {token}'})


@pytest.mark.parametrize('days', [1, 30])
def test_rotation_extends_original_session_policy(client, user, token_redis, days):
    token, claims = make_refresh(user, days)
    response = refresh(client, token)
    assert response.status_code == 200
    tokens = response.json['data']
    new = decode_token(tokens['refresh_token'])
    assert new['jti'] != claims['jti']
    assert new['session_lifetime'] == days * 86400
    assert new['exp'] - new['iat'] == days * 86400
    assert decode_token(tokens['access_token'])['type'] == 'access'
    assert 0 < token_redis.ttl(f"refresh_token:{user.id}:{claims['jti']}") <= 60
    # Once grace has ended, the old JWT cannot renew the session.
    token_redis.delete(f"refresh_token:{user.id}:{claims['jti']}")
    assert refresh(client, token).status_code == 401
    assert refresh(client, tokens['refresh_token']).status_code == 200


def test_lost_response_or_concurrent_tab_receives_identical_tokens(client, user, token_redis):
    token, _ = make_refresh(user)
    first = refresh(client, token)
    retry = refresh(client, token)
    assert first.status_code == retry.status_code == 200
    assert first.json['data'] == retry.json['data']
    assert len(token_redis.keys(f'refresh_token:{user.id}:*')) == 2


def test_atomic_rotation_only_creates_one_successor(user, token_redis):
    from helpers import rotate_refresh_token, store_refresh_token
    store_refresh_token(user.id, 'old', 3600)
    def rotate(index):
        return rotate_refresh_token(user.id, 'old', f'new-{index}', 3600,
                                    {'refresh_token': f'candidate-{index}'})
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(rotate, range(4)))
    assert all(result == results[0] for result in results)
    assert len(token_redis.keys(f'refresh_token:{user.id}:*')) == 2


def test_revocation_invalidates_both_grace_and_current_tokens(client, user, token_redis):
    from helpers import revoke_all_refresh_tokens
    token, _ = make_refresh(user)
    new = refresh(client, token).json['data']['refresh_token']
    revoke_all_refresh_tokens(user.id)
    assert refresh(client, token).status_code == 401
    assert refresh(client, new).status_code == 401
