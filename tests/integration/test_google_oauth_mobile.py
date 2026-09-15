"""
Tests d'intégration — retour OAuth Google vers l'app Android (Custom Tabs).

Contexte : la WebView Capacitor ne peut pas faire l'aller-retour OAuth elle-même
(Google bloque l'auth dans un user-agent WebView embarqué, disallowed_useragent).
Le bouton Google ouvre donc le flow dans un Chrome Custom Tab côté app, avec
?platform=mobile ; google_login() tague alors le state CSRF (":mobile") et
google_callback() redirige vers le schéma custom net.laprod.app:// plutôt que
vers le site web quand ce tag est présent.

Couvre :
  - google_login() sans ?platform=mobile : state non tagué (comportement web inchangé)
  - google_login()?platform=mobile : state tagué ":mobile", entropie conservée
  - google_callback() avec state tagué : redirige vers net.laprod.app://oauth-callback
  - google_callback() sans tag : redirige vers FRONTEND_URL/oauth-callback (régression)
"""
import uuid
from unittest.mock import MagicMock

import pytest

from extensions import oauth


@pytest.fixture()
def google_user(db, bound_factories):
    """Utilisateur déjà lié à Google — chemin le plus simple du callback (CAS 1).
    google_id unique par test : la fixture `db` ne rollback pas entre tests."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(email_verified=True, user_type_selected=True)
    u.google_id = f'google-sub-{uuid.uuid4().hex[:12]}'
    u.oauth_provider = 'google'
    db.session.commit()
    return u


def _mock_userinfo(mocker, user_email, google_id):
    mocker.patch.object(oauth.google, 'authorize_access_token', return_value={'access_token': 'x'})
    resp = MagicMock()
    resp.json.return_value = {
        'sub': google_id,
        'email': user_email,
        'given_name': 'Test',
        'picture': None,
        'email_verified': True,
    }
    mocker.patch.object(oauth.google, 'get', return_value=resp)


class TestGoogleLoginStateTagging:

    def test_web_login_does_not_tag_state(self, client, mocker):
        mock_redirect = mocker.patch.object(
            oauth.google, 'authorize_redirect', return_value=MagicMock(),
        )
        client.get('/api/auth/google/login')

        assert mock_redirect.call_args.kwargs.get('state') is None

    def test_mobile_login_tags_state(self, client, mocker):
        mock_redirect = mocker.patch.object(
            oauth.google, 'authorize_redirect', return_value=MagicMock(),
        )
        client.get('/api/auth/google/login?platform=mobile')

        state = mock_redirect.call_args.kwargs.get('state')
        assert state is not None
        assert state.endswith(':mobile')
        # Le préfixe aléatoire doit rester suffisamment long (protection CSRF réelle)
        assert len(state.split(':mobile')[0]) >= 24


class TestGoogleCallbackRedirectDestination:

    def test_mobile_state_redirects_to_custom_scheme(self, client, db, google_user, mocker):
        _mock_userinfo(mocker, google_user.email, google_user.google_id)

        resp = client.get('/api/auth/google/callback?state=abc123:mobile&code=whatever')

        assert resp.status_code == 302
        assert resp.location.startswith('net.laprod.app://oauth-callback?code=')

    def test_web_state_redirects_to_frontend_url(self, client, db, app, google_user, mocker):
        _mock_userinfo(mocker, google_user.email, google_user.google_id)

        resp = client.get('/api/auth/google/callback?state=abc123&code=whatever')

        assert resp.status_code == 302
        frontend = app.config.get('FRONTEND_URL', 'https://laprod.net')
        assert resp.location.startswith(f'{frontend}/oauth-callback?code=')
        assert 'net.laprod.app://' not in resp.location

    def test_mobile_state_on_oauth_failure_still_returns_to_app(self, client, db, mocker):
        """Même en erreur, un utilisateur parti du mobile doit revenir dans l'app
        via /oauth-callback (pas /login, que le listener natif n'intercepte pas —
        cf. NativeShellService.init()) plutôt que rester coincé sur l'onglet
        Chrome Custom Tab."""
        mocker.patch.object(
            oauth.google, 'authorize_access_token', side_effect=Exception('boom'),
        )

        resp = client.get('/api/auth/google/callback?state=abc123:mobile')

        assert resp.status_code == 302
        assert resp.location == 'net.laprod.app://oauth-callback?error=oauth_failed'

    def test_web_state_on_oauth_failure_redirects_to_login(self, client, db, app, mocker):
        """Régression : le chemin web garde /login?error=..., inchangé."""
        mocker.patch.object(
            oauth.google, 'authorize_access_token', side_effect=Exception('boom'),
        )

        resp = client.get('/api/auth/google/callback?state=abc123')

        frontend = app.config.get('FRONTEND_URL', 'https://laprod.net')
        assert resp.location == f'{frontend}/login?error=oauth_failed'
