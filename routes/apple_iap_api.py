"""
Blueprint APPLE IAP — abonnement LaProd+ acheté dans l'app iOS (StoreKit 2).

  GET  /api/apple-iap/policy         → ce que l'app iOS a le droit de vendre (public)
  GET  /api/apple-iap/products       → produits App Store par palier + jeton de compte
  POST /api/apple-iap/verify         → vérifie des transactions signées et crédite
  POST /api/apple-iap/notifications  → notifications serveur App Store V2 (remboursements)

Le web et Android n'appellent jamais ces routes : ils restent sur Stripe
(routes/premium_api.py). Voir docs/architecture.md § Paiements sur iOS.
"""
from flask import Blueprint, request, current_app
from flask_jwt_extended import jwt_required

from extensions import db, csrf, limiter
from serializers import ok, err
from utils import apple_iap, plans
from utils.auth_helpers import require_user
from utils.crud_helpers import commit_or_rollback, handle_route_exceptions
from utils.notification_service import create_notification
from routes.premium_api import _premium_status

apple_iap_api_bp = Blueprint('apple_iap_api', __name__, url_prefix='/api/apple-iap')

# Une restauration renvoie tout l'historique de l'appareil : on borne pour qu'une
# requête ne puisse pas déclencher des centaines de vérifications de signature.
_MAX_TRANSACTIONS_PER_CALL = 25


@apple_iap_api_bp.route('/policy', methods=['GET'])
def policy():
    """PUBLIQUE : l'app iOS doit savoir quoi afficher avant même la connexion
    (la fiche d'un beat est consultable sans compte)."""
    return ok({'policy': apple_iap.ios_purchase_policy()})


@apple_iap_api_bp.route('/products', methods=['GET'])
@jwt_required()
@handle_route_exceptions
@require_user
def products(current_user):
    """Les identifiants de produit viennent du serveur : le front n'en code aucun
    en dur, comme pour la grille Stripe (GET /api/premium/plans)."""
    configured = apple_iap.is_configured()
    items = []
    if configured:
        for plan, product_id in apple_iap.product_ids().items():
            items.append({'plan': plan, 'product_id': product_id})
    return ok({
        'configured':        configured,
        'products':          items,
        'app_account_token': apple_iap.account_token_for(current_user.id),
    })


@apple_iap_api_bp.route('/verify', methods=['POST'])
@csrf.exempt
@jwt_required()
@limiter.limit('30 per minute')
@handle_route_exceptions
@require_user
@commit_or_rollback
def verify(current_user):
    """Body : {transactions: ['<JWS>', …]}. Un achat en envoie une, une
    restauration en envoie plusieurs. Chaque transaction n'est créditée qu'une
    fois, quel que soit le nombre de fois où l'app la représente."""
    data = request.get_json(silent=True) or {}
    signed_list = data.get('transactions')
    if isinstance(signed_list, str):
        signed_list = [signed_list]
    if not isinstance(signed_list, list) or not signed_list:
        return err('Aucun achat à vérifier.', code='IAP_NO_TRANSACTION', status=400)
    signed_list = [s for s in signed_list if isinstance(s, str) and s][:_MAX_TRANSACTIONS_PER_CALL]

    credited = []
    first_error = None
    for signed in signed_list:
        try:
            tx = apple_iap.verify_transaction(signed)
            row, was_credited = apple_iap.credit_transaction(current_user, tx)
            db.session.commit()
            if was_credited:
                credited.append(row)
        except apple_iap.AppleIapError as exc:
            # Une restauration mélange des achats valides et des achats remboursés
            # ou faits sur un autre compte : un refus ne doit pas bloquer les autres.
            db.session.rollback()
            first_error = first_error or exc

    if not credited and first_error is not None and len(signed_list) == 1:
        status = 503 if first_error.code == 'IAP_NOT_CONFIGURED' else 400
        return err(first_error.message, code=first_error.code, status=status)

    for row in credited:
        label = plans.label_of(row.plan)
        create_notification(
            user_id=current_user.id,
            notif_type='system',
            title=f'LaProd+ {label} activé',
            message=(
                f'Ton abonnement LaProd+ {label} est actif jusqu\'au '
                f'{current_user.premium_expires_at.strftime("%d/%m/%Y")}.'
            ),
            link='/premium',
        )
        current_app.logger.info(
            "[APPLE-IAP] crédit user=%s plan=%s tx=%s env=%s",
            current_user.id, row.plan, row.transaction_id, row.environment)

    payload = _premium_status(current_user)
    payload['credited'] = len(credited)
    message = ''
    if credited:
        message = f'Abonnement LaProd+ {plans.label_of(credited[-1].plan)} activé.'
    return ok(payload, message=message)


@apple_iap_api_bp.route('/notifications', methods=['POST'])
@csrf.exempt
@limiter.limit('300 per minute')
def notifications():
    """Notifications serveur App Store V2. PUBLIQUE par nature (c'est Apple qui
    appelle) : l'authentification est la signature du payload, vérifiée contre
    les certificats racine d'Apple — un corps non signé est rejeté.

    Seuls le remboursement et la révocation nous concernent : l'abonnement ne se
    renouvelle pas automatiquement, il n'y a donc aucun cycle de vie à suivre."""
    data = request.get_json(silent=True) or {}
    signed_payload = data.get('signedPayload')
    if not isinstance(signed_payload, str) or not signed_payload:
        return err('Notification invalide.', code='IAP_INVALID_NOTIFICATION', status=400)

    try:
        notification = apple_iap.verify_notification(signed_payload)
    except apple_iap.AppleIapError as exc:
        # 503 si non configuré : Apple réessaiera, on ne perd pas un remboursement
        # parce qu'une variable manquait au moment où il est arrivé.
        status = 503 if exc.code == 'IAP_NOT_CONFIGURED' else 400
        return err('Notification invalide.', code=exc.code, status=status)

    notif_type = getattr(notification, 'rawNotificationType', None)
    if notif_type not in ('REFUND', 'REVOKE'):
        return ok({'handled': False})

    signed_tx = getattr(getattr(notification, 'data', None), 'signedTransactionInfo', None)
    if not signed_tx:
        return ok({'handled': False})

    try:
        tx = apple_iap.verify_transaction(signed_tx)
        user = apple_iap.revoke_transaction(getattr(tx, 'transactionId', None) or '')
        db.session.commit()
    except apple_iap.AppleIapError:
        db.session.rollback()
        return err('Notification invalide.', code='IAP_INVALID_NOTIFICATION', status=400)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error("[APPLE-IAP] échec reprise %s : %s", notif_type, exc, exc_info=True)
        return err('Erreur interne.', status=500)

    if user is not None:
        current_app.logger.info(
            "[APPLE-IAP] %s tx=%s user=%s → jours repris", notif_type, tx.transactionId, user.id)
        try:
            create_notification(
                user_id=user.id,
                notif_type='system',
                title='Achat LaProd+ remboursé',
                message="Apple a remboursé un de tes achats LaProd+ : la période "
                        "correspondante a été retirée de ton abonnement.",
                link='/premium',
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
    return ok({'handled': user is not None})
