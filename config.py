"""
Configuration LaProd - PostgreSQL
"""
import os
from dotenv import load_dotenv
from pathlib import Path
from datetime import timedelta

load_dotenv()

# Chemin de base du projet (dossier contenant config.py)
BASE_DIR = Path(__file__).resolve().parent

# ============================================
# CONFIGURATION POSTGRESQL
# ============================================

# Option 1 : Utiliser DATABASE_URL complète (production, Railway, Heroku, etc.)
DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    # Certains services (Heroku) utilisent postgres:// au lieu de postgresql://
    # On corrige si nécessaire
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    # Note: Database URL logged in app.py

else:
    # Option 2 : Construire depuis variables séparées (développement local)
    DB_USER = os.environ.get('DB_USER', 'laprod_user')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', 'password')
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'laprod_db')

    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    # Note: Database connection logged in app.py

# Désactiver le tracking des modifications (économise de la mémoire)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Configuration PostgreSQL optimisée
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,              # Nombre de connexions dans le pool
    'pool_recycle': 3600,         # Recycler les connexions après 1h
    'pool_pre_ping': True,        # Vérifier les connexions avant utilisation
    'max_overflow': 20,           # Connexions supplémentaires si pool saturé
    'pool_timeout': 30,           # Timeout si pas de connexion disponible
    'echo': False,                # Mettre True pour debug SQL
}

# ============================================
# CONFIGURATION OAUTH
# ============================================
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


# ============================================
# CONFIGURATION STRIPE
# ============================================
STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY')
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET')

# Vérifier que les clés existent
if not all([STRIPE_PUBLIC_KEY, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET]):
    raise ValueError("️ ERREUR : Clés Stripe manquantes dans .env !")

DEMO_MODE = os.environ.get('DEMO_MODE', 'True').lower() == 'true'

# Commission de la plateforme (10%)
PLATFORM_COMMISSION = 0.10

# ============================================
# CONFIGURATION DES UPLOADS
# ============================================
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'ogg', 'flac', 'zip', 'rar'}
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
MAX_AUDIO_SIZE = 100 * 1024 * 1024  # 100 MB
MIN_MP3_SIZE = 1.2 * 1024 * 1024    # 1.2 MB (~1min10 en 128kbps, anti-snippet)
MIN_WAV_SIZE = 10 * 1024 * 1024     # 10 MB (~1min en 44.1kHz/16bit stereo)
MIN_STEMS_SIZE = 40 * 1024 * 1024   # 40 MB (archive de pistes FLAC separees)
MAX_IMAGE_SIZE = 5 * 1024 * 1024    # 5 MB
MAX_TOPLINE_SIZE = 5 * 1024 * 1024  # 5 MB (force MP3 pour toplines)
MAX_ARCHIVE_SIZE = 800 * 1024 * 1024 # 800 MB pour les archives (mixmasterrequest)

# ============================================
# WATERMARK
# ============================================
WATERMARK_AUDIO_PATH = BASE_DIR / 'static' / 'audio' / 'watermark.mp3'
PREVIEW_DURATION = 90  # 1:30 en secondes
WATERMARK_INTERVALS = [20, 45]  # Positions en secondes où insérer le watermark

DEFAULT_PRICE_MP3 = 9.99
DEFAULT_PRICE_WAV = 19.99
DEFAULT_PRICE_STEMS = 49.99



# ============================================
# CONFIGURATION DES CONTRATS BEATS/TRACKS
# ============================================

# Prix des options de contrat (en euros)
CONTRACT_EXCLUSIVE_PRICE = 150

# Durées et prix des contrats
CONTRACT_DURATIONS = {
    '3': 5,   # 3 ans : 5€
    '5': 10,   # 5 ans : 10€
    '10': 15,  # 10 ans : 15€
    'lifetime': 50  # À vie : 50€
}

# Droits d'exploitation
CONTRACT_MECHANICAL_REPRODUCTION_PRICE = 30
CONTRACT_PUBLIC_SHOW_PRICE = 40
CONTRACT_ARRANGEMENT_PRICE = 10

# Seuil pour l'inclusion automatique des droits
CONTRACT_AUTO_RIGHTS_THRESHOLD = 30

