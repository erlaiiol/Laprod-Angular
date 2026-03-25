"""
Décorateurs de validation Stripe pour sécuriser les paiements
Vérifie l'état réel des paiements auprès de Stripe (défense contre manipulation BDD)
"""
from functools import wraps
from flask import flash, redirect, url_for, abort
import stripe
import stripe._error as stripe_error


def verify_stripe_payment(
    payment_intent_attr='stripe_payment_intent_id',
    expected_status='succeeded',
    verify_amount=True,
    amount_attr='total_price',
    verify_transfer=False,
    transfer_id_attr='stripe_deposit_transfer_id',
    transfer_amount_attr='deposit_amount',
    transfer_multiplier=0.90,
    on_error_redirect='mixmaster.dashboard'
):
    """
    Décorateur pour vérifier l'état réel d'un paiement Stripe AVANT une opération critique

    Usage:
        @verify_stripe_payment(expected_status='requires_capture')
        def upload_processed(request_id, request_obj=None):
            # payment_intent_check est injecté automatiquement
            ...

    Paramètres:
        payment_intent_attr: Nom de l'attribut contenant le Payment Intent ID
        expected_status: Statut attendu ('requires_capture', 'succeeded', etc.)
        verify_amount: Vérifier que le montant correspond
        amount_attr: Attribut contenant le montant total
        verify_transfer: Vérifier aussi un transfer existant
        transfer_id_attr: Attribut contenant le Transfer ID
        transfer_amount_attr: Attribut contenant le montant du transfer
        transfer_multiplier: Multiplicateur pour le montant du transfer (ex: 0.90 = 90%)
        on_error_redirect: Route de redirection en cas d'erreur

    Injection:
        Le décorateur injecte 'payment_intent_verified' dans kwargs
        (et 'deposit_transfer_verified' si verify_transfer=True)
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Récupérer l'objet resource depuis les kwargs
            # Le décorateur @requires_ownership l'a déjà injecté
            resource = None
            resource_candidates = ['request_obj', 'purchase', 'track', 'topline']
            for candidate in resource_candidates:
                if candidate in kwargs:
                    resource = kwargs[candidate]
                    break

            if not resource:
                flash('Erreur: Ressource introuvable.', 'danger')
                return redirect(url_for(on_error_redirect))

            #  SÉCURITÉ: Vérifier que le Payment Intent existe
            payment_intent_id = getattr(resource, payment_intent_attr, None)
            if not payment_intent_id:
                flash('Informations de paiement manquantes.', 'danger')
                return redirect(url_for(on_error_redirect))

            try:
                #  SÉCURITÉ CRITIQUE: Récupérer l'état réel depuis Stripe
                payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

                # Vérifier le statut
                if payment_intent.status != expected_status:
                    flash(
                        f'Le paiement n\'est pas dans l\'état attendu '
                        f'(attendu: {expected_status}, actuel: {payment_intent.status}).',
                        'danger'
                    )
                    return redirect(url_for(on_error_redirect))

                # Vérifier le montant si demandé
                if verify_amount:
                    expected_total = getattr(resource, amount_attr, 0)
                    expected_amount_cents = int(expected_total * 100)

                    # Utiliser amount_received pour 'succeeded', amount pour les autres
                    actual_amount = (
                        payment_intent.amount_received
                        if expected_status == 'succeeded'
                        else payment_intent.amount
                    )

                    if actual_amount != expected_amount_cents:
                        flash(
                            f'Le montant ne correspond pas '
                            f'(attendu: {expected_amount_cents/100}€, reçu: {actual_amount/100}€).',
                            'danger'
                        )
                        return redirect(url_for(on_error_redirect))

                # Vérifier le transfer si demandé
                if verify_transfer:
                    transfer_id = getattr(resource, transfer_id_attr, None)
                    if not transfer_id:
                        flash('Informations de transfert manquantes.', 'danger')
                        return redirect(url_for(on_error_redirect))

                    deposit_transfer = stripe.Transfer.retrieve(transfer_id)

                    # Vérifier que le transfer n'a pas été annulé
                    if deposit_transfer.reversed:
                        flash('Le transfert initial a été annulé. Opération impossible.', 'danger')
                        return redirect(url_for(on_error_redirect))

                    # Vérifier le montant du transfer
                    transfer_base = getattr(resource, transfer_amount_attr, 0)
                    expected_transfer_cents = int(round(transfer_base * transfer_multiplier, 2) * 100)

                    if deposit_transfer.amount != expected_transfer_cents:
                        flash('Le montant du transfert ne correspond pas.', 'danger')
                        return redirect(url_for(on_error_redirect))

                    # Injecter le transfer vérifié
                    kwargs['deposit_transfer_verified'] = deposit_transfer

                #  Tout est vérifié, injecter le Payment Intent
                kwargs['payment_intent_verified'] = payment_intent

            except stripe_error.StripeError as e:
                flash(f'Erreur de vérification du paiement auprès de Stripe: {str(e)}', 'danger')
                return redirect(url_for(on_error_redirect))

            # Appeler la fonction avec le Payment Intent vérifié
            return f(*args, **kwargs)

        return wrapper
    return decorator


def verify_stripe_payment_for_download(
    payment_intent_attr='stripe_payment_intent_id',
    amount_attr='total_price',
    verify_deposit_transfer=True,
    on_error_redirect='mixmaster.dashboard'
):
    """
    Décorateur spécialisé pour les téléchargements MixMaster (étape finale 70%)

    Vérifie:
    - Payment Intent status = 'succeeded'
    - Montant capturé correct
    - Transfer initial de 30% effectué et non annulé

    Usage:
        @verify_stripe_payment_for_download()
        def download_processed(request_id, request_obj=None, payment_intent_verified=None):
            # payment_intent_verified contient le PI vérifié
            # deposit_transfer_verified contient le transfer vérifié
            charge_id = payment_intent_verified.latest_charge
            ...
    """
    return verify_stripe_payment(
        payment_intent_attr=payment_intent_attr,
        expected_status='succeeded',
        verify_amount=True,
        amount_attr=amount_attr,
        verify_transfer=verify_deposit_transfer,
        transfer_id_attr='stripe_deposit_transfer_id',
        transfer_amount_attr='deposit_amount',
        transfer_multiplier=0.90,
        on_error_redirect=on_error_redirect
    )


def verify_stripe_payment_for_capture(
    payment_intent_attr='stripe_payment_intent_id',
    amount_attr='total_price',
    on_error_redirect='mixmaster.dashboard'
):
    """
    Décorateur spécialisé pour la capture initiale MixMaster (étape 30%)

    Vérifie:
    - Payment Intent status = 'requires_capture'
    - Montant correct

    Usage:
        @verify_stripe_payment_for_capture()
        def upload_processed(request_id, request_obj=None, payment_intent_verified=None):
            # payment_intent_verified.status == 'requires_capture' garanti
            capture = stripe.PaymentIntent.capture(request_obj.stripe_payment_intent_id)
            ...
    """
    return verify_stripe_payment(
        payment_intent_attr=payment_intent_attr,
        expected_status='requires_capture',
        verify_amount=True,
        amount_attr=amount_attr,
        verify_transfer=False,
        on_error_redirect=on_error_redirect
    )


def verify_stripe_payment_for_refund(
    payment_intent_attr='stripe_payment_intent_id',
    amount_attr='total_price',
    on_error_redirect='mixmaster.dashboard'
):
    """
    Décorateur spécialisé pour les remboursements MixMaster

    Vérifie:
    - Payment Intent status = 'succeeded'
    - Montant capturé correct
    - Transfer initial effectué et non annulé

    Usage:
        @verify_stripe_payment_for_refund()
        def reject_delivery(request_id, request_obj=None, payment_intent_verified=None):
            # Remboursement sécurisé
            refund = stripe.Refund.create(...)
            ...
    """
    return verify_stripe_payment(
        payment_intent_attr=payment_intent_attr,
        expected_status='succeeded',
        verify_amount=True,
        amount_attr=amount_attr,
        verify_transfer=True,
        transfer_id_attr='stripe_deposit_transfer_id',
        transfer_amount_attr='deposit_amount',
        transfer_multiplier=0.90,
        on_error_redirect=on_error_redirect
    )
