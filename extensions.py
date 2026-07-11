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

_is_dev = os.environ.get('FLASK_ENV', 'development') == 'development'


def _rate_limit_key():
    """
    Clé de rate-limiting :
    - Utilisateur JWT connecté → clé = "user:<id>" (pas d'impact CG-NAT).
    - Visiteur anonyme → clé = IP (comportement Flask-Limiter par défaut).
    """
    from flask import request as _req
    try:
        from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
        verify_jwt_in_request(optional=True)
        uid = get_jwt_identity()
        if uid:
            return f"user:{uid}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key,
    # En développement : aucune limite globale (les @limiter.limit() par route restent actifs).
    # En production :
    #   • 2 000 requêtes/jour  (≈ 83/heure en usage continu — large pour une session active)
    #   • 200 requêtes/heure   (CG-NAT : clé = user_id si connecté, IP sinon)
    default_limits=[] if _is_dev else ["2000 per day", "200 per hour"],
    storage_uri=os.getenv("REDIS_URL", "redis://redis:6379"),
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
    # Utilise Redis comme cache pour le state OAuth (multi-workers safe).
    # Sans ça, Authlib stocke le state dans le cookie de session Flask qui
    # peut être perdu entre google/login (worker A) et google/callback (worker B).
    _oauth_redis = redis.Redis(
        host=app.config['REDIS_HOST'],
        port=app.config['REDIS_PORT'],
        db=app.config['REDIS_DB'],
        decode_responses=True,
    )
    oauth.init_app(app, cache=_oauth_redis)

    # flask-mail
    mail.init_app(app)

    # flask-CORS
    _cors_origins = [o.strip() for o in os.environ.get('CORS_ORIGINS', 'http://localhost:4200').split(',') if o.strip()]
    # SÉCURITÉ : en production, on rejette les origines http:// en clair (sauf
    # localhost pour d'éventuels outils internes). Avec supports_credentials=True,
    # une origine http:// autoriserait des requêtes credentialisées interceptables.
    # Les schemes natifs (capacitor://, ionic://) et https:// sont conservés.
    if not _is_dev:
        _filtered = [
            o for o in _cors_origins
            if not (o.startswith('http://') and 'localhost' not in o and '127.0.0.1' not in o)
        ]
        _dropped = set(_cors_origins) - set(_filtered)
        if _dropped:
            app.logger.warning(f"  CORS : origines http:// non sécurisées ignorées en prod : {sorted(_dropped)}")
        _cors_origins = _filtered
    CORS(app, origins=_cors_origins, supports_credentials=True)
    app.logger.info(f"  OK CORS (origins: {_cors_origins})")

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
            force_https=False,          # nginx gère la redirection HTTP→HTTPS
            force_https_permanent=False,
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

    # ── Checks dépendances système ─────────────────────────────────────────────
    _check_system_deps(app)


def _check_system_deps(app):
    """Vérifie la disponibilité des dépendances système critiques au démarrage."""
    import subprocess

    # python-magic / libmagic
    try:
        import magic
        magic.from_buffer(b'\x00' * 16)   # test réel, pas juste l'import
        app.logger.info("  OK python-magic (validation MIME)")
    except Exception as e:
        app.logger.critical(f"  ERREUR python-magic indisponible — upload désactivé: {e}")

    # ffmpeg (pydub, toplines, watermark)
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            version_line = result.stdout.splitlines()[0] if result.stdout else '?'
            app.logger.info(f"  OK ffmpeg ({version_line})")
        else:
            app.logger.critical("  ERREUR ffmpeg non fonctionnel (returncode != 0)")
    except FileNotFoundError:
        app.logger.critical("  ERREUR ffmpeg introuvable — traitement audio désactivé")
    except Exception as e:
        app.logger.critical(f"  ERREUR ffmpeg: {e}")


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
        # Chaque nuit à 3h : corrélations pour l'algorithme de recommandation
        from utils.recommendation_jobs import run_correlation_job
        scheduler.add_job(
            func=run_correlation_job,
            trigger='cron',
            hour=3,
            minute=0,
            id='recommendation_correlations',
            replace_existing=True,
            args=[app]
        )
        # Chaque nuit à 4h : purge RGPD des comptes en attente de suppression (>30j)
        from utils.gdpr_purge import run_gdpr_purge_job
        scheduler.add_job(
            func=run_gdpr_purge_job,
            trigger='cron',
            hour=4,
            minute=0,
            id='gdpr_purge',
            replace_existing=True,
            args=[app]
        )
        # ── Jobs cycle de vie des licences ──────────────────────────────────
        from utils.scheduled_tasks import (
            run_contract_expiry_update,
            run_expiry_notifications,
            run_sole_licensee_notifications,
        )
        # Chaque nuit à 0h : expire les licences échues + libère les exclusivités
        scheduler.add_job(
            func=run_contract_expiry_update,
            trigger='cron',
            hour=0,
            minute=5,
            id='contract_expiry_update',
            replace_existing=True,
            args=[app]
        )
        # Chaque matin à 8h : rappels d'expiration (90/30/7/1 jours)
        scheduler.add_job(
            func=run_expiry_notifications,
            trigger='cron',
            hour=8,
            minute=0,
            id='expiry_notifications',
            replace_existing=True,
            args=[app]
        )
        # 1er de chaque mois à 9h : notification "unique licencié"
        scheduler.add_job(
            func=run_sole_licensee_notifications,
            trigger='cron',
            day=1,
            hour=9,
            minute=0,
            id='sole_licensee_notifications',
            replace_existing=True,
            args=[app]
        )
        # Chaque lundi à 9h : rappel Stripe Connect aux beatmakers/mix engineers non configurés
        from utils.scheduled_tasks import run_stripe_reminder_job
        scheduler.add_job(
            func=run_stripe_reminder_job,
            trigger='cron',
            day_of_week='mon',
            hour=9,
            minute=0,
            id='stripe_connect_reminder',
            replace_existing=True,
            args=[app]
        )
        # Chaque mercredi à 10h : re-engagement des utilisateurs inactifs 7j+
        from utils.scheduled_tasks import run_reengagement_emails
        scheduler.add_job(
            func=run_reengagement_emails,
            trigger='cron',
            day_of_week='wed',
            hour=10,
            minute=0,
            id='reengagement_emails',
            replace_existing=True,
            args=[app]
        )
        # Toutes les heures : purge des toplines guest expirées (TTL 24h, non réclamées)
        from utils.scheduled_tasks import run_guest_topline_cleanup
        scheduler.add_job(
            func=run_guest_topline_cleanup,
            trigger='interval',
            hours=1,
            id='guest_topline_cleanup',
            replace_existing=True,
            args=[app]
        )
        scheduler.start()
        app.logger.info("  OK APScheduler (jobs wallet + recommandations + licences + stripe + re-engagement)")