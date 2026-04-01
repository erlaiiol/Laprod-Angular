"""
Extensions Flask - Initialisées sans app pour éviter imports circulaires
AVEC Flask-Migrate pour PostgreSQL + OAuth2
"""
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_migrate import Migrate
from flask_mail import Mail
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from authlib.integrations.flask_client import OAuth
from apscheduler.schedulers.background import BackgroundScheduler
import stripe
import os
import redis

# ============================================
# CRÉER LES EXTENSIONS SANS APP
# ============================================

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
migrate = Migrate()
mail = Mail()
oauth = OAuth()  # OAuth2 pour Google
scheduler = BackgroundScheduler(daemon=True)
jwt = JWTManager()

limiter = Limiter(
    key_func=get_remote_address,
    # CHANGE THIS ABSOLUTELY FOR PRODUCTION PURPOSE TO 300 PER DAY 50 PER HOUR
    default_limits=["300 per day", "50 per hour"],
    storage_uri=os.getenv("REDIS_URL", "redis://redis:6379"),  # Utiliser Redis pour stocker les compteurs de rate limit
)

redis_client: redis.Redis | None = None  # Initialisé dans init_extensions()


# ============================================
# FONCTION D'INITIALISATION
# ============================================

def init_extensions(app):
    """
    Initialise toutes les extensions avec l'app Flask
    À appeler dans app.py : init_extensions(app)
    """
    
    app.logger.info("Initialisation des extensions...")
    
    # Base de données
    db.init_app(app)
    app.logger.info("  OK SQLAlchemy (PostgreSQL)")
    
    # NOUVEAU - Flask-Migrate
    migrate.init_app(app, db)
    app.logger.info("  OK Flask-Migrate (migrations DB)")
    
    # Login Manager
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Vous devez être connecté pour accéder à cette page'
    login_manager.login_message_category = 'warning'
    app.logger.info("  OK Flask-Login")
    
    # CSRF Protection
    csrf.init_app(app)
    app.logger.info("  OK CSRF Protection")
    
    # Rate Limiting
    limiter.init_app(app)
    app.logger.info("  OK Rate Limiting")

    #  OAuth2 - Google
    oauth.init_app(app)

    # flask-mail
    mail.init_app(app)

    # flask-CORS
    CORS(app, origins=['http://localhost:4200'], supports_credentials=True)
    app.logger.info("  OK CORS (Angular dev: localhost:4200)")

    #JWTManager
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        from models import TokenBlocklist
        jti = jwt_payload['jti']
        return db.session.query(TokenBlocklist).filter_by(jti=jti).first() is not None

    # Enregistrer le client Google
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url=app.config['GOOGLE_DISCOVERY_URL'],
        client_kwargs={
            'scope': 'openid email profile'
        }
    )
    app.logger.info("  OK OAuth2 (Google)")

    # Redis
    global redis_client
    redis_client = redis.Redis(
        host=app.config['REDIS_HOST'],
        port=app.config['REDIS_PORT'],
        db=app.config['REDIS_DB'],
        decode_responses=True
    )

    # Talisman (Headers sécurité)
    env = os.environ.get('FLASK_ENV', 'development')

    # ============================================
    # STRIPE - INITIALISATION GLOBALE
    # ============================================
    #  SÉCURITÉ: C'est le SEUL endroit où stripe.api_key doit être configuré
    # Les routes (payment, mixmaster, etc.) utilisent stripe sans reconfigurer la clé
    stripe.api_key = app.config['STRIPE_SECRET_KEY']
    app.logger.debug(f"  OK Stripe (cle: {stripe.api_key[:7]}...)")
    
    if env == 'production':
        # PRODUCTION : Sécurité maximale
        Talisman(
            app,
            force_https=True,
            force_https_permanent=True,
            strict_transport_security=True,
            strict_transport_security_max_age=31536000,  # 1 an
            content_security_policy={
                'default-src': "'self'",
                'script-src': [
                    "'self'",
                    'https://js.stripe.com',
                    'https://cdn.jsdelivr.net',
                ],
                'style-src': [
                    "'self'",
                    "'unsafe-inline'",  # Bootstrap
                    'https://cdn.jsdelivr.net',
                ],
                'img-src': [
                    "'self'",
                    'data:',
                    'https:',
                ],
                'font-src': [
                    "'self'",
                    'https://fonts.gstatic.com',
                    'https://cdn.jsdelivr.net',
                ],
                'connect-src': [
                    "'self'",
                    'https://api.stripe.com',
                    'https://cdn.jsdelivr.net',
                ],
                'frame-src': [
                    'https://js.stripe.com',
                ],
                'media-src': [
                    "'self'",
                    'blob:',
                ],
            },
            content_security_policy_nonce_in=['script-src'],
            feature_policy={
                'geolocation': "'none'",
                'camera': "'none'",
                'microphone': "'self'",
                'payment': "'self'",
            },
        )
        app.logger.info("  OK Talisman (PRODUCTION)")
    else:
        # DÉVELOPPEMENT : Plus souple
        Talisman(
            app,
            force_https=False,
            content_security_policy=None,
        )
        app.logger.info("  OK Talisman (DEVELOPPEMENT)")
    


    app.logger.info("Extensions initialisees")


def init_scheduler(app):
    """
    Démarre APScheduler avec les jobs wallet.
    À appeler après init_extensions(), uniquement dans le processus principal
    (gunicorn worker ou WERKZEUG_RUN_MAIN=true).
    """
    from utils.wallet_jobs import run_pending_to_available_job, run_expiration_job

    if not scheduler.running:
        # Toutes les heures : pending → available
        scheduler.add_job(
            func=run_pending_to_available_job,
            trigger='interval',
            hours=1,
            id='wallet_pending_to_available',
            replace_existing=True,
            args=[app]
        )
        # Chaque nuit à 2h : expiration des fonds >2 ans
        scheduler.add_job(
            func=run_expiration_job,
            trigger='cron',
            hour=2,
            minute=0,
            id='wallet_expiration',
            replace_existing=True,
            args=[app]
        )
        scheduler.start()
        app.logger.info("  OK APScheduler (jobs wallet)")