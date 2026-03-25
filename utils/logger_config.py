"""
Configuration centralisée du logging pour LaProd
Remplace tous les print() par un système de logging professionnel
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(app):
    """
    Configure le système de logging pour l'application Flask

    Niveaux de log:
    - DEBUG: Informations détaillées pour le debugging
    - INFO: Confirmation que les choses fonctionnent comme prévu
    - WARNING: Indication que quelque chose d'inattendu s'est produit
    - ERROR: Erreur sérieuse, l'application n'a pas pu effectuer une fonction
    - CRITICAL: Erreur grave, l'application peut ne pas pouvoir continuer

    Args:
        app: Instance Flask

    Usage dans app.py:
        from utils.logger_config import setup_logging
        setup_logging(app)
    """
    # Créer le dossier logs s'il n'existe pas
    logs_folder = Path(app.root_path) / 'logs'
    logs_folder.mkdir(exist_ok=True)

    # Déterminer le niveau de log selon l'environnement
    if app.debug:
        log_level = logging.DEBUG
        console_level = logging.DEBUG
    else:
        log_level = logging.INFO
        console_level = logging.WARNING  # En prod: seulement warnings+ dans la console

    # ============================================
    # LOGGER PRINCIPAL (app)
    # ============================================

    # Éviter les handlers dupliqués (reloader Flask appelle create_app() 2 fois)
    if app.logger.handlers:
        app.logger.handlers.clear()

    app.logger.setLevel(log_level)

    # Format des logs
    detailed_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s.%(funcName)s:%(lineno)d: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    simple_formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    # ============================================
    # HANDLER 1: CONSOLE (développement)
    # ============================================
    if app.debug:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        console_handler.setFormatter(simple_formatter)
        app.logger.addHandler(console_handler)

    # ============================================
    # HANDLER 2: FICHIER GÉNÉRAL (app.log)
    # ============================================
    try:
        file_handler = RotatingFileHandler(
            logs_folder / 'app.log',
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(detailed_formatter)
        app.logger.addHandler(file_handler)
    except PermissionError:
        # Bind mount non accessible (ex: droits insuffisants sur le dossier host)
        # Fallback : logs vers stdout (capturés par `docker compose logs`)
        stdout_handler = logging.StreamHandler()
        stdout_handler.setLevel(log_level)
        stdout_handler.setFormatter(detailed_formatter)
        app.logger.addHandler(stdout_handler)
        app.logger.warning("Impossible d'écrire dans logs/app.log — fallback stdout (fix: chown 1000:1000 ./logs)")

    # ============================================
    # HANDLER 3: FICHIER ERREURS SEULEMENT (errors.log)
    # ============================================
    try:
        error_handler = RotatingFileHandler(
            logs_folder / 'errors.log',
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(detailed_formatter)
        app.logger.addHandler(error_handler)
    except PermissionError:
        pass  # Le fallback stdout ci-dessus couvre déjà les erreurs

    # ============================================
    # LOGGERS SPÉCIALISÉS
    # ============================================

    def _make_rotating_handler(path, level, formatter, fallback_to_stdout=False):
        """Crée un RotatingFileHandler, fallback StreamHandler si permission refusée."""
        try:
            h = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
        except PermissionError:
            if not fallback_to_stdout:
                return None
            h = logging.StreamHandler()
        h.setLevel(level)
        h.setFormatter(formatter)
        return h

    # Logger Stripe
    stripe_logger = logging.getLogger('stripe_transactions')
    if not stripe_logger.handlers:
        h = _make_rotating_handler(logs_folder / 'stripe_transactions.log', logging.INFO, detailed_formatter, fallback_to_stdout=True)
        if h:
            stripe_logger.addHandler(h)
        stripe_logger.setLevel(logging.INFO)

    # Logger erreurs applicatives
    error_logger = logging.getLogger('laprod_errors')
    if not error_logger.handlers:
        h = _make_rotating_handler(logs_folder / 'errors.log', logging.ERROR, detailed_formatter)
        if h:
            error_logger.addHandler(h)
        error_logger.setLevel(logging.ERROR)

    # Logger sécurité
    security_logger = logging.getLogger('security')
    if not security_logger.handlers:
        h = _make_rotating_handler(logs_folder / 'security.log', logging.WARNING, detailed_formatter, fallback_to_stdout=True)
        if h:
            security_logger.addHandler(h)
        security_logger.setLevel(logging.WARNING)

    # Logger performance
    perf_logger = logging.getLogger('performance')
    if not perf_logger.handlers:
        h = _make_rotating_handler(logs_folder / 'performance.log', logging.INFO, detailed_formatter)
        if h:
            perf_logger.addHandler(h)
        perf_logger.setLevel(logging.INFO)

    # ============================================
    # DÉSACTIVER LES LOGGERS TROP VERBEUX
    # ============================================
    logging.getLogger('werkzeug').setLevel(logging.WARNING)  # Flask dev server
    logging.getLogger('urllib3').setLevel(logging.WARNING)   # Requests HTTP

    app.logger.info("=" * 60)
    app.logger.info("Système de logging initialisé")
    app.logger.info(f"Niveau de log: {logging.getLevelName(log_level)}")
    app.logger.info(f"Dossier logs: {logs_folder}")
    app.logger.info("=" * 60)


# ============================================
# HELPERS POUR REMPLACER LES print()
# ============================================

def get_logger(name):
    """
    Récupère un logger nommé pour un module

    Usage dans un fichier:
        from utils.logger_config import get_logger
        logger = get_logger(__name__)

        # Au lieu de print()
        logger.info("Message d'info")
        logger.warning("Attention!")
        logger.error("Erreur!")
    """
    return logging.getLogger(name)


# ============================================
# DÉCORATEUR POUR LOGGER LES PERFORMANCES
# ============================================

import time
from functools import wraps

def log_performance(threshold_ms=1000):
    """
    Décorateur pour logger les fonctions lentes

    Args:
        threshold_ms: Seuil en millisecondes au-dessus duquel logger

    Usage:
        @log_performance(threshold_ms=500)
        def slow_function():
            time.sleep(1)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger('performance')
            start = time.time()

            try:
                result = f(*args, **kwargs)
                duration_ms = (time.time() - start) * 1000

                if duration_ms > threshold_ms:
                    logger.warning(
                        f"{f.__module__}.{f.__name__} took {duration_ms:.2f}ms "
                        f"(threshold: {threshold_ms}ms)"
                    )

                return result
            except Exception as e:
                duration_ms = (time.time() - start) * 1000
                logger.error(
                    f"{f.__module__}.{f.__name__} failed after {duration_ms:.2f}ms: {e}"
                )
                raise

        return wrapper
    return decorator


# ============================================
# HELPER POUR LOGGER LES ACCÈS NON AUTORISÉS
# ============================================

def log_security_event(event_type, details, user_id=None, ip=None):
    """
    Log un événement de sécurité

    Args:
        event_type: Type d'événement ('unauthorized_access', 'suspicious_activity', etc.)
        details: Description détaillée
        user_id: ID de l'utilisateur concerné (optionnel)
        ip: Adresse IP (optionnel)

    Usage:
        log_security_event(
            'unauthorized_access',
            'Tentative d\'accès à un purchase non autorisé',
            user_id=current_user.id,
            ip=request.remote_addr
        )
    """
    logger = logging.getLogger('security')

    log_parts = [f"[{event_type}]", details]
    if user_id:
        log_parts.append(f"user_id={user_id}")
    if ip:
        log_parts.append(f"ip={ip}")

    logger.warning(" | ".join(log_parts))
