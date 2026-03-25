"""
Blueprint STRIPE CONNECT - Gestion des paiements compositeurs
Routes pour configurer Stripe Connect et gérer les paiements
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, current_app
from flask_login import login_required, current_user
import stripe
import stripe._error as stripe_error

from extensions import db, csrf
from models import Track, Purchase
from stripe_connect_helpers import (
    create_connect_account,
    create_account_link,
    check_account_status,
    create_payment_with_transfer,
    create_dashboard_link,
    handle_webhook_account_updated
)

# ============================================
# CRÉER LE BLUEPRINT
# ============================================

stripe_connect_bp = Blueprint('stripe_connect', __name__, url_prefix='/stripe')


# ============================================
# WEBHOOK STRIPE
# ============================================

@stripe_connect_bp.route('/webhook', methods=['POST'])
@csrf.exempt  # Les webhooks Stripe ne peuvent pas avoir de CSRF token
def webhook():
    """Webhook pour recevoir les événements Stripe"""
    
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, current_app.config['STRIPE_WEBHOOK_SECRET']
        )
    except ValueError:
        return 'Invalid payload', 400
    except stripe_error.SignatureVerificationError:
        return 'Invalid signature', 400
    
    # Gérer les événements
    if event['type'] == 'account.updated':
        # Un compte Stripe Connect a été mis à jour
        account_id = event['data']['object']['id']
        handle_webhook_account_updated(account_id)
    
    return '', 200


# ============================================
# CONFIGURATION STRIPE CONNECT
# ============================================

@stripe_connect_bp.route('/connect/setup')
@login_required
def setup():
    """Page de configuration du compte Stripe Connect"""

    # Vérifier le statut du compte
    account_status = check_account_status(current_user)

    # Si le compte est actif, créer un lien vers le dashboard
    dashboard_url = None
    if current_user.can_receive_payments():
        dashboard_url = create_dashboard_link(current_user)

    # Calculer les statistiques de vente
    sales = db.session.query(Purchase).join(Track).filter(Track.composer_id == current_user.id).all()
    total_sales = len(sales)
    total_revenue = sum(purchase.composer_revenue for purchase in sales)
    pending_revenue = 0  # À implémenter selon votre logique

    # Si le compte existe mais n'est pas complet, créer un lien d'onboarding
    onboarding_url = None
    if current_user.stripe_account_id and not current_user.stripe_onboarding_complete:
        return_url = url_for('stripe_connect.return_page', _external=True)
        refresh_url = url_for('stripe_connect.refresh', _external=True)
        onboarding_url = create_account_link(current_user, return_url, refresh_url)

    return render_template('stripe_connect_setup.html',
                            account_status=account_status,
                            dashboard_url=dashboard_url,
                            onboarding_url=onboarding_url,
                            total_sales=total_sales,
                            total_revenue=total_revenue,
                            pending_revenue=pending_revenue)


@stripe_connect_bp.route('/connect/create', methods=['POST'])
@login_required
def create():
    """Crée un compte Stripe Connect pour le compositeur"""
    
    # Vérifier si l'utilisateur a déjà un compte
    if current_user.stripe_account_id:
        flash('Vous avez déjà un compte Stripe Connect', 'warning')
        return redirect(url_for('stripe_connect.setup'))
    
    # Créer le compte
    result = create_connect_account(current_user)
    
    if not result['success']:
        flash(f"Erreur : {result['message']}", 'danger')
        return redirect(url_for('stripe_connect.setup'))
    
    # Créer le lien d'onboarding
    return_url = url_for('stripe_connect.return_page', _external=True)
    refresh_url = url_for('stripe_connect.refresh', _external=True)
    onboarding_url = create_account_link(current_user, return_url, refresh_url)
    
    if not onboarding_url:
        flash('Erreur lors de la création du lien d\'onboarding', 'danger')
        return redirect(url_for('stripe_connect.setup'))
    
    # Rediriger vers Stripe pour compléter l'onboarding
    return redirect(onboarding_url)


@stripe_connect_bp.route('/connect/return')
@login_required
def return_page():
    """Page de retour après onboarding Stripe"""
    
    # Vérifier le statut du compte
    account_status = check_account_status(current_user)
    
    if account_status['can_receive_payments']:
        flash(' Votre compte de paiement est configuré ! Vous pouvez maintenant vendre vos compositions.', 'success')
    else:
        flash(' Configuration en cours. Veuillez compléter toutes les étapes sur Stripe.', 'warning')
    
    return redirect(url_for('stripe_connect.setup'))


@stripe_connect_bp.route('/connect/refresh')
@login_required
def refresh():
    """Page de rafraîchissement si l'onboarding expire"""
    
    # Recréer un lien d'onboarding
    return_url = url_for('stripe_connect.return_page', _external=True)
    refresh_url = url_for('stripe_connect.refresh', _external=True)
    onboarding_url = create_account_link(current_user, return_url, refresh_url)
    
    if not onboarding_url:
        flash('Erreur lors de la création du lien d\'onboarding', 'danger')
        return redirect(url_for('stripe_connect.setup'))
    
    return redirect(onboarding_url)


# ============================================
# CRÉATION PAYMENT INTENT
# ============================================

@stripe_connect_bp.route('/create-payment-intent', methods=['POST'])
@login_required
def create_payment_intent():
    """Crée un Payment Intent Stripe avec transfert au compositeur"""
    
    try:
        data = request.get_json()
        track_id = data.get('track_id')
        format_type = data.get('format_type')
        buyer_name = data.get('buyer_name')
        
        track = db.get_or_404(Track, track_id)
        
        # Récupérer les données du contrat depuis la session
        contract_data = session.get('contract_data', {})
        contract_price = contract_data.get('contract_price', 0)
        
        # Créer le paiement avec transfert
        result = create_payment_with_transfer(
            track=track,
            buyer=current_user,
            format_type=format_type,
            buyer_name=buyer_name,
            contract_price=contract_price
        )
        
        if not result['success']:
            return jsonify({'error': result['error']}), 400
        
        # Sauvegarder les infos de paiement dans la session
        session['payment_data'] = {
            'payment_intent_id': result['payment_intent_id'],
            'total_amount': result['total_amount'],
            'track_price': result['track_price'],
            'contract_price': result['contract_price'],
            'platform_fee': result['platform_fee'],
            'composer_revenue': result['composer_revenue']
        }
        
        return jsonify({
            'clientSecret': result['client_secret'],
            'totalAmount': result['total_amount'],
            'platformFee': result['platform_fee'],
            'composerRevenue': result['composer_revenue']
        })
        
    except Exception as e:
        current_app.logger.error(f"Erreur création payment intent: {e}")
        return jsonify({'error': str(e)}), 500