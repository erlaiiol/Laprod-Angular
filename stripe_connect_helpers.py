"""
Gestion de Stripe Connect pour les paiements aux compositeurs
"""
import stripe
import stripe._error as stripe_error
from flask import current_app, url_for
from models import db, User, Purchase


def create_connect_account(user):
    """
    Crée un compte Stripe Connect pour un compositeur
    
    Args:
        user: Instance de User (compositeur)
    
    Returns:
        dict: Informations du compte créé
    """
    try:
        # Créer un compte Express (le plus simple)
        account = stripe.Account.create(
            type='express',
            country='FR',  # France
            email=user.email,
            capabilities={
                'card_payments': {'requested': True},
                'transfers': {'requested': True},
            },
            business_type='individual',
            metadata={
                'user_id': user.id,
                'username': user.username
            }
        )
        
        # Sauvegarder l'ID du compte Stripe
        user.stripe_account_id = account.id
        user.stripe_account_status = 'pending'
        db.session.commit()
        
        return {
            'success': True,
            'account_id': account.id,
            'message': 'Compte Stripe Connect créé avec succès'
        }
        
    except stripe_error.StripeError as e:
        return {
            'success': False,
            'error': str(e),
            'message': 'Erreur lors de la création du compte Stripe'
        }


def create_account_link(user, return_url, refresh_url):
    """
    Crée un lien d'onboarding pour que l'utilisateur configure son compte Stripe
    
    Args:
        user: Instance de User
        return_url: URL de retour après succès
        refresh_url: URL si l'utilisateur doit rafraîchir
    
    Returns:
        str: URL du lien d'onboarding
    """
    try:
        account_link = stripe.AccountLink.create(
            account=user.stripe_account_id,
            refresh_url=refresh_url,
            return_url=return_url,
            type='account_onboarding',
        )
        
        return account_link.url
        
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur création account link: {e}")
        return None


def check_account_status(user):
    """
    Vérifie le statut du compte Stripe Connect
    
    Args:
        user: Instance de User
    
    Returns:
        dict: Informations sur le statut du compte
    """
    if not user.stripe_account_id:
        return {
            'status': 'not_created',
            'can_receive_payments': False,
            'message': 'Aucun compte Stripe Connect'
        }
    
    try:
        account = stripe.Account.retrieve(user.stripe_account_id)
        
        # Vérifier si le compte est complètement configuré
        charges_enabled = account.charges_enabled
        payouts_enabled = account.payouts_enabled
        
        if charges_enabled and payouts_enabled:
            user.stripe_account_status = 'active'
            user.stripe_onboarding_complete = True
        else:
            user.stripe_account_status = 'pending'
            user.stripe_onboarding_complete = False
        
        db.session.commit()
        
        return {
            'status': user.stripe_account_status,
            'can_receive_payments': user.stripe_onboarding_complete,
            'charges_enabled': charges_enabled,
            'payouts_enabled': payouts_enabled,
            'details_submitted': account.details_submitted
        }
        
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur vérification compte: {e}")
        return {
            'status': 'error',
            'can_receive_payments': False,
            'error': str(e)
        }


def create_payment_with_transfer(track, buyer, format_type, buyer_name, contract_price=0):
    """
    Crée un Payment Intent avec transfert automatique au compositeur
    
    Args:
        track: Instance de Track
        buyer: Instance de User (acheteur)
        format_type: 'mp3', 'wav', ou 'stems'
        buyer_name: Nom complet de l'acheteur
        contract_price: Prix du contrat (défaut: 0)
    
    Returns:
        dict: Informations du paiement
    """
    # Calculer le prix du track selon le format
    track_prices = {
        'mp3': track.price_mp3,
        'wav': track.price_wav,
        'stems': track.price_stems
    }
    
    track_price = track_prices.get(format_type, track.price_mp3)
    total_amount = track_price + contract_price
    
    # Calculer la commission (10%)
    platform_commission = current_app.config.get('PLATFORM_COMMISSION', 0.10)
    platform_fee = round(total_amount * platform_commission, 2)
    composer_revenue = round(total_amount - platform_fee, 2)
    
    # Vérifier que le compositeur peut recevoir des paiements
    composer = track.composer_user
    if not composer.can_receive_payments():
        return {
            'success': False,
            'error': 'Le compositeur n\'a pas configuré son compte de paiement'
        }
    
    try:
        # Créer le Payment Intent avec application_fee (commission plateforme)
        payment_intent = stripe.PaymentIntent.create(
            amount=int(total_amount * 100),  # Stripe utilise les centimes
            currency='eur',
            application_fee_amount=int(platform_fee * 100),  # Commission plateforme
            transfer_data={
                'destination': composer.stripe_account_id,  # Compte du compositeur
            },
            metadata={
                'track_id': track.id,
                'track_title': track.title,
                'format': format_type,
                'buyer_id': buyer.id,
                'buyer_name': buyer_name,
                'track_price': track_price,
                'contract_price': contract_price,
                'platform_fee': platform_fee,
                'composer_revenue': composer_revenue
            }
        )
        
        return {
            'success': True,
            'client_secret': payment_intent.client_secret,
            'payment_intent_id': payment_intent.id,
            'total_amount': total_amount,
            'track_price': track_price,
            'contract_price': contract_price,
            'platform_fee': platform_fee,
            'composer_revenue': composer_revenue
        }
        
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur création payment: {e}")
        return {
            'success': False,
            'error': str(e)
        }


def create_dashboard_link(user):
    """
    Crée un lien vers le dashboard Stripe Express pour le compositeur
    
    Args:
        user: Instance de User
    
    Returns:
        str: URL du dashboard ou None
    """
    if not user.stripe_account_id:
        return None
    
    try:
        link = stripe.Account.create_login_link(user.stripe_account_id)
        return link.url
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur création dashboard link: {e}")
        return None


def handle_webhook_account_updated(account_id):
    """
    Gère le webhook account.updated de Stripe
    Met à jour le statut du compte dans la BDD
    
    Args:
        account_id: ID du compte Stripe
    """
    user = db.session.query(User).filter_by(stripe_account_id=account_id).first()
    if not user:
        return
    
    try:
        account = stripe.Account.retrieve(account_id)
        
        if account.charges_enabled and account.payouts_enabled:
            user.stripe_account_status = 'active'
            user.stripe_onboarding_complete = True
        else:
            user.stripe_account_status = 'pending'
        
        db.session.commit()
        
    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur webhook account.updated: {e}")


def refund_payment(payment_intent_id, amount=None):
    """
    Rembourse un paiement (en cas d'annulation, litige, etc.)
    
    Args:
        payment_intent_id: ID du Payment Intent
        amount: Montant à rembourser (en euros). Si None, remboursement total
    
    Returns:
        dict: Résultat du remboursement
    """
    try:
        refund_params = {
            'payment_intent': payment_intent_id,
        }
        
        if amount:
            refund_params['amount'] = int(amount * 100)
        
        refund = stripe.Refund.create(**refund_params)
        
        return {
            'success': True,
            'refund_id': refund.id,
            'status': refund.status,
            'amount': refund.amount / 100
        }
        
    except stripe_error.StripeError as e:
        return {
            'success': False,
            'error': str(e)
        }