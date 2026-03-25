"""
Blueprints Registry
Importe tous les blueprints pour faciliter leur enregistrement dans app.py
"""

# Blueprints actuellement créés
from .auth import auth_bp
from .main import main_bp
from .api import api_bp
from .admin import admin_bp
from .audio import audio_bp
from .payment import payment_bp
from .contracts import contracts_bp
from .stripe_connect import stripe_connect_bp
from .tracks import tracks_bp
from .toplines import toplines_bp
from .mixmaster import mixmaster_bp
from .favorites import favorites_bp
from .premium import premium_bp
from .wallet import wallet_bp
from .tracks_api import tracks_api_bp
from .cud_tracks_api import cud_tracks_api_bp
from .tags_filters_api import tags_filters_api_bp
from .auth_api import auth_api_bp


__all__ = [
    'auth_bp',
    'main_bp',
    'tracks_bp',
    'admin_bp',
    'api_bp',
    'payment_bp',
    'contracts_bp',
    'stripe_connect_bp',
    'audio_bp',
    'toplines_bp',
    'mixmaster_bp',
    'favorites_bp',
    'premium_bp',
    'wallet_bp',
    'tracks_api_bp',
    'cud_tracks_api_bp',
    'tags_filters_api_bp',
    'auth_api_bp'
]