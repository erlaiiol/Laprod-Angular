"""
Blueprint LICENSES API — Gestion du cycle de vie des licences

GET  /api/licenses                          → licences de l'artiste connecté
GET  /api/licenses/<purchase_id>            → détail d'une licence
GET  /api/licenses/<purchase_id>/contract   → PDF du contrat

POST /api/track-payment/track/<id>/renew/<purchase_id>   → Checkout Stripe de renouvellement
POST /api/track-payment/verify-renewal                   → Vérification et création de la nouvelle licence

GET  /api/composer/licenses                → licences vendues (compositeur)
GET  /api/composer/licenses/exclusive      → licences exclusives vendues
"""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request, current_app, send_file
from flask_jwt_extended import jwt_required
import stripe
import stripe._error as stripe_error
from datetime import datetime
from pathlib import Path

from extensions import db, csrf
from models import Track, Purchase
from serializers import ok, err
from utils.auth_helpers import require_user
from utils.license_service import (
    get_user_licenses,
    get_composer_sold_licenses,
    compute_expires_at,
    compute_days_remaining,
    build_duration_text,
    build_end_date_text,
    is_sole_licensee,
    get_renewal_price,
)
from utils.contract_service import mark_contract_renewed
from utils.contract_data_builder import build_contract_data, create_contract_and_pdf

_TWO_PLACES = Decimal('0.01')

licenses_api_bp = Blueprint('licenses_api', __name__)


# ── Sérialiseur interne ───────────────────────────────────────────────────────

def _serialize_license(p: Purchase, include_sole: bool = False) -> dict:
    from serializers import track_card
    days = compute_days_remaining(p)
    sole = is_sole_licensee(p) if include_sole else False
    return {
        'id':              p.id,
        'track':           track_card(p.track),
        'format':          p.format_purchased,
        'price_paid':      float(p.price_paid),
        'is_exclusive':    p.is_exclusive,
        'duration_years':  p.duration_years,
        'is_lifetime':     p.is_lifetime,
        'territory':       p.territory,
        'expires_at':      p.expires_at.isoformat() if p.expires_at else None,
        'days_remaining':  days,
        'license_status':  p.license_status,
        'is_sole_licensee': sole,
        'renewed_from_id': p.renewed_from_id,
        'renewed_to_id':   p.renewed_to_id,
        'contract_url':    f'/api/licenses/{p.id}/contract' if p.contract_file else None,
        'created_at':      p.created_at.isoformat(),
    }


# ────────────────────────────────────────────────────────────────────────────
# ARTISTE — ses licences
# ────────────────────────────────────────────────────────────────────────────

