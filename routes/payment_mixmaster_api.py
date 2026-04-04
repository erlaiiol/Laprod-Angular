"""
Payment Mixmaster API — Vérification du paiement Stripe après checkout.
L'artiste est redirigé depuis Stripe vers /mix/payment-success?session_id=...
Angular appelle ensuite POST /mixmaster-payment/verify avec {session_id}.
"""
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from extensions import db, csrf
from models import User, MixMasterRequest
from utils.notification_service import notify_mixmaster_request_received_and_sent
from utils.stripe_logger import (
    log_stripe_payment_intent_created, log_stripe_error,
)
from utils.archive_utils import get_archive_file_tree
import stripe
import stripe._error as stripe_error
from datetime import datetime
from pathlib import Path

payment_mixmaster_api_bp = Blueprint(
    'payment_mixmaster_api', __name__, url_prefix='/mixmaster-payment'
)


@payment_mixmaster_api_bp.route('/verify', methods=['POST'])
@jwt_required()
@csrf.exempt
def verify_payment():
    """
    Vérifie la session Stripe Checkout et crée le MixMasterRequest.
    Body JSON : { session_id: string }
    """
    user_id = int(get_jwt_identity())
    data    = request.get_json() or {}
    session_id = data.get('session_id', '').strip()

    if not session_id:
        return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': 'session_id requis.'}}), 400

    try:
        checkout_session = stripe.checkout.Session.retrieve(session_id)
        payment_intent_id = checkout_session.payment_intent

        if not payment_intent_id:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Aucun Payment Intent trouvé.'}}), 400

        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)

        if payment_intent.status not in ('requires_capture', 'succeeded'):
            return jsonify({'success': False, 'feedback': {'level': 'warning', 'message': f'Paiement non confirmé (statut : {payment_intent.status}).'}}), 400

        meta = payment_intent.metadata

        # Vérification de sécurité : l'artiste JWT correspond à la metadata
        if int(meta.get('artist_id', -1)) != user_id:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Cette commande ne vous appartient pas.'}}), 403

        # Idempotence : MixMasterRequest déjà créé ?
        existing = db.session.query(MixMasterRequest).filter_by(
            stripe_payment_intent_id=payment_intent_id
        ).first()
        if existing:
            return jsonify({
                'success': True,
                'feedback': {'level': 'info', 'message': 'Demande déjà enregistrée.'},
                'data': {'order_id': existing.id},
            }), 200

        engineer_id = int(meta.get('engineer_id'))
        engineer    = db.session.get(User, engineer_id)
        if not engineer:
            return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Ingénieur introuvable.'}}), 404

        mm = MixMasterRequest(
            title                = meta.get('title', 'Mix/Master')[:50],
            artist_id            = user_id,
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
            stripe_payment_status     = 'authorized',
            total_price               = 0,
            deposit_amount            = 0,
            remaining_amount          = 0,
            platform_fee              = 0,
            engineer_revenue          = 0,
        )

        mm.total_price    = mm.calculate_service_price(engineer.mixmaster_reference_price)
        mm.deposit_amount = round(mm.total_price * 0.30, 2)
        mm.remaining_amount = round(mm.total_price - mm.deposit_amount, 2)
        mm.platform_fee   = round(mm.total_price * 0.10, 2)
        mm.engineer_revenue = round(mm.total_price - mm.platform_fee, 2)

        # Arborescence complète de l'archive
        if mm.original_file:
            stems_disk = Path(current_app.root_path) / mm.original_file
            if stems_disk.exists():
                mm.archive_file_tree = get_archive_file_tree(str(stems_disk))

        db.session.add(mm)
        db.session.flush()  # obtenir mm.id avant commit

        log_stripe_payment_intent_created(
            payment_intent_id=payment_intent_id,
            amount=payment_intent.amount,
            resource_type='mixmaster',
            resource_id=mm.id,
            engineer_id=engineer_id,
            artist_id=user_id,
            status='authorized',
        )

        notify_mixmaster_request_received_and_sent(mm)
        db.session.commit()

        return jsonify({
            'success': True,
            'feedback': {'level': 'success', 'message': 'Paiement confirmé ! Votre demande a été envoyée à l\'ingénieur.'},
            'data': {'order_id': mm.id},
        }), 200

    except stripe_error.StripeError as e:
        log_stripe_error(operation='verify_mixmaster_payment', error_message=str(e),
                         resource_type='mixmaster', session_id=session_id)
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': f'Erreur Stripe : {str(e)}'}}), 502
    except Exception as e:
        current_app.logger.error(f'verify_payment #{session_id}: {e}', exc_info=True)
        return jsonify({'success': False, 'feedback': {'level': 'error', 'message': 'Erreur serveur.'}}), 500
