"""
Blueprint PAYMENT TRACK API — JSON API pour l'achat de tracks (frontend Angular)

POST /api/track-payment/track/<track_id>/<format_type>/checkout
  → Valide le prix côté serveur, crée une session Stripe Checkout, retourne l'URL.

POST /api/track-payment/verify
  → Appelé par Angular après redirection Stripe. Crée Purchase, wallet, contrat PDF, notifications.
"""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
import stripe
import stripe._error as stripe_error
import os
from datetime import datetime

from extensions import db, csrf
from models import Track, User, Purchase
from serializers import ok, err
from utils.auth_helpers import require_user

_TWO_PLACES = Decimal('0.01')
from utils.payment_validator import TrackPriceCalculator
from utils.wallet_service import credit_wallet_for_beat_sale
from utils.notification_service import notify_purchase_confirmed, notify_sale_completed
from utils.email_service import send_purchase_confirmation_email, send_sale_notification_email

payment_track_api_bp = Blueprint('payment_track_api', __name__, url_prefix='/api/track-payment')


# ── POST /api/track-payment/track/<id>/<format>/checkout ──────────────────────

@payment_track_api_bp.route('/track/<int:track_id>/<format_type>/checkout', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def create_checkout(track_id, format_type, current_user):
    """
    Crée une session Stripe Checkout pour l'achat d'un track.

    Corps JSON :
      {
        "is_lifetime":              bool,
        "duration_years":           int  (3 | 5 | 10),
        "territory":                str  ("France" | "Europe" | "Monde entier"),
        "mechanical_reproduction":  bool,
        "public_show":              bool,
        "arrangement":              bool,
        "total_price":              float  (prix calculé côté client — validé serveur),
        "buyer_address":            str  (optionnel),
        "buyer_email":              str  (optionnel)
      }

    Retourne :
      { success: true, data: { checkout_url: "...", total: float } }
    """
    if format_type not in ('mp3', 'wav', 'stems'):
        return err('Format invalide.', code='INVALID_FORMAT', status=400)

    track = db.session.get(Track, track_id)
    if not track:
        return err('Track introuvable.', code='NOT_FOUND', status=404)
    if not track.is_approved:
        return err('Cette track n\'est pas disponible.', code='TRACK_UNAVAILABLE', status=403)
    if track.is_exclusive_sold:
        return err(
            'Ce track a été vendu en exclusivité et n\'est plus disponible.',
            code='TRACK_EXCLUSIVE_SOLD', status=410,
        )
    if current_user.id == track.composer_id:
        return err(
            'Vous ne pouvez pas acheter votre propre composition.',
            code='OWN_TRACK', status=403,
        )

    data = request.get_json() or {}

    options = {
        'is_exclusive':            bool(data.get('is_exclusive', False)),
        'is_lifetime':             bool(data.get('is_lifetime', False)),
        'duration_years':          int(data.get('duration_years', 3)),
        'territory':               data.get('territory', 'Monde entier'),
        'mechanical_reproduction': bool(data.get('mechanical_reproduction', False)),
        'public_show':             bool(data.get('public_show', False)),
        'arrangement':             bool(data.get('arrangement', False)),
    }

    # ── Validation du prix côté serveur ──────────────────────────────────────
    calculator = TrackPriceCalculator()
    try:
        _base, _opts, server_total = calculator.calculate_total(
            resource=track, options=options, format_type=format_type
        )
    except ValueError as e:
        return err(str(e), code='PRICE_CALC_ERROR', status=400)

    client_total = data.get('total_price')
    if client_total is not None and abs(server_total - Decimal(str(client_total))) > Decimal('0.01'):
        current_app.logger.error(
            f"Prix manipulé ! Client: {client_total}€, Serveur: {server_total}€, "
            f"User: {current_user.id}, Track: {track_id}"
        )
        return err('Prix invalide. Veuillez rafraîchir la page.', code='PRICE_TAMPERED', status=403)

    # ── Créer la session Stripe Checkout ─────────────────────────────────────
    try:
        duration_years = str(data.get('duration_years', 3))
        is_lifetime    = options['is_lifetime']
        buyer_email    = data.get('buyer_email') or current_user.email

        metadata = {
            'track_id':               str(track_id),
            'track_title':            track.title,
            'composer_id':            str(track.composer_id),
            'composer_username':      track.composer_user.username,
            'buyer_id':               str(current_user.id),
            'buyer_username':         current_user.username,
            'format_type':            format_type,
            'is_exclusive':           str(options['is_exclusive']),
            'duration_years':         duration_years,
            'is_lifetime':            str(is_lifetime),
            'territory':              options['territory'],
            'streaming':              'true',
            'mechanical_reproduction': str(options['mechanical_reproduction']),
            'public_show':            str(options['public_show']),
            'arrangement':            str(options['arrangement']),
            'buyer_address':          data.get('buyer_address', ''),
            'buyer_email':            buyer_email,
            'track_price':            str(server_total),
        }

        frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:4200')

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': int(server_total * 100),
                    'product_data': {
                        'name': f"{track.title} — {format_type.upper()}",
                        'description': f"Licence d'exploitation par {track.composer_user.username}",
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{frontend_url}/payment/track/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/contract/{track_id}/{format_type}",
            metadata=metadata,
            payment_intent_data={'metadata': metadata},
            customer_email=buyer_email,
        )

        current_app.logger.info(
            f"Checkout Stripe créé | track #{track_id} {format_type} | "
            f"total {server_total}€ | user #{current_user.id}"
        )

        return ok(
            data={'checkout_url': checkout_session.url, 'total': server_total},
            message='Session Stripe créée.',
        )

    except stripe.StripeError as e:
        current_app.logger.error(f"Erreur Stripe checkout track #{track_id}: {e}", exc_info=True)
        return err(f"Erreur Stripe : {str(e)}", code='STRIPE_ERROR', status=500)
    except Exception as e:
        current_app.logger.error(f"Erreur checkout track #{track_id}: {e}", exc_info=True)
        return err(str(e), code='SERVER_ERROR', status=500)


# ── POST /api/track-payment/verify ───────────────────────────────────────────

@payment_track_api_bp.route('/verify', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def verify_payment(current_user):
    """
    Vérifie la session Stripe Checkout et crée le Purchase.
    Body JSON : { session_id: string }
    """
    data = request.get_json() or {}
    session_id = data.get('session_id', '').strip()

    if not session_id:
        return err('session_id requis.', code='MISSING_SESSION', status=400)

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        payment_intent_id = checkout_session.payment_intent

        if not payment_intent_id:
            return err('Aucun Payment Intent trouvé.', code='NO_PAYMENT_INTENT', status=400)

        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

        if payment_intent.status != 'succeeded':
            return err(
                f'Paiement non confirmé (statut : {payment_intent.status}).',
                level='warning', code='PAYMENT_NOT_SUCCEEDED', status=400,
            )

        # Les métadonnées sont sur la Session (pas auto-copiées vers le PaymentIntent)
        meta = checkout_session.metadata

        # Vérification de sécurité : l'acheteur JWT correspond à la metadata
        if int(meta.get('buyer_id', -1)) != current_user.id:
            return err('Cette session ne vous appartient pas.', code='UNAUTHORIZED', status=403)

        # Idempotence : Purchase déjà créé ?
        existing = db.session.query(Purchase).filter_by(
            stripe_payment_intent_id=payment_intent_id
        ).first()
        if existing:
            return ok({'purchase_id': existing.id}, message='Achat déjà enregistré.', level='info')

        track_id = int(meta.get('track_id'))
        track = db.session.get(Track, track_id)
        if not track:
            return err('Track introuvable.', code='TRACK_NOT_FOUND', status=404)

        total_price      = Decimal(str(meta.get('track_price', payment_intent.amount / 100)))
        platform_fee     = (total_price * Decimal('0.10')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        composer_revenue = (total_price - platform_fee).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        purchase = Purchase(
            track_id=track_id,
            buyer_id=current_user.id,
            format_purchased=meta.get('format_type', 'mp3'),
            price_paid=total_price,
            buyer_name=current_user.username,
            contract_price=0,
            track_price=total_price,
            platform_fee=platform_fee,
            composer_revenue=composer_revenue,
            stripe_payment_intent_id=payment_intent_id,
        )
        db.session.add(purchase)
        db.session.flush()  # obtenir purchase.id

        # ── Marquer le track comme vendu en exclusivité ──────────────────────
        if meta.get('is_exclusive') == 'True':
            track.is_exclusive_sold  = True
            track.exclusive_sold_at  = datetime.now()
            track.exclusive_buyer_id = purchase.buyer_id
            try:
                from utils.notification_service import notify_exclusive_sold
                from utils.email_service import send_exclusive_sold_email
                notify_exclusive_sold(track, purchase)
                send_exclusive_sold_email(track, purchase)
            except Exception as exc_err:
                current_app.logger.error(f"Erreur notify/email exclusivité track #{track_id}: {exc_err}")

        # ── Crédit wallet compositeur ────────────────────────────────────────
        credit_wallet_for_beat_sale(purchase)

        # ── Génération du contrat PDF ────────────────────────────────────────
        try:
            from utils.contract_generator import generate_contract_pdf
            from pathlib import Path

            contracts_dir = Path(current_app.root_path) / 'db_assets' / 'contracts'
            contracts_dir.mkdir(parents=True, exist_ok=True)

            is_lifetime = meta.get('is_lifetime') == 'True'
            duration_years = int(meta.get('duration_years', 3))
            start_date = datetime.now().strftime('%d/%m/%Y')
            if is_lifetime:
                end_date = 'À vie'
                duration_text = 'À vie'
            elif duration_years == 0:
                end_date = 'Illimité (streaming uniquement)'
                duration_text = 'Streaming seul — perpétuel'
            else:
                end_year = datetime.now().year + duration_years
                end_date = f"31/12/{end_year}"
                duration_text = f"{duration_years} an{'s' if duration_years > 1 else ''}"

            contract_filename = f"contract_{purchase.id}_{track_id}.pdf"
            contract_path = contracts_dir / contract_filename

            contract_data = {
                'track_title':            track.title,
                'composer_name':          track.composer_user.username,
                'composer_address':       getattr(track.composer_user, 'address', ''),
                'composer_email':         track.composer_user.email,
                'composer_credit':        f"Prod. par {track.composer_user.username}",
                'client_name':            current_user.username,
                'client_address':         meta.get('buyer_address', ''),
                'client_email':           meta.get('buyer_email', current_user.email),
                'is_exclusive':           meta.get('is_exclusive') == 'True',
                'start_date':             start_date,
                'end_date':               end_date,
                'duration_text':          duration_text,
                'territory':              meta.get('territory', 'Monde entier'),
                'mechanical_reproduction': meta.get('mechanical_reproduction') == 'True',
                'public_show':            meta.get('public_show') == 'True',
                'streaming':              True,
                'arrangement':            meta.get('arrangement') == 'True',
                'price':                  total_price,
                'platform_commission':    10,
                'signature_date':         start_date,
            }

            generate_contract_pdf(str(contract_path), contract_data)
            purchase.contract_file = contract_filename

        except Exception as pdf_err:
            current_app.logger.error(
                f"Erreur génération contrat PDF purchase #{purchase.id}: {pdf_err}",
                exc_info=True,
            )
            # Non bloquant : on continue sans PDF

        # ── Notifications ────────────────────────────────────────────────────
        notify_purchase_confirmed(purchase)
        notify_sale_completed(purchase)

        db.session.commit()

        current_app.logger.info(
            f"Purchase #{purchase.id} créé | track #{track_id} {meta.get('format_type')} | "
            f"total {total_price}€ | buyer #{current_user.id}"
        )

        # ── Emails (hors transaction) ────────────────────────────────────────
        try:
            send_purchase_confirmation_email(purchase)
        except Exception as e:
            current_app.logger.error(f"Erreur email acheteur purchase #{purchase.id}: {e}")

        try:
            send_sale_notification_email(purchase)
        except Exception as e:
            current_app.logger.error(f"Erreur email compositeur purchase #{purchase.id}: {e}")

        return ok(
            data={'purchase_id': purchase.id},
            message='Paiement confirmé ! Votre achat est disponible dans vos téléchargements.',
        )

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe verify purchase: {e}", exc_info=True)
        return err(f"Erreur Stripe : {str(e)}", code='STRIPE_ERROR', status=502)
    except Exception as e:
        current_app.logger.error(f"Erreur verify_payment: {e}", exc_info=True)
        return err('Erreur serveur.', code='SERVER_ERROR', status=500)
