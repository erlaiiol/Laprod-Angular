"""
Blueprint premium_api — LaProd+
Gestion des abonnements Amateur / Pro via Stripe Checkout (JWT).
"""

from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from datetime import datetime, timedelta
from pathlib import Path
from werkzeug.utils import secure_filename
import stripe
import stripe._error as stripe_error

from extensions import db, csrf
from utils.money import to_money, to_cents
from utils import plans
from models import User
from serializers import ok, err, capabilities_dict
from utils.auth_helpers import require_user
from utils.crud_helpers import handle_route_exceptions, commit_or_rollback, EntityForbidden
from utils.notification_service import create_notification
from utils.stripe_logger import (
    log_stripe_checkout_session_created,
    log_stripe_error,
    log_stripe_transaction,
)
import config

premium_api_bp = Blueprint('premium_api', __name__, url_prefix='/api/premium')

# Les paliers, leurs prix et leurs libellés viennent tous de utils/plans.py :
# une grille tarifaire recopiée ici finirait par diverger de celle affichée au
# client, et on encaisserait un montant différent de celui annoncé.
_VALID_PLANS = plans.PAID_PLANS


def _plan_price(plan: str):
    return plans.price_of(plan)


def _plan_label(plan: str) -> str:
    return plans.label_of(plan)


