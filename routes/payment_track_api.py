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
from pathlib import Path

from extensions import db, csrf
from models import Track, User, Purchase
from serializers import ok, err
from utils.auth_helpers import require_user

_TWO_PLACES = Decimal('0.01')
from utils.payment_validator import TrackPriceCalculator
from utils.wallet_service import credit_wallet_for_beat_sale
from utils.notification_service import notify_purchase_confirmed, notify_sale_completed
from utils.email_service import send_purchase_confirmation_email, send_sale_notification_email
from utils.license_service import (
    ALLOWED_DURATION_YEARS,
    compute_expires_at,
    build_duration_text,
    build_end_date_text,
)
from utils.contract_data_builder import build_contract_data, create_contract_and_pdf

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
        "is_lifetime":              bool,  (durée légale de protection)
        "duration_years":           int  (0 = streaming seul | 10 = terme de 10 ans),
        "territory":                str  ("France" | "Europe" | "Monde entier"),
        "mechanical_reproduction":  bool,
        "public_show":              bool,
        "arrangement":              bool,
        "total_price":              float  (prix calculé côté client — validé serveur),
        "buyer_address":            str  (optionnel),
        "buyer_email":              str  (optionnel),
        "legal_terms_accepted":     bool (obligatoire),
        "withdrawal_right_waived":  bool (obligatoire — renonciation art. L.221-28 13° C. conso),
        "buyer_declares_original_lyrics": bool (optionnel)
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

    # ── Consentement (RGPD / droit de rétractation) ──────────────────────────
    # Deux actes positifs distincts exigés à l'achat : les CGU/conditions de
    # licence, et la renonciation expresse au droit de rétractation de 14 jours
    # sur ce contenu numérique immédiatement disponible (art. L.221-28 13° C. conso).
    # Non re-dérivables plus tard : sans preuve de consentement au moment de
    # l'achat, la charge de la preuve pèse sur le professionnel.
    legal_terms_accepted    = bool(data.get('legal_terms_accepted', False))
    withdrawal_right_waived = bool(data.get('withdrawal_right_waived', False))
    buyer_declares_original_lyrics = bool(data.get('buyer_declares_original_lyrics', False))

    if not legal_terms_accepted:
        return err(
            'Vous devez accepter les conditions légales de la licence.',
            code='LEGAL_TERMS_REQUIRED', status=400,
        )
    if not withdrawal_right_waived:
        return err(
            'Vous devez renoncer expressément à votre droit de rétractation pour ce '
            'contenu numérique immédiatement disponible.',
            code='WITHDRAWAL_WAIVER_REQUIRED', status=400,
        )

    # Barème fermé : 0 (streaming seul) ou 10 ans. Sans cette liste blanche, une
    # durée hors barème (7 ans…) retomberait sur le fee par défaut du calculateur
    # tout en étant écrite telle quelle dans le contrat.
    is_lifetime_opt = bool(data.get('is_lifetime', False))
    try:
        duration_years_opt = int(data.get('duration_years', 0))
    except (TypeError, ValueError):
        return err('Durée invalide.', code='INVALID_DURATION', status=400)
    if not is_lifetime_opt and duration_years_opt not in ALLOWED_DURATION_YEARS:
        return err('Durée invalide.', code='INVALID_DURATION', status=400)

    # « Streaming seul » : aucun droit additionnel n'est concédé. Le PDF imprime
    # d'ailleurs « aucun autre droit d'exploitation n'est accordé » dans ce cas —
    # sans cette normalisation, une requête forgée produirait un contrat qui se
    # contredit lui-même (art. 3 vs art. 5) et ferait payer des droits fantômes.
    stream_only = not is_lifetime_opt and duration_years_opt == 0

    options = {
        'is_exclusive':            bool(data.get('is_exclusive', False)),
        'is_lifetime':             is_lifetime_opt,
        'duration_years':          duration_years_opt,
        'territory':               data.get('territory', 'Monde entier'),
        'mechanical_reproduction': not stream_only and bool(data.get('mechanical_reproduction', False)),
        'public_show':             not stream_only and bool(data.get('public_show', False)),
        'arrangement':             not stream_only and bool(data.get('arrangement', False)),
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
        duration_years = str(duration_years_opt)
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
            'legal_terms_accepted':           str(legal_terms_accepted),
            'withdrawal_right_waived':        str(withdrawal_right_waived),
            'buyer_declares_original_lyrics': str(buyer_declares_original_lyrics),
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
            data={'checkout_url': checkout_session.url, 'total': float(server_total)},
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

        track_id    = int(meta.get('track_id'))
        is_exclusive = meta.get('is_exclusive') == 'True'

        if is_exclusive:
            # Verrou de ligne (SELECT … FOR UPDATE) — garantit qu'un seul verify
            # exclusif peut lire-puis-écrire is_exclusive_sold de façon atomique.
            # Sans ce verrou, deux verify simultanés passeraient tous les deux la
            # vérification (is_exclusive_sold=False) avant que l'un commite.
            from sqlalchemy import select as _sa_select
            track = db.session.execute(
                _sa_select(Track).where(Track.id == track_id).with_for_update()
            ).scalar_one_or_none()
        else:
            track = db.session.get(Track, track_id)

        if not track:
            return err('Track introuvable.', code='TRACK_NOT_FOUND', status=404)

        # Guard anti-double-vente — vérification sous verrou pour les achats exclusifs.
        if is_exclusive and track.is_exclusive_sold:
            return err(
                'Ce track a déjà été vendu en exclusivité à un autre acheteur. '
                'Contactez le support pour un remboursement.',
                code='TRACK_EXCLUSIVE_SOLD', status=409,
            )

        total_price      = Decimal(str(meta.get('track_price', payment_intent.amount / 100)))
        platform_fee     = (total_price * Decimal('0.10')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        composer_revenue = (total_price - platform_fee).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)

        # ── Données de licence extraites des métadonnées Stripe ─────────────
        is_lifetime    = meta.get('is_lifetime') == 'True'
        duration_years = int(meta.get('duration_years', 0)) if not is_lifetime else None
        # duration_years == 0 signifie "streaming seul"
        if duration_years == 0:
            duration_years = None
        territory      = meta.get('territory', 'Monde entier')
        expires_at_val = compute_expires_at(is_lifetime, duration_years)

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
            # Champs lifecycle licence
            is_exclusive=is_exclusive,
            duration_years=duration_years,
            is_lifetime=is_lifetime,
            territory=territory,
            expires_at=expires_at_val,
            license_status='active',
        )
        db.session.add(purchase)
        db.session.flush()  # obtenir purchase.id

        # ── Créer le Contract record + PDF (builder partagé) ─────────────────
        duration_text_val = build_duration_text(is_lifetime, duration_years)
        start_date_str    = datetime.now().strftime('%d/%m/%Y')
        end_date_str      = build_end_date_text(is_lifetime, expires_at_val)

        contract_data = build_contract_data(
            track=track,
            composer_user=track.composer_user,
            client_user=current_user,
            is_exclusive=is_exclusive,
            start_date=start_date_str,
            end_date=end_date_str,
            duration_text=duration_text_val,
            territory=territory,
            mechanical_reproduction=meta.get('mechanical_reproduction') == 'True',
            public_show=meta.get('public_show') == 'True',
            arrangement=meta.get('arrangement') == 'True',
            price=total_price,
            client_address=meta.get('buyer_address', ''),
            client_email=meta.get('buyer_email', current_user.email),
            buyer_declares_original_lyrics=meta.get('buyer_declares_original_lyrics') == 'True',
            legal_terms_accepted=meta.get('legal_terms_accepted') == 'True',
            withdrawal_right_waived=meta.get('withdrawal_right_waived') == 'True',
        )
        contracts_dir = Path(current_app.root_path) / 'db_assets' / 'contracts'
        create_contract_and_pdf(
            contract_data=contract_data,
            contracts_dir=contracts_dir,
            filename_prefix=f"contract_{purchase.id}_{track_id}",
            purchase=purchase,
        )

        # ── Marquer le track comme vendu en exclusivité ──────────────────────
        if is_exclusive:
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
