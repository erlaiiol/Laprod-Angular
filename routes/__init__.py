"""
Blueprints Registry
Importe tous les blueprints pour faciliter leur enregistrement dans app.py
"""

from .premium_api import premium_api_bp

from .tracks_api import tracks_api_bp
from .tags_filters_api import tags_filters_api_bp
from .auth_api import auth_api_bp
from .toplines_api import toplines_api_bp
from .payment_track_api import payment_track_api_bp
from .wallet_api import wallet_api_bp
from .contracts_api import contracts_api_bp
from .stripe_connect_api import stripe_connect_api_bp
from .main_api import main_api_bp
from .dashboard_api import dashboard_api_bp
from .purchases_api import purchases_api_bp
from .favorites_api import favorites_api_bp
from .mixmaster_api import (
    mixmaster_api_bp,
    cud_mixmaster_artist_api_bp,
    cud_mixmaster_engineer_api_bp,
)
from .payment_mixmaster_api import payment_mixmaster_api_bp
from .stripe_webhook_api import stripe_webhook_bp
from .mixmaster_media_api import mixmaster_media_api_bp
from .admin_api import admin_api_bp
from .job_status_api import job_status_api
from .contract_builder_api import contract_builder_api_bp
from .contract_analyzer_api import contract_analyzer_api_bp
from .playlist_api import playlist_bp
from .invoice_api import invoice_api_bp
from .licenses_api import licenses_api_bp
from .testimonials_api import testimonials_api_bp

__all__ = [
    'premium_api_bp',
    'tracks_api_bp',
    'tags_filters_api_bp',
    'auth_api_bp',
    'toplines_api_bp',
    'payment_track_api_bp',
    'wallet_api_bp',
    'contracts_api_bp',
    'stripe_connect_api_bp',
    'main_api_bp',
    'dashboard_api_bp',
    'purchases_api_bp',
    'favorites_api_bp',
    'mixmaster_api_bp',
    'cud_mixmaster_artist_api_bp',
    'cud_mixmaster_engineer_api_bp',
    'payment_mixmaster_api_bp',
    'stripe_webhook_bp',
    'mixmaster_media_api_bp',
    'admin_api_bp',
    'job_status_api',
    'contract_builder_api_bp',
    'contract_analyzer_api_bp',
    'playlist_bp',
    'invoice_api_bp',
    'licenses_api_bp',
    'testimonials_api_bp',
]