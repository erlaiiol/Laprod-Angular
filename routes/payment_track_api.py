"""
Blueprint PAYMENT TRACK API — JSON API pour l'achat de tracks (frontend Angular)

POST  /api/payment/track/<track_id>/<format_type>/checkout
  → Valide le prix côté serveur, crée une session Stripe Checkout, retourne l'URL.

Le callback succès Stripe reste géré par routes/payment.py → /payment/success
(logique métier : création Purchase, wallet, contrat PDF, notifications).
"""
from flask import Blueprint, jsonify, request, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import stripe

from extensions import db
from models import Track, User
from utils.payment_validator import TrackPriceCalculator

payment_track_api_bp = Blueprint('payment_track_api', __name__, url_prefix='/api/payment')


# ── Helpers réponse unifiée ────────────────────────────────────────────────────

def _ok(data=None, message='', code=None, status=200):
    body = {'success': True, 'feedback': {'level': 'success', 'message': message}}
    if data is not None:
        body['data'] = data
    if code:
        body['code'] = code
    return jsonify(body), status


def _err(message, level='error', code=None, status=400):
    body = {'success': False, 'feedback': {'level': level, 'message': message}}
    if code:
        body['code'] = code
    return jsonify(body), status


# ── POST /api/payment/track/<id>/<format>/checkout ─────────────────────────────

@payment_track_api_bp.route('/track/<int:track_id>/<format_type>/checkout', methods=['POST'])
@jwt_required()
def create_checkout(track_id, format_type):
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
    current_user_id = int(get_jwt_identity())
    current_user = db.session.get(User, current_user_id)
    if not current_user:
        return _err('Utilisateur introuvable.', code='USER_NOT_FOUND', status=404)

    if format_type not in ('mp3', 'wav', 'stems'):
        return _err('Format invalide.', code='INVALID_FORMAT', status=400)

    track = db.session.get(Track, track_id)
    if not track:
        return _err('Track introuvable.', code='NOT_FOUND', status=404)
    if not track.is_approved:
        return _err('Cette track n\'est pas disponible.', code='TRACK_UNAVAILABLE', status=403)
    if current_user_id == track.composer_id:
        return _err(
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
        return _err(str(e), code='PRICE_CALC_ERROR', status=400)

    client_total = data.get('total_price')
    if client_total is not None and abs(server_total - float(client_total)) > 0.01:
        current_app.logger.error(
            f"Prix manipulé ! Client: {client_total}€, Serveur: {server_total}€, "
            f"User: {current_user_id}, Track: {track_id}"
        )
        return _err('Prix invalide. Veuillez rafraîchir la page.', code='PRICE_TAMPERED', status=403)

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
            'buyer_id':               str(current_user_id),
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
        }

        base_url = request.url_root.rstrip('/')

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'unit_amount': round(server_total * 100),
                    'product_data': {
                        'name': f"{track.title} — {format_type.upper()}",
                        'description': f"Licence d'exploitation par {track.composer_user.username}",
                    },
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f"{base_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/track/{track_id}",
            metadata=metadata,
            customer_email=buyer_email,
        )

        current_app.logger.info(
            f"Checkout Stripe créé | track #{track_id} {format_type} | "
            f"total {server_total}€ | user #{current_user_id}"
        )

        return _ok(
            data={'checkout_url': checkout_session.url, 'total': server_total},
            message='Session Stripe créée.',
        )

    except stripe.StripeError as e:
        current_app.logger.error(f"Erreur Stripe checkout track #{track_id}: {e}", exc_info=True)
        return _err(f"Erreur Stripe : {str(e)}", code='STRIPE_ERROR', status=500)
    except Exception as e:
        current_app.logger.error(f"Erreur checkout track #{track_id}: {e}", exc_info=True)
        return _err(str(e), code='SERVER_ERROR', status=500)
