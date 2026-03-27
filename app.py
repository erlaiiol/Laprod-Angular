"""
LaProd - Application Factory (PostgreSQL + Flask-Migrate)
"""
from flask import Flask, session
import os
from dotenv import load_dotenv
from helpers import admin_required
from pathlib import Path
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()


def create_app():
    """Factory pour créer l'application Flask"""
    
    app = Flask(__name__)
    
    # ============================================
    # PROXY FIX POUR NGINX (CRITIQUE EN PRODUCTION)
    # ============================================

    if os.environ.get('FLASK_ENV') == 'production':
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,           # X-Forwarded-For
            x_proto=1,         # X-Forwarded-Proto (HTTPS detection)
            x_host=1,          # X-Forwarded-Host
            x_prefix=1         # X-Script-Name
        )
    
    # ============================================
    # CONFIGURATION DEPUIS config.py
    # ============================================
    
    # Secret key depuis .env
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
    if not app.config['SECRET_KEY']:
        raise ValueError("ERREUR : SECRET_KEY manquante dans .env !")
    
    # Import de TOUTE la config depuis config.py
    import config

    app.config['DEBUG'] = config.DEBUG

    # Base de données PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = config.SQLALCHEMY_DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = config.SQLALCHEMY_TRACK_MODIFICATIONS
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = config.SQLALCHEMY_ENGINE_OPTIONS

    
    
    # En debug, le reloader lance create_app() 2 fois.
    # On ne log le démarrage que dans le processus qui sert (WERKZEUG_RUN_MAIN=true)
    # ou en production (pas de reloader).
    is_main_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or os.environ.get('FLASK_ENV') == 'production'

    # Cookies

    app.config['SESSION_COOKIE_SECURE'] = config.SESSION_COOKIE_SECURE
    app.config['SESSION_COOKIE_HTTPONLY'] = config.SESSION_COOKIE_HTTPONLY
    app.config['SESSION_COOKIE_SAMESITE'] = config.SESSION_COOKIE_SAMESITE
    app.config['PERMANENT_SESSION_LIFETIME'] = config.PERMANENT_SESSION_LIFETIME
    
    # Uploads
    app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
    app.config['CONTRACTS_FOLDER'] = config.CONTRACTS_FOLDER
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB (pour pistes mixmaster)
    
    # Stripe
    app.config['STRIPE_PUBLIC_KEY'] = config.STRIPE_PUBLIC_KEY
    app.config['STRIPE_SECRET_KEY'] = config.STRIPE_SECRET_KEY
    app.config['STRIPE_WEBHOOK_SECRET'] = config.STRIPE_WEBHOOK_SECRET
    app.config['PLATFORM_COMMISSION'] = config.PLATFORM_COMMISSION

    # SERVER
    # Not NEEDED IN PRODUCTION PROD V2
    # app.config['SERVER_NAME'] = config.SERVER_NAME

    # OAuth Google
    app.config['GOOGLE_CLIENT_ID'] = config.GOOGLE_CLIENT_ID
    app.config['GOOGLE_CLIENT_SECRET'] = config.GOOGLE_CLIENT_SECRET
    app.config['GOOGLE_DISCOVERY_URL'] = config.GOOGLE_DISCOVERY_URL
    
    # Contrats (prix)
    app.config['CONTRACT_EXCLUSIVE_PRICE'] = config.CONTRACT_EXCLUSIVE_PRICE
    app.config['CONTRACT_DURATIONS'] = config.CONTRACT_DURATIONS
    app.config['CONTRACT_MECHANICAL_REPRODUCTION_PRICE'] = config.CONTRACT_MECHANICAL_REPRODUCTION_PRICE
    app.config['CONTRACT_PUBLIC_SHOW_PRICE'] = config.CONTRACT_PUBLIC_SHOW_PRICE
    app.config['CONTRACT_ARRANGEMENT_PRICE'] = config.CONTRACT_ARRANGEMENT_PRICE
    app.config['CONTRACT_TERRITORY_EUROPE'] = config.CONTRACT_TERRITORY_EUROPE
    app.config['CONTRACT_TERRITORY_WORLD'] = config.CONTRACT_TERRITORY_WORLD

    # Mail Flask-Mail
    app.config['MAIL_SERVER'] = config.MAIL_SERVER
    app.config['MAIL_PORT'] = config.MAIL_PORT
    app.config['MAIL_USE_TLS'] = config.MAIL_USE_TLS
    app.config['MAIL_USE_SSL'] = config.MAIL_USE_SSL
    app.config['MAIL_USERNAME'] = config.MAIL_USERNAME
    app.config['MAIL_PASSWORD'] = config.MAIL_PASSWORD
    app.config['MAIL_DEFAULT_SENDER'] = config.MAIL_DEFAULT_SENDER

    #JWTManager
    app.config['JWT_SECRET_KEY'] = config.JWT_SECRET_KEY
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = config.JWT_ACCESS_TOKEN_EXPIRES
    app.config['JWT_BLACKLIST_ENABLED'] = True
    app.config['JWT_BLACKLIST_TOKEN_CHECKS'] = ['access', 'refresh']
    
    if os.environ.get('FLASK_ENV') == 'production':
        if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
            raise RuntimeError("Configuration MAIL incomplète (.env)")
    
    # ============================================
    # CRÉER LES DOSSIERS NÉCESSAIRES
    # ============================================

    config.UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_FOLDER / 'toplines').mkdir(parents=True, exist_ok=True)
    config.CONTRACTS_FOLDER.mkdir(parents=True, exist_ok=True)
    config.IMAGES_FOLDER.mkdir(parents=True, exist_ok=True)
    (config.IMAGES_FOLDER / 'tracks').mkdir(parents=True, exist_ok=True)
    config.MIXMASTER_UPLOADS_FOLDER.mkdir(parents=True, exist_ok=True)
    config.MIXMASTER_PROCESSED_FOLDER.mkdir(parents=True, exist_ok=True)
    config.MIXMASTER_PREVIEWS_FOLDER.mkdir(parents=True, exist_ok=True)
    config.MIXMASTER_SAMPLES_FOLDER.mkdir(parents=True, exist_ok=True)

    # ============================================
    # INITIALISER LES EXTENSIONS
    # ============================================

    from extensions import init_extensions, init_scheduler, db, login_manager
    init_extensions(app)

    # Démarrer APScheduler uniquement dans le processus principal
    if is_main_process:
        init_scheduler(app)

    # ============================================
    # INITIALISER LE LOGGING PROFESSIONNEL
    # ============================================

    from utils.logger_config import setup_logging
    setup_logging(app)

    if is_main_process:
        app.logger.info("=" * 60)
        app.logger.info("Application LaProd demarree")
        app.logger.info(f"Environnement: {os.environ.get('FLASK_ENV', 'development')}")
        app.logger.info(f"Debug: {app.debug}")
        app.logger.info("=" * 60)

    # ============================================
    # NOUVEAU - COMMANDES FLASK CLI
    # ============================================

    @app.cli.command()
    def init_db():
        """Créer les tables (si elles n'existent pas)"""
        from extensions import db, migrate, login_manager, mail, oauth
        from models import User, Track, Tag, Category, Topline, Purchase, Contract
        
        with app.app_context():
            db.create_all()
            app.logger.info("Tables creees (si necessaire)")
    
    @app.cli.command()
    def create_admin():
        """Créer le compte admin"""
        from extensions import db
        from models import User
        from datetime import datetime

        with app.app_context():
            admin = db.session.query(User).filter_by(username='admin').first()
            if admin:
                app.logger.info("Le compte admin existe deja")
                return

            admin_password = os.environ.get('ADMIN_PASSWORD', 'CHANGE_ME_NOW')
            admin = User(
                username='admin',
                email='admin@laprod.net',
                is_admin=True,
                signature='Admin LaProd',
                account_status='active',  # Compte actif directement
                email_verified=True,  # Email vérifié
                terms_accepted_at=datetime.now(),  # CGU acceptées
                user_type_selected=True  # Pas besoin de sélectionner un type pour admin
            )
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            app.logger.info("Compte admin cree")
    
    # ============================================
    # ENREGISTRER LES BLUEPRINTS
    # ============================================
    
    from routes import (
        auth_bp,
        main_bp,
        tracks_bp,
        admin_bp,
        payment_bp,
        contracts_bp,
        stripe_connect_bp,
        audio_bp,
        api_bp,
        toplines_bp,
        mixmaster_bp,
        favorites_bp,
        premium_bp,
        wallet_bp,
        tracks_api_bp,
        cud_tracks_api_bp,
        tags_filters_api_bp,
        auth_api_bp,
        topline_api_bp,
        topline_cud_api_bp,
        payment_track_api_bp,
        wallet_api_bp,
        cud_wallet_api_bp,
        contracts_api_bp,
        stripe_connect_api_bp,
    )

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(tracks_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(contracts_bp)
    app.register_blueprint(stripe_connect_bp)
    app.register_blueprint(audio_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(toplines_bp)
    app.register_blueprint(mixmaster_bp)
    app.register_blueprint(favorites_bp)
    app.register_blueprint(premium_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(tracks_api_bp)
    app.register_blueprint(cud_tracks_api_bp)
    app.register_blueprint(tags_filters_api_bp)
    app.register_blueprint(auth_api_bp)
    app.register_blueprint(topline_api_bp)
    app.register_blueprint(topline_cud_api_bp)
    app.register_blueprint(payment_track_api_bp)
    app.register_blueprint(wallet_api_bp)
    app.register_blueprint(cud_wallet_api_bp)
    app.register_blueprint(contracts_api_bp)
    app.register_blueprint(stripe_connect_api_bp)

    if is_main_process:
        app.logger.info("Blueprints enregistres")
    
    # ============================================
    # USER LOADER POUR FLASK-LOGIN
    # ============================================
    
    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return db.session.get(User, int(user_id))
    
    # ============================================
    # HELPERS / UTILS GLOBAUX
    # ============================================
    
    from functools import wraps
    from flask import flash, redirect, url_for
    from flask_login import current_user
    
    
    # Rendre admin_required accessible globalement
    app.jinja_env.globals.update(admin_required=admin_required)


    # ============================================
    # CONTEXT PROCESSORS
    # ============================================
    # V2 IMPLEMENTER SYSTEME DE NOTIFICATIONS / BADGES
    @app.context_processor
    def inject_dashboard_info():
        if current_user.is_authenticated:
            dashboards = []


            if current_user.is_artist:
                dashboards.append({
                    'name': 'Espace Artiste',
                    'url': url_for('payment.artist_dashboard'),
                    'icon': 'bi bi-mic',
                    # 'badge': get_artist_notifications_count()
                })

            if current_user.is_beatmaker:
                dashboards.append({
                    'name': 'Espace Beatmaker',
                    'url': url_for('payment.beatmaker_dashboard'),
                    'icon': 'bi bi-music-note-beamed',
                    # 'badge': get_beatmaker_notifications_count()
                })

            if current_user.is_mix_engineer:
                dashboards.append({
                    'name': 'Espace Mix/Master',
                    'url': url_for('mixmaster.mix_engineer_dashboard'),
                    'icon': 'bi bi-sliders',
                    # 'badge': get_mixmaster_notifications_count()
                })

            return {
                'user_dashboards': dashboards,
                'dashboard_count': len(dashboards)
            }

        # Utilisateur non connecté
        return {
            'user_dashboards': [],
            'dashboard_count': 0
        }

    @app.context_processor
    def inject_notifications_count():

        from models import Notification

        if current_user.is_authenticated:
            unread_notifications_count = (
                db.session.query(Notification).filter(Notification.recipient_user == current_user, Notification.is_read == False).count()
                )
        else:
            unread_notifications_count=0

        return dict(unread_notifications_count=unread_notifications_count)
    
    # ===========================================================
    # Category injector
    # ===========================================================
    @app.context_processor
    def inject_categories():
        """ injecte les categories dans tous les templates qui vont se servir de jinja
        pour les afficher (avec darken_color() plus bas dans les 'template_filter'"""
        from models import Category

        return {'all_categories': Category.query.all()}


            

    # ============================================
    # MIDDLEWARE - Forcer sélection du type d'utilisateur
    # ============================================

    @app.before_request
    def check_user_type_selection():
        """Force l'utilisateur à sélectionner son type après inscription"""
        from flask import request, redirect, url_for
        from flask_login import current_user

        # Routes autorisées sans sélection de type
        allowed_endpoints = [
            'auth.select_user_type',
            'auth.submit_mixmaster_sample',
            'auth.complete_profile',
            'auth.callback_google',
            'auth.logout',
            'static'
        ]

        # Si l'utilisateur est connecté mais n'a pas sélectionné son type
        if current_user.is_authenticated and not current_user.user_type_selected:
            # Si l'utilisateur n'a pas de username, rediriger vers complete_profile d'abord
            if not current_user.username:
                if request.endpoint not in ['auth.complete_profile', 'static', 'auth.logout']:
                    return redirect(url_for('auth.complete_profile'))
            # Sinon, rediriger vers select_user_type
            elif request.endpoint not in allowed_endpoints:
                return redirect(url_for('auth.select_user_type'))
            
    @app.before_request
    def make_session_permanent():
        session.permanent = True

    # ============================================
    # GESTIONNAIRES D'ERREURS HTTP
    # ============================================

    from flask import request, render_template
    from flask_wtf.csrf import CSRFError
    from utils.logger_config import log_security_event

    def _error_context():
        """Retourne (user_id, ip) pour les logs d'erreurs, sans jamais planter."""
        try:
            from flask_login import current_user as cu
            user_id = cu.id if cu.is_authenticated else None
        except Exception:
            user_id = None
        ip = request.headers.get('X-Forwarded-For', request.remote_addr)
        return user_id, ip

    # --- CSRF (400) ---
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        user_id, ip = _error_context()
        # Log détaillé conservé pour le diagnostic nginx/gunicorn
        app.logger.warning(
            f"CSRF invalide | user={user_id} | ip={ip} | "
            f"url={request.url} | methode={request.method} | "
            f"endpoint={request.endpoint} | referrer={request.referrer} | "
            f"raison={e.description} | "
            f"X-Forwarded-Proto={request.headers.get('X-Forwarded-Proto', 'ABSENT')} | "
            f"X-Forwarded-For={request.headers.get('X-Forwarded-For', 'ABSENT')} | "
            f"cookie_session={'session' in request.cookies} | "
            f"csrf_in_form={'csrf_token' in request.form}"
        )
        log_security_event('csrf_error', f"Token CSRF invalide sur {request.url}", user_id=user_id, ip=ip)
        return render_template(
            'errors.html',
            error_code=400,
            error_title="Session expirée",
            error_description=(
                "Votre session a expiré ou la requête est invalide. "
                "Cela arrive souvent si la page est restée ouverte trop longtemps."
            ),
            error_hint="Revenez sur la page précédente et soumettez à nouveau le formulaire."
        ), 400

    # --- 400 Bad Request ---
    @app.errorhandler(400)
    def handle_bad_request(e):
        user_id, ip = _error_context()
        app.logger.warning(
            f"400 Bad Request | user={user_id} | ip={ip} | "
            f"url={request.url} | detail={getattr(e, 'description', str(e))}"
        )
        return render_template(
            'errors.html',
            error_code=400,
            error_title="Requête invalide",
            error_description="La requête envoyée au serveur est mal formée ou contient des données incorrectes.",
            error_hint="Vérifiez les données soumises et réessayez."
        ), 400

    # --- 403 Forbidden ---
    @app.errorhandler(403)
    def handle_forbidden(e):
        user_id, ip = _error_context()
        app.logger.warning(
            f"403 Forbidden | user={user_id} | ip={ip} | url={request.url}"
        )
        log_security_event('access_forbidden', f"Accès interdit à {request.url}", user_id=user_id, ip=ip)
        return render_template(
            'errors.html',
            error_code=403,
            error_title="Accès refusé",
            error_description="Vous n'avez pas les permissions nécessaires pour accéder à cette ressource.",
            error_hint="Connectez-vous avec un compte ayant les droits requis, ou contactez l'administration."
        ), 403

    # --- 404 Not Found ---
    @app.errorhandler(404)
    def handle_not_found(e):
        user_id, ip = _error_context()
        app.logger.warning(
            f"404 Not Found | user={user_id} | ip={ip} | url={request.url}"
        )
        return render_template(
            'errors.html',
            error_code=404,
            error_title="Page introuvable",
            error_description="La page que vous cherchez n'existe pas ou a été supprimée.",
            error_hint="Vérifiez l'URL ou utilisez la barre de recherche pour trouver ce que vous cherchez."
        ), 404

    # --- 405 Method Not Allowed ---
    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        user_id, ip = _error_context()
        app.logger.warning(
            f"405 Method Not Allowed | user={user_id} | ip={ip} | "
            f"url={request.url} | method={request.method}"
        )
        return render_template(
            'errors.html',
            error_code=405,
            error_title="Méthode non autorisée",
            error_description="La méthode HTTP utilisée n'est pas autorisée pour cette URL.",
            error_hint=None
        ), 405

    # --- 413 Payload Too Large (fichier trop gros, capté aussi par nginx) ---
    @app.errorhandler(413)
    def handle_payload_too_large(e):
        user_id, ip = _error_context()
        app.logger.warning(
            f"413 Payload Too Large | user={user_id} | ip={ip} | url={request.url}"
        )
        return render_template(
            'errors.html',
            error_code=413,
            error_title="Fichier trop volumineux",
            error_description="Le fichier envoyé dépasse la taille maximale autorisée par le serveur.",
            error_hint="Vérifiez les limites de taille indiquées dans le formulaire d'upload."
        ), 413

    # --- 429 Too Many Requests (Flask-Limiter) ---
    @app.errorhandler(429)
    def handle_rate_limit(e):
        user_id, ip = _error_context()
        app.logger.warning(
            f"429 Too Many Requests | user={user_id} | ip={ip} | "
            f"url={request.url} | detail={getattr(e, 'description', str(e))}"
        )
        log_security_event('rate_limit_exceeded', f"Limite dépassée sur {request.url}", user_id=user_id, ip=ip)
        return render_template(
            'errors.html',
            error_code=429,
            error_title="Trop de requêtes",
            error_description="Vous avez effectué trop de requêtes en peu de temps.",
            error_hint="Attendez quelques minutes avant de réessayer."
        ), 429

    # --- 500 Internal Server Error ---
    @app.errorhandler(500)
    def handle_server_error(e):
        user_id, ip = _error_context()
        app.logger.error(
            f"500 Internal Server Error | user={user_id} | ip={ip} | url={request.url}",
            exc_info=True
        )
        try:
            return render_template(
                'errors.html',
                error_code=500,
                error_title="Erreur serveur",
                error_description="Une erreur inattendue s'est produite. Notre équipe a été notifiée.",
                error_hint=None
            ), 500
        except Exception:
            # Fallback si render_template échoue (ex : base de données hors-ligne)
            return (
                "<html><body style='font-family:sans-serif;text-align:center;padding:60px;background:#212529;color:#fff'>"
                "<h1 style='color:#dc3545;font-size:6rem;margin:0'>500</h1>"
                "<h2>Erreur serveur</h2>"
                "<p style='color:#adb5bd'>Une erreur inattendue s'est produite.</p>"
                "<a href='/' style='color:#0d6efd'>Retour à l'accueil</a>"
                "</body></html>"
            ), 500

    # ============================================
    # FILTRES JINJA2 PERSONNALISÉS
    # ============================================

    import re

    @app.template_filter('regex_match')
    def regex_match_filter(value, pattern):
        """Filtre Jinja2 pour vérifier si une valeur correspond à une regex"""
        if value is None:
            return False
        return bool(re.match(pattern, str(value)))

    @app.template_filter('regex_search')
    def regex_search_filter(value, pattern):
        """Filtre Jinja2 pour chercher une regex dans une valeur"""
        if value is None:
            return False
        return bool(re.search(pattern, str(value)))


    @app.template_filter('darken')
    def darken_color(hex_color, factor=0.15):
        """
        Assombrit une couleur hexadécimale par un facteur multiplicatif.
        factor=0.15 → très foncé (fond des tags)
        factor=0.35 → intermédiaire (hover)
        Équivalent Python de darkenColor() dans category_colors.js.
        """
        if not hex_color or not isinstance(hex_color, str):
            return '#1a1a1a'
        hex_color = hex_color.lstrip('#')
        if len(hex_color) != 6:
            return '#1a1a1a'
        try:
            r = int(int(hex_color[0:2], 16) * factor)
            g = int(int(hex_color[2:4], 16) * factor)
            b = int(int(hex_color[4:6], 16) * factor)
            return f'#{r:02x}{g:02x}{b:02x}'
        except ValueError:
            return '#1a1a1a'

    return app


# ============================================
# CRÉER L'APPLICATION
# ============================================

app = create_app()

if __name__ == '__main__':
    app.run(debug=app.config.get('DEBUG', False), port=5000)