def _premium_status(user: User) -> dict:
    # On expose les CAPACITÉS, pas seulement le nom du palier : le front ne doit
    # jamais réimplémenter « semi_pro ou plus » de son côté — cette règle vit au
    # même endroit pour les deux, sinon l'UI et l'API finissent par diverger.
    return {
        'subscription_plan':  user.plan,
        'plan_label':         plans.label_of(user.plan),
        'is_premium_active':  user.is_premium_active,
        'is_pro':             user.is_pro,
        'premium_since':      user.premium_since.isoformat() if user.premium_since else None,
        'premium_expires_at': user.premium_expires_at.isoformat() if user.premium_expires_at else None,
        'upload_track_tokens': user.upload_track_tokens,
        'topline_tokens':      user.topline_tokens,
        'capabilities': capabilities_dict(user),
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/premium/status
# ─────────────────────────────────────────────────────────────────────────────

@premium_api_bp.route('/status', methods=['GET'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
def status(current_user):
    return ok(_premium_status(current_user))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/premium/plans — grille tarifaire publique
# ─────────────────────────────────────────────────────────────────────────────

@premium_api_bp.route('/plans', methods=['GET'])
def plan_catalog():
    """Grille des paliers. PUBLIQUE : un visiteur non connecté doit pouvoir voir
    ce que coûte l'abonnement avant de créer un compte — cacher ses prix derrière
    un mur d'inscription est le contraire d'une relation de confiance."""
    return ok({
        'plans':      plans.public_catalog(),
        'comparison': plans.comparison_matrix(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/premium/subscribe  {plan: 'premium'|'semi_pro'|'pro_structure'}
# ─────────────────────────────────────────────────────────────────────────────

@premium_api_bp.route('/subscribe', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
def subscribe(current_user):
    data = request.get_json(silent=True) or {}
    raw  = (data.get('plan') or '').strip().lower()

    # Les anciens identifiants ('amateur', 'pro') sont acceptés et normalisés :
    # l'app mobile Capacitor déjà installée chez les utilisateurs les envoie encore,
    # et une version publiée ne se met pas à jour d'un claquement de doigts. Refuser
    # ces valeurs casserait l'abonnement pour tout le parc mobile existant.
    plan = plans.normalize(raw) if raw in set(plans.PLAN_ORDER) | set(plans.LEGACY_ALIASES) else None
    if plan not in _VALID_PLANS:
        raise EntityForbidden(
            f"Plan invalide. Valeurs acceptées : {', '.join(_VALID_PLANS)}."
        )

    price        = _plan_price(plan)
    label        = _plan_label(plan)
    is_renewal   = current_user.is_premium_active
    frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:4200')

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': to_cents(price),
                    'product_data': {
                        'name': f"LaProd+ {label}" + (' — Renouvellement' if is_renewal else ''),
                        'description': f"{config.PREMIUM_DURATION_DAYS} jours d'accès LaProd+ {label}",
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=(
                f"{frontend_url}/premium"
                f"?payment=success&plan={plan}&session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{frontend_url}/premium",
            metadata={
                'user_id':              str(current_user.id),
                'plan':                 plan,
                'premium_duration_days': str(config.PREMIUM_DURATION_DAYS),
                'is_renewal':           str(is_renewal),
                'type':                 'premium_subscription',
            },
            customer_email=current_user.email,
        )

        log_stripe_checkout_session_created(
            session_id=checkout_session.id,
            amount=to_cents(price),
            resource_type='premium',
            resource_id=current_user.id,
            buyer_id=current_user.id,
        )

        return ok({'checkout_url': checkout_session.url})

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe premium subscribe: {e}", exc_info=True)
        log_stripe_error(
            operation='premium_checkout_creation',
            error_message=str(e),
            resource_type='premium',
            resource_id=current_user.id,
        )
        return err('Erreur lors de la création de la session de paiement. Veuillez réessayer.', status=503)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/premium/activate  {session_id: '...'}
# ─────────────────────────────────────────────────────────────────────────────

@premium_api_bp.route('/activate', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def activate(current_user):
    data       = request.get_json(silent=True) or {}
    session_id = data.get('session_id', '').strip()

    if not session_id:
        raise EntityForbidden("session_id manquant.")

    try:
        stripe_session = stripe.checkout.Session.retrieve(session_id)
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe premium activate: {e}", exc_info=True)
        log_stripe_error(
            operation='premium_activate_retrieve',
            error_message=str(e),
            resource_type='premium',
            session_id=session_id,
        )
        return err('Impossible de vérifier le paiement. Veuillez contacter le support.', status=503)

    if stripe_session.payment_status != 'paid':
        raise EntityForbidden("Le paiement n'a pas été complété.")

    meta = stripe_session.metadata or {}
    if meta.get('type') != 'premium_subscription':
        raise EntityForbidden("Session de paiement invalide.")

    if int(meta.get('user_id', -1)) != current_user.id:
        raise EntityForbidden("Session de paiement invalide.")

    # Anti-doublon : < 60 s depuis premium_since
    if (current_user.is_premium_active
            and current_user.premium_since
            and (datetime.now() - current_user.premium_since).total_seconds() < 60):
        return ok(_premium_status(current_user), message='Abonnement déjà actif.')

    # Le palier vient des métadonnées de la session Stripe, écrites au moment du
    # checkout — donc potentiellement AVANT le renommage des paliers. On normalise
    # ('pro' → pro_structure) au lieu de retomber sur le palier d'entrée : sans ça,
    # un utilisateur ayant payé 49,99 € via une session ouverte avant le déploiement
    # se verrait accorder le palier le moins cher. On n'accorde jamais moins que ce
    # qui a été payé.
    plan = plans.normalize(meta.get('plan', ''))
    if plan not in _VALID_PLANS:
        current_app.logger.error(
            f"Palier illisible dans la session Stripe {session_id} "
            f"(meta.plan={meta.get('plan')!r}) — activation refusée."
        )
        raise EntityForbidden(
            "Impossible de déterminer l'abonnement payé. Contactez le support."
        )
    duration_days = int(meta.get('premium_duration_days', config.PREMIUM_DURATION_DAYS))
    is_renewal    = meta.get('is_renewal') == 'True'
    now           = datetime.now()
    payment_intent_id = stripe_session.payment_intent

    price_paid = _plan_price(plan)

    if is_renewal and current_user.is_premium_active and current_user.premium_expires_at:
        current_user.premium_expires_at = current_user.premium_expires_at + timedelta(days=duration_days)
    else:
        current_user.premium_since      = now
        current_user.premium_expires_at = now + timedelta(days=duration_days)

    current_user.subscription_plan = plan
    current_user.premium_source    = 'stripe'
    current_user.premium_price_paid = price_paid
    current_user.apply_premium_tokens()
    db.session.commit()

    log_stripe_transaction(
        operation='premium_activated',
        resource_type='premium',
        resource_id=current_user.id,
        amount=to_cents(_plan_price(plan)),
        stripe_payment_intent_id=payment_intent_id,
    )

    label = _plan_label(plan)
    if is_renewal:
        create_notification(
            user_id=current_user.id,
            notif_type='system',
            title=f'LaProd+ {label} renouvelé',
            message=(
                f'Votre abonnement LaProd+ {label} a été prolongé de {duration_days} jours. '
                f'Nouvelle expiration : {current_user.premium_expires_at.strftime("%d/%m/%Y")}.'
            ),
            link='/premium',
        )
    else:
        create_notification(
            user_id=current_user.id,
            notif_type='system',
            title=f'Bienvenue en LaProd+ {label} !',
            message=f'Votre abonnement LaProd+ {label} est actif pour {duration_days} jours.',
            link='/premium',
        )

    return ok(_premium_status(current_user), message=f'Abonnement LaProd+ {label} activé.')


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/premium/update-mix-previews  (Pro uniquement)
# Permet aux ingénieurs Pro de mettre à jour leurs previews sans validation admin.
# ─────────────────────────────────────────────────────────────────────────────

@premium_api_bp.route('/update-mix-previews', methods=['POST'])
@jwt_required()
@csrf.exempt
@handle_route_exceptions
@require_user
@commit_or_rollback
def update_mix_previews(current_user):
    """Pro + is_mixmaster_engineer → mise à jour des previews sans validation admin."""
    if not current_user.is_pro:
        raise EntityForbidden("Cette fonctionnalité est réservée aux abonnés LaProd+ Pro.")
    if not current_user.is_mixmaster_engineer:
        raise EntityForbidden("Certification Mix Engineer requise.")

    raw_file  = request.files.get('sample_raw')
    proc_file = request.files.get('sample_processed')

    if not raw_file and not proc_file:
        raise EntityForbidden("Sélectionnez au moins un fichier audio.")

    allowed_ext = {'wav', 'mp3'}
    MAX_SIZE    = 50 * 1024 * 1024

    def _valid_file(f):
        if not f or f.filename == '':
            return False
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in allowed_ext:
            return False
        f.seek(0, 2); size = f.tell(); f.seek(0)
        return size <= MAX_SIZE

    if raw_file and not _valid_file(raw_file):
        raise EntityForbidden("Fichier brut invalide (.wav/.mp3, max 50 MB).")
    if proc_file and not _valid_file(proc_file):
        raise EntityForbidden("Fichier traité invalide (.wav/.mp3, max 50 MB).")

    try:
        folder = config.MIXMASTER_SAMPLES_FOLDER
        folder.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')

        if raw_file:
            raw_name = f"{current_user.id}_{ts}_raw_{secure_filename(raw_file.filename)}"
            raw_file.save(folder / raw_name)
            current_user.mixmaster_sample_raw = \
                Path('db_assets', 'mixmaster', 'samples', raw_name).as_posix()

        if proc_file:
            proc_name = f"{current_user.id}_{ts}_processed_{secure_filename(proc_file.filename)}"
            proc_file.save(folder / proc_name)
            current_user.mixmaster_sample_processed = \
                Path('db_assets', 'mixmaster', 'samples', proc_name).as_posix()

    except Exception as e:
        current_app.logger.error(f'update_mix_previews error: {e}', exc_info=True)
        raise

    db.session.commit()
    return ok({
        'mixmaster_sample_raw':       current_user.mixmaster_sample_raw,
        'mixmaster_sample_processed': current_user.mixmaster_sample_processed,
    }, message='Previews mis à jour avec succès.')