@licenses_api_bp.route('/api/licenses', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_my_licenses(current_user):
    """Liste toutes les licences de l'artiste connecté."""
    purchases = get_user_licenses(current_user.id)
    return ok(data={
        'licenses': [_serialize_license(p, include_sole=True) for p in purchases],
        'total': len(purchases),
    })


@licenses_api_bp.route('/api/licenses/<int:purchase_id>', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_license_detail(purchase_id, current_user):
    """Détail d'une licence — réservé à l'acheteur."""
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Licence introuvable.', code='NOT_FOUND', status=404)
    if purchase.buyer_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)
    return ok(data=_serialize_license(purchase, include_sole=True))


@licenses_api_bp.route('/api/licenses/<int:purchase_id>/contract', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def download_license_contract(purchase_id, current_user):
    """Télécharger le PDF du contrat — réservé à l'acheteur."""
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Licence introuvable.', code='NOT_FOUND', status=404)
    if purchase.buyer_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)
    if not purchase.contract_file:
        return err('Aucun contrat disponible.', code='NO_CONTRACT', status=404)

    contracts_dir = (Path(current_app.root_path) / 'db_assets' / 'contracts').resolve()
    contract_path = (contracts_dir / purchase.contract_file).resolve()

    # Défense en profondeur : confiner le chemin sous db_assets/contracts.
    if not contract_path.is_relative_to(contracts_dir):
        current_app.logger.warning(
            f'[SECURITY] Path traversal bloqué contrat purchase #{purchase_id}: {purchase.contract_file!r}'
        )
        return err('Accès refusé.', code='FORBIDDEN', status=403)

    if not contract_path.exists():
        return err('Fichier contrat introuvable.', code='FILE_NOT_FOUND', status=404)

    return send_file(str(contract_path), as_attachment=True,
                     download_name=f'contrat_{purchase_id}.pdf',
                     mimetype='application/pdf')


# ────────────────────────────────────────────────────────────────────────────
# RENOUVELLEMENT
# ────────────────────────────────────────────────────────────────────────────

@licenses_api_bp.route('/api/track-payment/track/<int:track_id>/renew/<int:purchase_id>',
                       methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def create_renewal_checkout(track_id, purchase_id, current_user):
    """
    Crée une session Stripe Checkout pour le renouvellement d'une licence.

    Corps JSON : { is_lifetime, duration_years, territory } optionnels (reprend
    les termes de la licence originale si absents), plus deux champs de
    consentement obligatoires — legal_terms_accepted, withdrawal_right_waived —
    au même titre qu'un achat initial : un renouvellement est un nouveau
    paiement et doit donc être couvert par un nouvel acte de consentement.
    """
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        return err('Licence introuvable.', code='NOT_FOUND', status=404)
    if purchase.buyer_id != current_user.id:
        return err('Accès refusé.', code='FORBIDDEN', status=403)
    if purchase.track_id != track_id:
        return err('Track ne correspond pas à la licence.', code='MISMATCH', status=400)
    if purchase.license_status not in ('active', 'expired'):
        return err('Cette licence ne peut pas être renouvelée.', code='NOT_RENEWABLE', status=409)
    if purchase.renewed_to_id is not None:
        return err('Cette licence a déjà été renouvelée.', code='ALREADY_RENEWED', status=409)

    track = db.session.get(Track, track_id)
    if not track:
        return err('Track introuvable.', code='NOT_FOUND', status=404)

    data          = request.get_json() or {}
    is_lifetime   = bool(data.get('is_lifetime', purchase.is_lifetime))
    duration_years = int(data.get('duration_years', purchase.duration_years or 0))
    territory     = data.get('territory', purchase.territory or 'Monde entier')

    # ── Consentement (même exigence qu'un achat initial — cf. create_checkout) ──
    legal_terms_accepted    = bool(data.get('legal_terms_accepted', False))
    withdrawal_right_waived = bool(data.get('withdrawal_right_waived', False))
    # L'auteur des paroles ne change pas d'un renouvellement à l'autre — on
    # reprend la déclaration d'origine sauf surcharge explicite du client.
    original_lyrics_declared = bool(purchase.contract and purchase.contract.buyer_declares_original_lyrics)
    buyer_declares_original_lyrics = bool(data.get('buyer_declares_original_lyrics', original_lyrics_declared))

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

    renewal_price = get_renewal_price(purchase)
    if renewal_price <= 0:
        return err(
            "Cette licence n'a pas de terme : elle court pour la durée légale de "
            "protection et n'a donc pas besoin d'être renouvelée.",
            code='NOTHING_TO_RENEW', status=400,
        )

    try:
        frontend_url = current_app.config.get('FRONTEND_URL', 'http://localhost:4200')
        metadata = {
            'renewal_of_purchase_id': str(purchase_id),
            'track_id':               str(track_id),
            'track_title':            track.title,
            'composer_id':            str(track.composer_id),
            'buyer_id':               str(current_user.id),
            'buyer_username':         current_user.username,
            'format_type':            purchase.format_purchased,
            'is_exclusive':           str(purchase.is_exclusive),
            'is_lifetime':            str(is_lifetime),
            'duration_years':         str(duration_years),
            'territory':              territory,
            'mechanical_reproduction': str(bool(purchase.contract and purchase.contract.mechanical_reproduction)),
            'public_show':            str(bool(purchase.contract and purchase.contract.public_show)),
            'arrangement':            str(bool(purchase.contract and purchase.contract.arrangement)),
            'track_price':            str(renewal_price),
            'legal_terms_accepted':           str(legal_terms_accepted),
            'withdrawal_right_waived':        str(withdrawal_right_waived),
            'buyer_declares_original_lyrics': str(buyer_declares_original_lyrics),
        }

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': int(renewal_price * 100),
                    'product_data': {
                        'name': f"Renouvellement — {track.title} {purchase.format_purchased.upper()}",
                        'description': f"Licence d'exploitation par {track.composer_user.username}",
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{frontend_url}/payment/renewal/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/licenses",
            metadata=metadata,
            payment_intent_data={'metadata': metadata},
            customer_email=current_user.email,
        )

        return ok(
            data={'checkout_url': checkout_session.url, 'total': float(renewal_price)},
            message='Session Stripe de renouvellement créée.',
        )

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe renewal: {e}", exc_info=True)
        return err(f"Erreur Stripe : {str(e)}", code='STRIPE_ERROR', status=500)


@licenses_api_bp.route('/api/track-payment/verify-renewal', methods=['POST'])
@jwt_required()
@csrf.exempt
@require_user
def verify_renewal_payment(current_user):
    """
    Vérifie le paiement Stripe d'un renouvellement et crée la nouvelle licence.
    Body JSON : { session_id: string }
    """
    data       = request.get_json() or {}
    session_id = data.get('session_id', '').strip()
    if not session_id:
        return err('session_id requis.', code='MISSING_SESSION', status=400)

    try:
        checkout_session  = stripe.checkout.Session.retrieve(session_id)
        payment_intent_id = checkout_session.payment_intent

        if not payment_intent_id:
            return err('Aucun Payment Intent trouvé.', code='NO_PAYMENT_INTENT', status=400)

        payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        if payment_intent.status != 'succeeded':
            return err(
                f'Paiement non confirmé (statut : {payment_intent.status}).',
                level='warning', code='PAYMENT_NOT_SUCCEEDED', status=400,
            )

        meta = checkout_session.metadata

        if int(meta.get('buyer_id', -1)) != current_user.id:
            return err('Cette session ne vous appartient pas.', code='UNAUTHORIZED', status=403)

        # Idempotence
        existing = db.session.query(Purchase).filter_by(
            stripe_payment_intent_id=payment_intent_id
        ).first()
        if existing:
            return ok({'purchase_id': existing.id}, message='Renouvellement déjà enregistré.', level='info')

        old_purchase_id = int(meta.get('renewal_of_purchase_id'))
        old_purchase    = db.session.get(Purchase, old_purchase_id)
        if not old_purchase:
            return err('Licence originale introuvable.', code='NOT_FOUND', status=404)
        if old_purchase.renewed_to_id is not None:
            return err('Cette licence a déjà été renouvelée.', code='ALREADY_RENEWED', status=409)

        track_id       = int(meta.get('track_id'))
        track          = db.session.get(Track, track_id)
        if not track:
            return err('Track introuvable.', code='NOT_FOUND', status=404)

        is_lifetime    = meta.get('is_lifetime') == 'True'
        duration_years = int(meta.get('duration_years', 0)) or None
        territory      = meta.get('territory', 'Monde entier')
        total_price    = Decimal(str(meta.get('track_price', payment_intent.amount / 100)))
        platform_fee   = (total_price * Decimal('0.10')).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        composer_rev   = (total_price - platform_fee).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
        expires_at_val = compute_expires_at(is_lifetime, duration_years)

        new_purchase = Purchase(
            track_id=track_id,
            buyer_id=current_user.id,
            format_purchased=meta.get('format_type', old_purchase.format_purchased),
            price_paid=total_price,
            buyer_name=current_user.username,
            contract_price=0,
            track_price=total_price,
            platform_fee=platform_fee,
            composer_revenue=composer_rev,
            stripe_payment_intent_id=payment_intent_id,
            is_exclusive=old_purchase.is_exclusive,
            duration_years=duration_years,
            is_lifetime=is_lifetime,
            territory=territory,
            expires_at=expires_at_val,
            license_status='active',
        )
        db.session.add(new_purchase)
        db.session.flush()

        # Lier les licences
        mark_contract_renewed(old_purchase, new_purchase)

        # Créer Contract record + PDF (builder partagé)
        duration_text_val = build_duration_text(is_lifetime, duration_years)
        start_str         = datetime.now().strftime('%d/%m/%Y')
        end_str           = build_end_date_text(is_lifetime, expires_at_val)

        contract_data = build_contract_data(
            track=track,
            composer_user=track.composer_user,
            client_user=current_user,
            is_exclusive=old_purchase.is_exclusive,
            start_date=start_str,
            end_date=end_str,
            duration_text=duration_text_val,
            territory=territory,
            mechanical_reproduction=bool(old_purchase.contract and old_purchase.contract.mechanical_reproduction),
            public_show=bool(old_purchase.contract and old_purchase.contract.public_show),
            arrangement=bool(old_purchase.contract and old_purchase.contract.arrangement),
            price=total_price,
            buyer_declares_original_lyrics=meta.get('buyer_declares_original_lyrics') == 'True',
            legal_terms_accepted=meta.get('legal_terms_accepted') == 'True',
            withdrawal_right_waived=meta.get('withdrawal_right_waived') == 'True',
        )
        contracts_dir = Path(current_app.root_path) / 'db_assets' / 'contracts'
        create_contract_and_pdf(
            contract_data=contract_data,
            contracts_dir=contracts_dir,
            filename_prefix=f"contract_{new_purchase.id}_{track_id}_renewal",
            purchase=new_purchase,
        )

        # Créditer wallet compositeur
        from utils.wallet_service import credit_wallet_for_beat_sale
        credit_wallet_for_beat_sale(new_purchase)

        # Notifications
        try:
            from utils.notification_service import notify_renewal_confirmed
            notify_renewal_confirmed(new_purchase)
        except Exception as notif_err:
            current_app.logger.error(f"notify_renewal_confirmed erreur: {notif_err}")

        db.session.commit()

        # Emails hors transaction
        try:
            from utils.email_service import send_renewal_confirmation_email
            send_renewal_confirmation_email(new_purchase)
        except Exception as mail_err:
            current_app.logger.error(f"Erreur email renouvellement #{new_purchase.id}: {mail_err}")

        return ok(
            data={'purchase_id': new_purchase.id},
            message='Renouvellement confirmé !',
        )

    except stripe_error.StripeError as e:
        current_app.logger.error(f"Erreur Stripe verify-renewal: {e}", exc_info=True)
        return err(f"Erreur Stripe : {str(e)}", code='STRIPE_ERROR', status=502)
    except Exception as e:
        current_app.logger.error(f"Erreur verify_renewal_payment: {e}", exc_info=True)
        return err('Erreur serveur.', code='SERVER_ERROR', status=500)


# ────────────────────────────────────────────────────────────────────────────
# COMPOSITEUR — ses licences vendues
# ────────────────────────────────────────────────────────────────────────────

def _serialize_sold_license(p: Purchase) -> dict:
    from serializers import track_card, user_ref
    days = compute_days_remaining(p)
    return {
        'id':             p.id,
        'track':          track_card(p.track),
        'buyer':          user_ref(p.buyer) if hasattr(p, 'buyer') and p.buyer else {'id': p.buyer_id, 'username': p.buyer_name},
        'format':         p.format_purchased,
        'price_paid':     float(p.price_paid),
        'composer_revenue': float(p.composer_revenue),
        'is_exclusive':   p.is_exclusive,
        'duration_years': p.duration_years,
        'is_lifetime':    p.is_lifetime,
        'territory':      p.territory,
        'expires_at':     p.expires_at.isoformat() if p.expires_at else None,
        'days_remaining': days,
        'license_status': p.license_status,
        'created_at':     p.created_at.isoformat(),
    }


@licenses_api_bp.route('/api/composer/licenses', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_composer_licenses(current_user):
    """Toutes les licences vendues par le compositeur connecté."""
    if not current_user.is_beatmaker:
        return err('Accès réservé aux compositeurs.', code='FORBIDDEN', status=403)

    purchases = get_composer_sold_licenses(current_user.id)
    return ok(data={
        'licenses':       [_serialize_sold_license(p) for p in purchases],
        'total':          len(purchases),
        'total_revenue':  float(sum(p.composer_revenue for p in purchases)),
        'exclusive_count': sum(1 for p in purchases if p.is_exclusive),
        'active_count':   sum(1 for p in purchases if p.license_status == 'active'),
        'expiring_count': sum(1 for p in purchases
                              if p.license_status == 'active'
                              and p.expires_at is not None
                              and compute_days_remaining(p) is not None
                              and compute_days_remaining(p) <= 30),
    })


@licenses_api_bp.route('/api/composer/licenses/exclusive', methods=['GET'])
@jwt_required()
@csrf.exempt
@require_user
def get_composer_exclusive_licenses(current_user):
    """Licences exclusives vendues par le compositeur connecté."""
    if not current_user.is_beatmaker:
        return err('Accès réservé aux compositeurs.', code='FORBIDDEN', status=403)

    purchases = [p for p in get_composer_sold_licenses(current_user.id) if p.is_exclusive]
    return ok(data={
        'licenses': [_serialize_sold_license(p) for p in purchases],
        'total':    len(purchases),
    })
