"""
Payment Mixmaster API — Vérification du paiement Stripe après checkout.
L'artiste est redirigé depuis Stripe vers /mix/payment-success?session_id=...
Angular appelle ensuite POST /mixmaster-payment/verify avec {session_id}.
"""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required
from extensions import db, csrf
from models import User, MixMasterRequest, PromoCode
from utils.money import to_money
from utils.promo_service import consume as consume_promo
from utils.notification_service import notify_mixmaster_request_received_and_sent
from utils.email_service import send_mixmaster_request_notification
from utils.stripe_logger import (
    log_stripe_payment_intent_created, log_stripe_error,
)
from utils.archive_utils import get_archive_file_tree
from serializers import ok, err
from utils.auth_helpers import require_user
import stripe
import stripe._error as stripe_error
from datetime import datetime
from pathlib import Path

payment_mixmaster_api_bp = Blueprint(
    'payment_mixmaster_api', __name__, url_prefix='/api/mixmaster-payment'
)


@payment_mixmaster_api_bp.route('/verify', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def verify_payment(current_user):
    """
    Vérifie la session Stripe Checkout et crée le MixMasterRequest.
    Body JSON : { session_id: string }
    """
    data    = request.get_json() or {}
    session_id = data.get('session_id', '').strip()

    if not session_id:
        return err('session_id requis.', level='warning')

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        payment_intent_id = checkout_session.payment_intent

        if not payment_intent_id:
            return err('Aucun Payment Intent trouvé.')

        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

        if payment_intent.status != 'succeeded':
            return err(f'Paiement non confirmé (statut : {payment_intent.status}).', level='warning')

        meta = payment_intent.metadata

        # Vérification de sécurité : l'artiste JWT correspond à la metadata
        if int(meta.get('artist_id', -1)) != current_user.id:
            return err('Cette commande ne vous appartient pas.', status=403)

        # Idempotence : MixMasterRequest déjà créé ?
        existing = db.session.query(MixMasterRequest).filter_by(
            stripe_payment_intent_id=payment_intent_id
        ).first()
        if existing:
            return ok({'order_id': existing.id}, message='Demande déjà enregistrée.', level='info')

        engineer_id = int(meta.get('engineer_id'))
        engineer    = db.session.get(User, engineer_id)
        if not engineer:
            return err('Ingénieur introuvable.', status=404)

        mm = MixMasterRequest(
            title                = meta.get('title', 'Mix/Master')[:50],
            artist_id            = current_user.id,
            engineer_id          = engineer_id,
            original_file        = meta.get('stems_file'),
            reference_file       = meta.get('reference_file'),
            service_cleaning     = meta.get('service_cleaning')     == 'True',
            service_effects      = meta.get('service_effects')      == 'True',
            service_artistic     = meta.get('service_artistic')     == 'True',
            service_mastering    = meta.get('service_mastering')    == 'True',
            has_separated_stems  = meta.get('has_separated_stems')  == 'True',
            artist_message       = meta.get('artist_message')       or None,
            brief_vocals         = meta.get('brief_vocals')         or None,
            brief_backing_vocals = meta.get('brief_backing_vocals') or None,
            brief_ambiance       = meta.get('brief_ambiance')       or None,
            brief_bass           = meta.get('brief_bass')           or None,
            brief_energy_style   = meta.get('brief_energy_style')   or None,
            brief_references     = meta.get('brief_references')     or None,
            brief_instruments    = meta.get('brief_instruments')    or None,
            brief_percussion     = meta.get('brief_percussion')     or None,
            brief_effects        = meta.get('brief_effects_brief')  or None,
            brief_structure      = meta.get('brief_structure')      or None,
            status                    = 'awaiting_acceptance',
            stripe_payment_intent_id  = payment_intent_id,
            stripe_payment_status     = 'captured',  # capture_method=automatic → fonds déjà prélevés
            total_price               = 0,
            deposit_amount            = 0,
            remaining_amount          = 0,
            platform_fee              = 0,
            engineer_revenue          = 0,
        )

        # ── Prix et remise ──────────────────────────────────────────────────
        # Le prix catalogue est recalculé côté serveur (jamais lu du client), puis
        # la remise écrite par NOTRE checkout dans les métadonnées est déduite.
        # total_price doit être le montant NET : tous les calculs dérivés (acompte
        # 30 %, transferts de révision, remboursements) en découlent et doivent
        # correspondre à ce que Stripe a réellement encaissé.
        gross_price     = mm.calculate_service_price(engineer.mixmaster_reference_price)
        gross_price     = to_money(meta.get('gross_price') or gross_price)
        discount_amount = to_money(meta.get('discount_amount') or 0)
        promo_meta_id   = meta.get('promo_code_id') or ''
        promo = db.session.get(PromoCode, int(promo_meta_id)) if promo_meta_id.isdigit() else None

        mm.gross_price     = gross_price
        mm.discount_amount = discount_amount
        mm.promo_code_id   = promo.id if promo else None
        mm.total_price     = to_money(gross_price - discount_amount)
        mm.calculate_payments()

        # Arborescence complète de l'archive (liste de chemins strings)
        if mm.original_file:
            stems_disk = Path(current_app.root_path) / mm.original_file
            if stems_disk.exists():
                raw_tree = get_archive_file_tree(str(stems_disk))
                mm.archive_file_tree = [
                    f['path'] for f in raw_tree if not f['is_dir']
                ] if raw_tree else []

        db.session.add(mm)
        db.session.flush()  # obtenir mm.id avant commit

        # ── Consommer le code promo (après encaissement seulement) ───────────
        if promo:
            consumed = consume_promo(
                promo, current_user.id,
                gross=gross_price, discount=discount_amount, net=mm.total_price,
                mixmaster_request=mm,
            )
            if not consumed:
                # Quota épuisé entre le checkout et l'encaissement : l'artiste a
                # déjà payé le montant remisé, on honore la remise et on trace.
                current_app.logger.warning(
                    f"Promo {promo.code} (#{promo.id}) consommée au-delà de son quota — "
                    f"mixmaster #{mm.id}, artist #{current_user.id}, remise {discount_amount}€"
                )

        log_stripe_payment_intent_created(
            payment_intent_id=payment_intent_id,
            amount=payment_intent.amount,
            resource_type='mixmaster',
            resource_id=mm.id,
            engineer_id=engineer_id,
            artist_id=current_user.id,
            status='authorized',
        )

        notify_mixmaster_request_received_and_sent(mm)
        db.session.commit()

        # Email à l'engineer (hors transaction — un échec email ne doit pas annuler la commande)
        try:
            send_mixmaster_request_notification(mm)
        except Exception as e:
            current_app.logger.error(f'Erreur envoi email mixmaster #{mm.id}: {e}', exc_info=True)

        return ok({'order_id': mm.id}, message="Paiement confirmé ! Votre demande a été envoyée à l'ingénieur.")

    except stripe_error.StripeError as e:
        log_stripe_error(operation='verify_mixmaster_payment', error_message=str(e),
                         resource_type='mixmaster', session_id=session_id)
        return err(f'Erreur Stripe : {str(e)}', status=502)
    except Exception as e:
        current_app.logger.error(f'verify_payment #{session_id}: {e}', exc_info=True)
        return err('Erreur serveur.', status=500)
