"""
Tests d'intégration — routes/contract_analyzer_api.py

POST /api/contract-analyzer/analyze : réservé aux abonnés premium actifs (amateur ou pro).
analyze_contract() (appel IA) est toujours mocké — aucun appel externe réel en test.
"""
import io
import json
from unittest.mock import patch


def _post_headers(auth_headers: dict) -> dict:
    """Extrait uniquement le header Authorization (sans Content-Type JSON)."""
    return {'Authorization': auth_headers['Authorization']}


def _pdf_file(name='contrat.pdf'):
    """BytesIO simulant un PDF minimal pour multipart/form-data."""
    return (io.BytesIO(b'%PDF-1.4\n%...\n'), name)


FAKE_ANALYSIS = {
    'contract_type': 'Contrat de licence',
    'overall_score': 70,
    'risk_level': 'modéré',
    'summary': 'Résumé de test.',
    'detected_parties': [],
    'critical_articles': [],
    'sections': [],
    'missing_clauses': [],
    'positive_points': [],
    'career_advice': '',
    'negotiation_checklist': [],
}


class TestAnalyze:

    def test_requires_authentication(self, client):
        resp = client.post(
            '/api/contract-analyzer/analyze',
            data={'contract_pdf': _pdf_file()},
            content_type='multipart/form-data',
        )
        assert resp.status_code == 401

    def test_non_premium_user_forbidden(self, client, admin_headers, admin_user, db):
        """admin_user est 'free' par défaut (fixture) : doit être rejeté avant même
        de regarder le fichier envoyé."""
        assert admin_user.subscription_plan == 'free'
        resp = client.post(
            '/api/contract-analyzer/analyze',
            data={'contract_pdf': _pdf_file()},
            headers=_post_headers(admin_headers),
            content_type='multipart/form-data',
        )
        assert resp.status_code == 403
        data = json.loads(resp.data)
        assert data['success'] is False

    def test_premium_user_missing_file(self, client, auth_headers, user):
        """user (fixture) est Pro donc premium actif — mais sans fichier, doit échouer 400."""
        resp = client.post(
            '/api/contract-analyzer/analyze',
            data={},
            headers=_post_headers(auth_headers),
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_premium_user_rejects_non_pdf(self, client, auth_headers, user):
        resp = client.post(
            '/api/contract-analyzer/analyze',
            data={'contract_pdf': (io.BytesIO(b'not a pdf'), 'contrat.txt')},
            headers=_post_headers(auth_headers),
            content_type='multipart/form-data',
        )
        assert resp.status_code == 400

    def test_premium_user_gets_analysis(self, client, auth_headers, user):
        with patch('routes.contract_analyzer_api.analyze_contract', return_value=FAKE_ANALYSIS) as mock_analyze:
            resp = client.post(
                '/api/contract-analyzer/analyze',
                data={'contract_pdf': _pdf_file()},
                headers=_post_headers(auth_headers),
                content_type='multipart/form-data',
            )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data['success'] is True
        assert data['data']['analysis'] == FAKE_ANALYSIS
        mock_analyze.assert_called_once()

    def test_amateur_plan_is_also_premium(self, client, app, db, bound_factories):
        """is_premium_active couvre amateur ET pro — l'accès ne doit pas se limiter à pro."""
        from datetime import datetime, timedelta
        from flask_jwt_extended import create_access_token
        from tests.factories.user_factory import UserFactory

        amateur = UserFactory(
            subscription_plan='amateur',
            premium_expires_at=datetime.now() + timedelta(days=10),
        )
        db.session.commit()
        with app.app_context():
            token = create_access_token(identity=str(amateur.id))

        with patch('routes.contract_analyzer_api.analyze_contract', return_value=FAKE_ANALYSIS):
            resp = client.post(
                '/api/contract-analyzer/analyze',
                data={'contract_pdf': _pdf_file()},
                headers={'Authorization': f'Bearer {token}'},
                content_type='multipart/form-data',
            )
        assert resp.status_code == 200

    def test_analysis_failure_returns_error_feedback(self, client, auth_headers, user):
        with patch('routes.contract_analyzer_api.analyze_contract', side_effect=ValueError('PDF illisible')):
            resp = client.post(
                '/api/contract-analyzer/analyze',
                data={'contract_pdf': _pdf_file()},
                headers=_post_headers(auth_headers),
                content_type='multipart/form-data',
            )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert data['success'] is False
        assert 'PDF illisible' in data['feedback']['message']
