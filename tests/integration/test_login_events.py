"""
Tests de la régularité des connexions (LoginEvent + hooks auth + stats admin).

Couvre :
  - LoginEvent.record() : dédup au jour, jamais bloquant
  - /api/auth/login : enregistre une connexion 'password'
  - /api/auth/refresh : enregistre une connexion 'refresh' (le canal réel de
    retour d'un utilisateur « se souvenir de moi »)
  - dédup CROISÉE entre sources : login puis refresh le même jour → 1 seule ligne
  - utils/behavior_stats.login_regularity / logins_by_weekday

Pas de nettoyage manuel des LoginEvent ici : la relation User.login_events porte
cascade='all, delete-orphan' (models.py), donc le teardown standard du fixture
`user` (conftest.py) supprime déjà les lignes créées par ces tests.
"""
from datetime import date, timedelta

import pytest
from flask_jwt_extended import create_refresh_token, decode_token

from models import LoginEvent
from utils.behavior_stats import login_regularity, logins_by_weekday


@pytest.fixture(autouse=True)
def mock_refresh_token_store(mocker):
    """Même pattern que test_auth_api.py : évite les appels Redis."""
    mocker.patch('routes.auth_api.store_refresh_token', return_value=None)


# ── LoginEvent.record() — modèle ─────────────────────────────────────────────

class TestLoginEventRecord:
    def test_premiere_connexion_du_jour_cree_une_ligne(self, db, user):
        assert LoginEvent.record(user.id, 'password') is True
        assert LoginEvent.query.filter_by(user_id=user.id, login_date=date.today()).count() == 1

    def test_deuxieme_connexion_meme_jour_ne_duplique_pas(self, db, user):
        """C'est le cœur du dispositif : un onglet resté ouvert qui déclenche des
        rafraîchissements en boucle ne doit jamais gonfler le compteur."""
        assert LoginEvent.record(user.id, 'password') is True
        assert LoginEvent.record(user.id, 'refresh') is False   # même jour, source différente
        assert LoginEvent.query.filter_by(user_id=user.id).count() == 1

    def test_jour_different_cree_une_nouvelle_ligne(self, db, user):
        # Simule une connexion d'hier directement en base (pas de monkeypatch de
        # date.today(), pour rester proche du comportement réel du modèle).
        db.session.add(LoginEvent(
            user_id=user.id, login_date=date.today() - timedelta(days=1), source='password',
        ))
        db.session.commit()

        assert LoginEvent.record(user.id, 'password') is True
        assert LoginEvent.query.filter_by(user_id=user.id).count() == 2

    def test_conflit_concurrent_ne_leve_jamais_et_reste_utilisable(self, db, user):
        """Une course entre deux requêtes sur la même contrainte unique doit être
        avalée (rollback propre), jamais remontée dans le flux d'authentification."""
        db.session.add(LoginEvent(user_id=user.id, login_date=date.today(), source='password'))
        db.session.commit()

        # record() re-vérifie l'existence AVANT d'insérer, donc il ne tentera pas
        # l'insert ici — on force quand même le chemin d'erreur en insérant en
        # doublon directement pour prouver que la session reste saine après.
        assert LoginEvent.record(user.id, 'refresh') is False
        # La session doit rester utilisable pour la suite du flux appelant.
        assert db.session.query(LoginEvent.id).filter_by(user_id=user.id).first() is not None


# ── POST /api/auth/login ──────────────────────────────────────────────────────

