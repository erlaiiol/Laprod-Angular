"""
Gestion de Stripe Connect pour les paiements aux compositeurs.

Convention de retour :
  - Les fonctions retournent une valeur directement (string URL, dict, etc.)
  - En cas d'erreur Stripe, elles lèvent stripe._error.StripeError
    → le blueprint appelant possède son propre try/except et renvoie un 500 approprié.
"""
import stripe
import stripe._error as stripe_error
from flask import current_app
from models import db, User


def create_connect_account(user):
    """
    Crée un compte Stripe Express pour un compositeur.

    Returns:
        dict: { success: True, account_id: str, message: str }
              { success: False, error: str, message: str }  si StripeError
    """
    try:
        account = stripe.Account.create(
            type='express',
            country='FR',
            email=user.email,
            capabilities={
                'card_payments': {'requested': True},
                'transfers':     {'requested': True},
            },
            business_type='individual',
            metadata={
                'user_id':  user.id,
                'username': user.username,
            },
        )

        user.stripe_account_id     = account.id
        user.stripe_account_status = 'pending'
        db.session.commit()

        return {
            'success':    True,
            'account_id': account.id,
            'message':    'Compte Stripe Connect créé avec succès',
        }

    except stripe_error.StripeError as e:
        return {
            'success': False,
            'error':   str(e),
            'message': 'Erreur lors de la création du compte Stripe',
        }


def create_account_link(user, return_url: str, refresh_url: str) -> str:
    """
    Crée un lien d'onboarding Stripe pour l'utilisateur.

    Returns:
        str: URL d'onboarding (ex: 'https://connect.stripe.com/...')

    Raises:
        stripe._error.StripeError: si l'appel Stripe échoue
    """
    account_link = stripe.AccountLink.create(
        account=user.stripe_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type='account_onboarding',
    )
    return account_link.url


def check_account_status(account_id: str) -> dict:
    """
    Vérifie le statut d'un compte Stripe Connect via l'API.
    Ne modifie PAS la base de données — c'est la responsabilité du code appelant.

    Args:
        account_id: ID Stripe du compte (ex: 'acct_xxx')

    Returns:
        dict avec les clés :
            'onboarding_complete' (bool)
            'status'              ('active' | 'pending')
            'charges_enabled'     (bool)
            'payouts_enabled'     (bool)
            'details_submitted'   (bool)

    Raises:
        stripe._error.StripeError: si l'appel Stripe échoue
    """
    account = stripe.Account.retrieve(account_id)

    charges_enabled     = account.charges_enabled
    payouts_enabled     = account.payouts_enabled
    onboarding_complete = charges_enabled and payouts_enabled

    return {
        'onboarding_complete': onboarding_complete,
        'status':              'active' if onboarding_complete else 'pending',
        'charges_enabled':     charges_enabled,
        'payouts_enabled':     payouts_enabled,
        'details_submitted':   account.details_submitted,
    }


def create_dashboard_link(account_id: str) -> str:
    """
    Crée un lien vers le dashboard Express Stripe.

    Args:
        account_id: ID Stripe du compte (ex: 'acct_xxx')

    Returns:
        str: URL du dashboard

    Raises:
        stripe._error.StripeError: si l'appel Stripe échoue
    """
    link = stripe.Account.create_login_link(account_id)
    return link.url


def create_payment_with_transfer(track, buyer, format_type, buyer_name, contract_price=0):
    """
    Crée un Payment Intent avec transfert automatique au compositeur.

    Returns:
        dict: { success: True, client_secret, payment_intent_id, ... }
              { success: False, error: str }  si StripeError
    """
    track_prices = {
        'mp3':   track.price_mp3,
        'wav':   track.price_wav,
        'stems': track.price_stems,
    }

    track_price   = track_prices.get(format_type, track.price_mp3)
    total_amount  = track_price + contract_price

    platform_commission = current_app.config.get('PLATFORM_COMMISSION', 0.10)
    platform_fee        = round(total_amount * platform_commission, 2)
    composer_revenue    = round(total_amount - platform_fee, 2)

    composer = track.composer_user
    if not composer.can_receive_payments():
        return {
            'success': False,
            'error':   'Le compositeur n\'a pas configuré son compte de paiement',
        }

    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=int(total_amount * 100),
            currency='eur',
            application_fee_amount=int(platform_fee * 100),
            transfer_data={'destination': composer.stripe_account_id},
            metadata={
                'track_id':         track.id,
                'track_title':      track.title,
                'format':           format_type,
                'buyer_id':         buyer.id,
                'buyer_name':       buyer_name,
                'track_price':      track_price,
                'contract_price':   contract_price,
                'platform_fee':     platform_fee,
                'composer_revenue': composer_revenue,
            },
        )

        return {
            'success':           True,
            'client_secret':     payment_intent.client_secret,
            'payment_intent_id': payment_intent.id,
            'total_amount':      total_amount,
            'track_price':       track_price,
            'contract_price':    contract_price,
            'platform_fee':      platform_fee,
            'composer_revenue':  composer_revenue,
        }

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur création payment: {e}")
        return {'success': False, 'error': str(e)}


def handle_webhook_account_updated(account_id: str) -> None:
    """
    Gère le webhook account.updated de Stripe.
    Met à jour le statut du compte dans la BDD.
    """
    user = db.session.query(User).filter_by(stripe_account_id=account_id).first()
    if not user:
        return

    try:
        account = stripe.Account.retrieve(account_id)

        if account.charges_enabled and account.payouts_enabled:
            user.stripe_account_status      = 'active'
            user.stripe_onboarding_complete = True
        else:
            user.stripe_account_status      = 'pending'
            user.stripe_onboarding_complete = False

        db.session.commit()

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur webhook account.updated: {e}")


def refund_payment(payment_intent_id: str, amount=None) -> dict:
    """
    Rembourse un paiement.

    Args:
        payment_intent_id: ID du Payment Intent Stripe
        amount: Montant en euros (None = remboursement total)

    Returns:
        dict: { success: True, refund_id, status, amount }
              { success: False, error: str }
    """
    try:
        refund_params = {'payment_intent': payment_intent_id}
        if amount:
            refund_params['amount'] = int(amount * 100)

        refund = stripe.Refund.create(**refund_params)

        return {
            'success':   True,
            'refund_id': refund.id,
            'status':    refund.status,
            'amount':    refund.amount / 100,
        }

    except stripe_error.StripeError as e:
        return {'success': False, 'error': str(e)}
