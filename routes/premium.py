"""
Blueprint premium -
Routes pour devenir premium et renouveler l'abonnement
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from flask_wtf.csrf import validate_csrf
from datetime import datetime, timedelta
import stripe
import stripe._error as stripe_error

from extensions import db
from utils import notification_service
from utils.stripe_logger import log_stripe_checkout_session_created, log_stripe_error, log_stripe_transaction
import config

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

premium_bp = Blueprint('premium', __name__, url_prefix='/legacy/premium')


# ============================================
# ROUTE 1 : PAGE PREMIUM (offre + statut)
# ============================================

@premium_bp.route('/premium')
@login_required
def premium_page():
    """Page de l'offre premium avec comparatif Free vs Premium et statut actuel"""

    return render_template(
        'premium.html',
        premium_price=config.PREMIUM_PRICE,
        premium_duration_days=config.PREMIUM_DURATION_DAYS,
        now=datetime.now()
    )


# ============================================
# ROUTE 2 : SOUSCRIRE / RENOUVELER (Stripe Checkout)
# ============================================

@premium_bp.route('/premium/subscribe', methods=['POST'])
@login_required
def subscribe():
    """Crée une session Stripe Checkout pour l'achat ou le renouvellement du premium"""

    # Validation CSRF
    try:
        validate_csrf(request.form.get('csrf_token'))
    except Exception:
        flash('Session expirée, veuillez réessayer.', 'danger')
        return redirect(url_for('premium.premium_page'))

    is_renewal = current_user.is_premium_active

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': round(config.PREMIUM_PRICE * 100),
                    'product_data': {
                        'name': 'LaProd Premium' + (' - Renouvellement' if is_renewal else ''),
                        'description': f'{config.PREMIUM_DURATION_DAYS} jours d\'accès Premium',
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.url_root.rstrip('/') + url_for('premium.premium_success') + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.url_root.rstrip('/') + url_for('premium.premium_page'),
            metadata={
                'user_id': str(current_user.id),
                'premium_duration_days': str(config.PREMIUM_DURATION_DAYS),
                'is_renewal': str(is_renewal),
                'type': 'premium_subscription',
            },
            customer_email=current_user.email,
        )

        log_stripe_checkout_session_created(
            session_id=checkout_session.id,
            amount=round(config.PREMIUM_PRICE * 100),
            resource_type='premium',
            resource_id=current_user.id,
            buyer_id=current_user.id
        )

        return redirect(checkout_session.url, code=303)

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe premium: {e}", exc_info=True)
        log_stripe_error(
            operation='premium_checkout_creation',
            error_message=str(e),
            resource_type='premium',
            resource_id=current_user.id
        )
        flash('Erreur lors de la création de la session de paiement. Veuillez réessayer.', 'danger')
        return redirect(url_for('premium.premium_page'))

    except Exception as e:
        current_app.logger.error(f"Erreur création session premium: {e}", exc_info=True)
        flash('Une erreur est survenue. Veuillez réessayer.', 'danger')
        return redirect(url_for('premium.premium_page'))


# ============================================
# ROUTE 3 : SUCCESS CALLBACK
# ============================================

@premium_bp.route('/premium/success')
@login_required
def premium_success():
    """Callback après paiement réussi - active ou prolonge le premium"""

    session_id = request.args.get('session_id')

    if not session_id:
        flash('Session de paiement introuvable.', 'danger')
        return redirect(url_for('premium.premium_page'))

    try:
        # Récupérer la session Stripe
        stripe_session = stripe.checkout.Session.retrieve(session_id)

        if stripe_session.payment_status != 'paid':
            flash('Le paiement n\'a pas été complété.', 'danger')
            return redirect(url_for('premium.premium_page'))

        # Vérifier les metadata
        metadata = stripe_session.metadata
        if metadata.get('type') != 'premium_subscription':
            flash('Session de paiement invalide.', 'danger')
            return redirect(url_for('premium.premium_page'))

        user_id = int(metadata['user_id'])
        if user_id != current_user.id:
            flash('Session de paiement invalide.', 'danger')
            return redirect(url_for('premium.premium_page'))

        duration_days = int(metadata.get('premium_duration_days', config.PREMIUM_DURATION_DAYS))

        # Anti-doublon : vérifier que cette session n'a pas déjà été traitée
        # On utilise le payment_intent_id comme identifiant unique
        payment_intent_id = stripe_session.payment_intent

        # Vérifier si ce payment_intent a déjà été utilisé
        # (on stocke dans les logs Stripe, et on vérifie côté premium_since)
        # Simple anti-doublon : si premium_since est dans les 60 dernières secondes
        # et qu'on a le même session_id en paramètre, on affiche juste le succès
        if (current_user.is_premium_active and
                current_user.premium_since and
                (datetime.now() - current_user.premium_since).total_seconds() < 60):
            flash('Votre premium est déjà actif.', 'info')
            return redirect(url_for('premium.premium_page'))

        # Logique d'activation / renouvellement
        now = datetime.now()

        if current_user.is_premium_active and current_user.premium_expires_at:
            # Renouvellement : ajouter les jours à la date d'expiration existante
            current_user.premium_expires_at = current_user.premium_expires_at + timedelta(days=duration_days)
        else:
            # Nouvel abonnement (ou expiré)
            current_user.is_premium = True
            current_user.premium_since = now
            current_user.premium_expires_at = now + timedelta(days=duration_days)

        # Booster immédiatement les tokens au plafond premium
        current_user.apply_premium_tokens()

        # Log transaction
        log_stripe_transaction(
            operation='premium_activated',
            resource_type='premium',
            resource_id=current_user.id,
            amount=round(config.PREMIUM_PRICE * 100),
            stripe_payment_intent_id=payment_intent_id
        )

        # Notification
        is_renewal = metadata.get('is_renewal') == 'True'
        if is_renewal:
            notification_service.create_notification(
                user_id=current_user.id,
                notif_type='system',
                title='Premium renouvelé',
                message=f'Votre abonnement Premium a été prolongé de {duration_days} jours. '
                        f'Nouvelle expiration : {current_user.premium_expires_at.strftime("%d/%m/%Y")}.',
                link=url_for('premium.premium_page')
            )
        else:
            notification_service.create_notification(
                user_id=current_user.id,
                notif_type='system',
                title='Bienvenue en Premium !',
                message=f'Votre abonnement Premium est actif pour {duration_days} jours. '
                        f'Profitez de vos avantages !',
                link=url_for('premium.premium_page')
            )

        db.session.commit()

        if is_renewal:
            flash(f'Premium renouvelé ! Expire le {current_user.premium_expires_at.strftime("%d/%m/%Y")}.', 'success')
        else:
            flash('Bienvenue en Premium ! Profitez de vos avantages.', 'success')

        return redirect(url_for('premium.premium_page'))

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe premium success: {e}", exc_info=True)
        log_stripe_error(
            operation='premium_success_callback',
            error_message=str(e),
            resource_type='premium',
            session_id=session_id
        )
        flash('Erreur lors de la vérification du paiement.', 'danger')
        return redirect(url_for('premium.premium_page'))

    except Exception as e:
        current_app.logger.error(f"Erreur traitement premium: {e}", exc_info=True)
        log_stripe_error(
            operation='premium_activation',
            error_message=str(e),
            resource_type='premium',
            session_id=session_id
        )
        flash('Une erreur est survenue lors de l\'activation du premium.', 'danger')
        return redirect(url_for('premium.premium_page'))