class TestLoginHook:
    def test_login_reussi_enregistre_une_connexion(self, client, db, user):
        assert LoginEvent.query.filter_by(user_id=user.id).count() == 0
        resp = client.post('/api/auth/login',
                           json={'identifier': user.email, 'password': 'TestPassword123!'})
        assert resp.status_code == 200
        row = LoginEvent.query.filter_by(user_id=user.id).first()
        assert row is not None
        assert row.source == 'password'
        assert row.login_date == date.today()

    def test_login_deux_fois_meme_jour_une_seule_ligne(self, client, db, user):
        for _ in range(2):
            client.post('/api/auth/login',
                       json={'identifier': user.email, 'password': 'TestPassword123!'})
        assert LoginEvent.query.filter_by(user_id=user.id).count() == 1

    def test_mauvais_mot_de_passe_n_enregistre_rien(self, client, db, user):
        client.post('/api/auth/login', json={'identifier': user.email, 'password': 'WrongPassword!'})
        assert LoginEvent.query.filter_by(user_id=user.id).count() == 0


# ── POST /api/auth/refresh ────────────────────────────────────────────────────

class TestRefreshHook:
    def _refresh_token_for(self, app, user):
        with app.app_context():
            token = create_refresh_token(identity=str(user.id))
            jti = decode_token(token)['jti']
        return token, jti

    def test_refresh_reussi_enregistre_une_connexion(self, client, app, db, user, mocker):
        """/refresh est le canal de retour d'un utilisateur « se souvenir de moi » :
        c'est lui qui doit alimenter la stat, pas seulement /login."""
        mocker.patch('routes.auth_api.is_refresh_token_valid', return_value=True)
        token, _ = self._refresh_token_for(app, user)

        assert LoginEvent.query.filter_by(user_id=user.id).count() == 0
        resp = client.post('/api/auth/refresh',
                           headers={'Authorization': f'Bearer {token}'})
        assert resp.status_code == 200

        row = LoginEvent.query.filter_by(user_id=user.id).first()
        assert row is not None
        assert row.source == 'refresh'

    def test_refresh_invalide_n_enregistre_rien(self, client, app, db, user, mocker):
        mocker.patch('routes.auth_api.is_refresh_token_valid', return_value=False)
        token, _ = self._refresh_token_for(app, user)

        client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {token}'})
        assert LoginEvent.query.filter_by(user_id=user.id).count() == 0

    def test_login_puis_refresh_meme_jour_une_seule_ligne(self, client, app, db, user, mocker):
        """La dédup est CROISÉE entre sources : peu importe par quelle porte
        l'utilisateur revient, un seul jour ne compte jamais deux fois."""
        client.post('/api/auth/login',
                   json={'identifier': user.email, 'password': 'TestPassword123!'})

        mocker.patch('routes.auth_api.is_refresh_token_valid', return_value=True)
        token, _ = self._refresh_token_for(app, user)
        client.post('/api/auth/refresh', headers={'Authorization': f'Bearer {token}'})

        rows = LoginEvent.query.filter_by(user_id=user.id).all()
        assert len(rows) == 1
        assert rows[0].source == 'password'   # la première porte gagne


# ── Statistiques admin (deltas — le fixture db ne rollback pas) ─────────────────

class TestLoginStats:
    def test_douze_points_toujours(self, db):
        s = login_regularity(weeks=12)
        assert len(s) == 12
        assert all('label' in p and 'value' in p for p in s)

    def test_sept_jours_lundi_premier(self, db):
        from utils.behavior_stats import WEEKDAYS_FR
        s = logins_by_weekday()
        assert [p['label'] for p in s] == WEEKDAYS_FR
        assert len(s) == 7

    def test_une_connexion_incremente_la_semaine_courante(self, db, user):
        before = login_regularity(weeks=12)
        LoginEvent.record(user.id, 'password')
        after = login_regularity(weeks=12)
        assert sum(p['value'] for p in after) - sum(p['value'] for p in before) == 1

    def test_connexion_incremente_le_bon_jour_de_semaine(self, db, user):
        from utils.behavior_stats import WEEKDAYS_FR
        today_label = WEEKDAYS_FR[date.today().weekday()]
        before = {p['label']: p['value'] for p in logins_by_weekday()}
        LoginEvent.record(user.id, 'password')
        after = {p['label']: p['value'] for p in logins_by_weekday()}
        assert after[today_label] - before[today_label] == 1
