"""
Gestionnaire d'erreurs centralisé pour LaProd
Gère les erreurs de manière sécurisée selon l'environnement (dev/prod)
"""
import logging
import os
from flask import flash, current_app

# Logger dédié aux erreurs applicatives
logger = logging.getLogger('laprod_errors')
logger.setLevel(logging.ERROR)

# Handler pour fichier (production)
from logging.handlers import RotatingFileHandler

logs_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(logs_folder, exist_ok=True)

file_handler = RotatingFileHandler(
    os.path.join(logs_folder, 'errors.log'),
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)

formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s in %(module)s.%(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


def handle_error(error, context="opération", user_message=None, flash_category='error'):
    """
    Gère une erreur de manière sécurisée

    Args:
        error: L'exception levée
        context: Description de l'opération (ex: "création de contrat")
        user_message: Message personnalisé pour l'utilisateur (optionnel)
        flash_category: Catégorie du flash ('error', 'warning', etc.)

    Usage:
        try:
            # Code risqué
        except Exception as e:
            handle_error(e, context="création de contrat")
    """
    # Logger l'erreur complète côté serveur (avec stacktrace)
    logger.error(
        f"Erreur lors de {context}: {str(error)}",
        exc_info=True,
        extra={'user_id': getattr(current_user, 'id', None) if 'current_user' in dir() else None}
    )

    # Déterminer si on est en mode debug
    is_debug = current_app.debug if current_app else False

    # Message pour l'utilisateur
    if is_debug:
        # En développement: afficher l'erreur technique
        flash(f"[DEV] Erreur {context}: {str(error)}", flash_category)
    else:
        # En production: message générique
        if user_message:
            flash(user_message, flash_category)
        else:
            flash(f"Une erreur est survenue lors de {context}. Notre équipe a été notifiée.", flash_category)


def handle_database_error(error, context="opération base de données"):
    """
    Gère spécifiquement les erreurs de base de données

    Usage:
        try:
            db.session.commit()
        except Exception as e:
            handle_database_error(e, context="enregistrement du contrat")
    """
    from extensions import db

    # Rollback automatique
    try:
        db.session.rollback()
    except:
        pass

    # Messages spécifiques selon le type d'erreur
    error_str = str(error).lower()

    if 'database is locked' in error_str:
        user_message = "La base de données est temporairement occupée. Veuillez réessayer."
    elif 'unique constraint' in error_str or 'unique' in error_str:
        user_message = "Cet élément existe déjà."
    elif 'foreign key' in error_str:
        user_message = "Référence invalide. Vérifiez les données liées."
    elif 'not null' in error_str:
        user_message = "Champ obligatoire manquant."
    else:
        user_message = None  # Message générique par défaut

    handle_error(error, context=context, user_message=user_message)


def handle_stripe_error(error, context="opération Stripe"):
    """
    Gère spécifiquement les erreurs Stripe

    Usage:
        import stripe
        try:
            stripe.PaymentIntent.create(...)
        except stripe.error.StripeError as e:
            handle_stripe_error(e, context="création du paiement")
    """
    import stripe

    # Messages spécifiques selon le type d'erreur Stripe
    if isinstance(error, stripe.error.CardError):
        user_message = f"Carte refusée: {error.user_message}"
    elif isinstance(error, stripe.error.InvalidRequestError):
        user_message = "Requête de paiement invalide. Contactez le support."
    elif isinstance(error, stripe.error.AuthenticationError):
        user_message = "Erreur d'authentification Stripe. Contactez le support."
    elif isinstance(error, stripe.error.APIConnectionError):
        user_message = "Impossible de contacter Stripe. Vérifiez votre connexion."
    elif isinstance(error, stripe.error.RateLimitError):
        user_message = "Trop de requêtes. Veuillez patienter quelques secondes."
    else:
        user_message = "Erreur de paiement. Veuillez réessayer ou contacter le support."

    handle_error(error, context=context, user_message=user_message)


def handle_file_error(error, context="opération fichier"):
    """
    Gère spécifiquement les erreurs de fichiers

    Usage:
        try:
            file.save(path)
        except Exception as e:
            handle_file_error(e, context="upload du fichier audio")
    """
    error_str = str(error).lower()

    if 'permission' in error_str or 'access' in error_str:
        user_message = "Erreur de permissions sur le serveur. Contactez le support."
    elif 'no space' in error_str or 'disk' in error_str:
        user_message = "Espace disque insuffisant sur le serveur. Contactez le support."
    elif 'not found' in error_str or 'no such file' in error_str:
        user_message = "Fichier introuvable."
    else:
        user_message = None

    handle_error(error, context=context, user_message=user_message)


# Contexte managers pour simplifier l'usage
from contextlib import contextmanager

@contextmanager
def safe_database_operation(context="opération base de données"):
    """
    Context manager pour les opérations base de données

    Usage:
        with safe_database_operation("création du contrat"):
            contract = Contract(...)
            db.session.add(contract)
            db.session.commit()
    """
    try:
        yield
    except Exception as e:
        handle_database_error(e, context=context)
        raise  # Re-raise pour permettre un traitement supplémentaire si nécessaire


@contextmanager
def safe_stripe_operation(context="opération Stripe"):
    """
    Context manager pour les opérations Stripe

    Usage:
        with safe_stripe_operation("création du Payment Intent"):
            payment_intent = stripe.PaymentIntent.create(...)
    """
    try:
        yield
    except Exception as e:
        handle_stripe_error(e, context=context)
        raise


@contextmanager
def safe_file_operation(context="opération fichier"):
    """
    Context manager pour les opérations fichiers

    Usage:
        with safe_file_operation("upload de l'audio"):
            file.save(path)
    """
    try:
        yield
    except Exception as e:
        handle_file_error(e, context=context)
        raise