# Prix des territoires
CONTRACT_TERRITORY_FRANCE = 0
CONTRACT_TERRITORY_EUROPE = 5
CONTRACT_TERRITORY_WORLD = 10



# ============================================
# SACEM CONFIGURATION
# ============================================
SACEM_URL = "https://www.sacem.fr"

SACEM_INFO_MESSAGE = """
Ce contrat doit être accompagné des démarches auprès de la SACEM.
Pour plus d'informations, consultez www.sacem.fr
"""

# ============================================
# DOSSIERS DE L'APPLICATION
# ============================================
# Tous les chemins sont des objets Path (pathlib)
UPLOAD_FOLDER = BASE_DIR / 'static' / 'audio'
CONTRACTS_FOLDER = BASE_DIR / 'static' / 'contracts'
IMAGES_FOLDER = BASE_DIR / 'static' / 'images'
PROFILES_FOLDER = BASE_DIR / 'static' / 'images' / 'profiles'

# DOSSIERS MIX/MASTER
MIXMASTER_UPLOADS_FOLDER = BASE_DIR / 'static' / 'mixmaster' / 'uploads'
MIXMASTER_PROCESSED_FOLDER = BASE_DIR / 'static' / 'mixmaster' / 'processed'
MIXMASTER_PREVIEWS_FOLDER = BASE_DIR / 'static' / 'mixmaster' / 'previews'
MIXMASTER_SAMPLES_FOLDER = BASE_DIR / 'static' / 'mixmaster' / 'samples'

# ============================================
# SÉCURITÉ
# ============================================
MAX_FILE_SIZE_MB = 500
SESSION_DURATION_DAYS = 30

# ============================================
# MESSAGES FLASH
# ============================================
ERROR_MESSAGES = {
    'payment_failed': "Le paiement a échoué. Veuillez réessayer.",
    'file_not_found': "Fichier introuvable.",
    'unauthorized': "Vous n'êtes pas autorisé à accéder à cette ressource.",
    'invalid_format': "Format de fichier invalide.",
    'own_track': "Vous ne pouvez pas acheter votre propre composition.",
}

SUCCESS_MESSAGES = {
    'payment_success': "Paiement confirmé ! Vous pouvez maintenant télécharger vos fichiers.",
    'contract_generated': "Contrat généré avec succès.",
    'upload_success': "Fichier uploadé avec succès.",
}


# ============================================
# MIX/MASTER CONFIGURATION
# ============================================
MIXMASTER_DEPOSIT_PERCENTAGE = 0.30  # Acompte de 30%
MIXMASTER_DEADLINE_DAYS = 7  # Délai de livraison en jours
MIXMASTER_PLATFORM_COMMISSION = 0.10  # Commission plateforme 10%
MIXMASTER_MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB pour les pistes
MIXMASTER_ALLOWED_EXTENSIONS = {'wav', 'zip', 'rar', 'mp3'}


# ============================================
# PREMIUM
# ============================================
PREMIUM_PRICE = 1.99  # Prix en euros pour 30 jours de premium
PREMIUM_DURATION_DAYS = 30  # Durée du premium en jours

# ============================================
# ENVIRONNEMENT
# ============================================
ENV = os.environ.get('FLASK_ENV', 'development')
DEBUG = ENV == 'development'

# ============================================
# JWT SECRET KEY
# ============================================

JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY')

if ENV == 'development':
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
else :
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)

# ============================================
# CONFIGURATION BLEACH POUR SANITIZATION ANTI CROSS SCRIPTING XSS
# ============================================

ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'u', 'a']
ALLOWED_ATTRIBUTES = {'a': ['href', 'title']}

# ==============================================
# CONFIGURATION DES COOKIES
# ==============================================

SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)

# =============================================
# CONFIG FLASK-MAIL
# =============================================

MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
MAIL_USE_SSL = os.environ.get('MAIL_USE_SSL', 'false').lower() == 'true'

# Identifiants
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

# Expéditeur
MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@laprod.net')

# Options
MAIL_MAX_EMAILS = None  # Pas de limite
MAIL_ASCII_ATTACHMENTS = False


# ============================================
# CONFIGURATION SERVEUR
# ============================================


# NOT NEEDED IN PRODUCTION PROD V2
# SERVER_NAME = os.environ.get('SERVER_NAME')