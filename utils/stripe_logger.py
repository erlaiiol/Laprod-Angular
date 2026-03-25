"""
Logger structuré pour toutes les transactions Stripe
Audit trail complet des opérations financières
"""
import logging
from datetime import datetime
from functools import wraps
from flask import request
from flask_login import current_user

# Créer un logger dédié pour Stripe
stripe_logger = logging.getLogger('stripe_transactions')
stripe_logger.setLevel(logging.INFO)

# Handler pour fichier (stockage permanent)
from logging.handlers import RotatingFileHandler
import os

# Créer le dossier logs s'il n'existe pas
logs_folder = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
os.makedirs(logs_folder, exist_ok=True)

# Fichier de log avec rotation (10 MB max, 5 backups)
file_handler = RotatingFileHandler(
    os.path.join(logs_folder, 'stripe_transactions.log'),
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=5,
    encoding='utf-8'
)

# Format détaillé avec timestamp
formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(formatter)
stripe_logger.addHandler(file_handler)


def log_stripe_transaction(operation, resource_type, resource_id, amount=None, user_id=None, **extra_data):
    """
    Logger une transaction Stripe avec contexte complet

    Args:
        operation: Type d'opération ('payment_intent_created', 'charge_captured', 'transfer_created', etc.)
        resource_type: Type de ressource ('track', 'mixmaster_request', 'topline', etc.)
        resource_id: ID de la ressource concernée
        amount: Montant en centimes (optionnel)
        user_id: ID de l'utilisateur (optionnel, auto-détecté si possible)
        **extra_data: Données supplémentaires (stripe_id, metadata, etc.)

    Exemple:
        log_stripe_transaction(
            operation='payment_intent_created',
            resource_type='track',
            resource_id=123,
            amount=2999,  # 29.99 EUR en centimes
            stripe_payment_intent_id='pi_xxx',
            track_title='Beat Title'
        )
    """
    # Auto-détecter le user_id depuis Flask-Login si non fourni
    if user_id is None:
        try:
            if current_user.is_authenticated:
                user_id = current_user.id
        except:
            pass

    # Construire le message de log structuré
    log_parts = [
        f"operation={operation}",
        f"resource_type={resource_type}",
        f"resource_id={resource_id}"
    ]

    if amount is not None:
        amount_eur = amount / 100 if isinstance(amount, (int, float)) else amount
        log_parts.append(f"amount={amount_eur}€")

    if user_id:
        log_parts.append(f"user_id={user_id}")

    # Ajouter les données supplémentaires
    for key, value in extra_data.items():
        # Éviter les valeurs trop longues
        if isinstance(value, str) and len(value) > 100:
            value = value[:97] + '...'
        log_parts.append(f"{key}={value}")

    # Ajouter l'IP si disponible
    try:
        if request:
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
            log_parts.append(f"ip={client_ip}")
    except:
        pass

    log_message = " | ".join(log_parts)
    stripe_logger.info(log_message)


def log_stripe_payment_intent_created(payment_intent_id, amount, resource_type, resource_id, **extra):
    """Logger la création d'un Payment Intent"""
    log_stripe_transaction(
        operation='payment_intent_created',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_payment_intent_id=payment_intent_id,
        **extra
    )


def log_stripe_payment_intent_captured(payment_intent_id, amount, resource_type, resource_id, **extra):
    """Logger la capture d'un Payment Intent"""
    log_stripe_transaction(
        operation='payment_intent_captured',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_payment_intent_id=payment_intent_id,
        **extra
    )


def log_stripe_payment_intent_succeeded(payment_intent_id, amount, resource_type, resource_id, **extra):
    """Logger le succès d'un Payment Intent"""
    log_stripe_transaction(
        operation='payment_intent_succeeded',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_payment_intent_id=payment_intent_id,
        **extra
    )


def log_stripe_transfer_created(transfer_id, amount, destination_account, resource_type, resource_id, **extra):
    """Logger la création d'un Transfer"""
    log_stripe_transaction(
        operation='transfer_created',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_transfer_id=transfer_id,
        destination_account=destination_account,
        **extra
    )


def log_stripe_refund_created(refund_id, amount, payment_intent_id, resource_type, resource_id, reason=None, **extra):
    """Logger la création d'un Refund"""
    log_stripe_transaction(
        operation='refund_created',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_refund_id=refund_id,
        stripe_payment_intent_id=payment_intent_id,
        reason=reason,
        **extra
    )


def log_stripe_transfer_reversal_created(reversal_id, transfer_id, amount, resource_type, resource_id, reason=None, **extra):
    """Logger la création d'un Transfer Reversal"""
    log_stripe_transaction(
        operation='transfer_reversal_created',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_reversal_id=reversal_id,
        stripe_transfer_id=transfer_id,
        reason=reason,
        **extra
    )


def log_stripe_checkout_session_created(session_id, amount, resource_type, resource_id, **extra):
    """Logger la création d'une Checkout Session"""
    log_stripe_transaction(
        operation='checkout_session_created',
        resource_type=resource_type,
        resource_id=resource_id,
        amount=amount,
        stripe_session_id=session_id,
        **extra
    )


def log_stripe_error(operation, error_message, resource_type=None, resource_id=None, **extra):
    """Logger une erreur Stripe"""
    log_parts = [
        f"operation={operation}",
        f"status=ERROR",
        f"error={error_message}"
    ]

    if resource_type:
        log_parts.append(f"resource_type={resource_type}")
    if resource_id:
        log_parts.append(f"resource_id={resource_id}")

    # Ajouter user_id si disponible
    try:
        if current_user.is_authenticated:
            log_parts.append(f"user_id={current_user.id}")
    except:
        pass

    # Ajouter les données supplémentaires
    for key, value in extra.items():
        if isinstance(value, str) and len(value) > 100:
            value = value[:97] + '...'
        log_parts.append(f"{key}={value}")

    log_message = " | ".join(log_parts)
    stripe_logger.error(log_message)


def with_stripe_logging(operation_name, resource_type_key='resource_type', resource_id_key='resource_id'):
    """
    Décorateur pour logger automatiquement les opérations Stripe

    Usage:
        @with_stripe_logging('payment_intent_creation', resource_type_key='track', resource_id_key='track_id')
        def create_payment(track_id):
            # ... code Stripe ...
            return payment_intent

    Le décorateur loggera automatiquement les succès et erreurs.
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            resource_type = kwargs.get(resource_type_key)
            resource_id = kwargs.get(resource_id_key)

            try:
                result = f(*args, **kwargs)

                # Logger le succès
                log_stripe_transaction(
                    operation=f"{operation_name}_success",
                    resource_type=resource_type or 'unknown',
                    resource_id=resource_id or 'unknown',
                    function=f.__name__
                )

                return result

            except Exception as e:
                # Logger l'erreur
                log_stripe_error(
                    operation=f"{operation_name}_failed",
                    error_message=str(e),
                    resource_type=resource_type,
                    resource_id=resource_id,
                    function=f.__name__
                )
                raise

        return wrapper
    return decorator
