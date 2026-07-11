"""
Blueprint STRIPE WEBHOOK — réconciliation serveur des événements Stripe.

POST /api/stripe/webhook
  → Vérifie la signature Stripe (construct_event), déduplique via Redis, puis
    traite les événements de réconciliation NON couverts par le flux /verify :
      • charge.refunded        → annule le crédit wallet du compositeur
      • charge.dispute.created → gèle la licence + annule le crédit si possible
      • account.updated        → met à jour le statut Stripe Connect du vendeur

Le flux d'achat (création de Purchase) reste géré par /verify côté client ; ce
webhook couvre les événements asynchrones et négatifs que le client ne signale
jamais (remboursements, litiges/chargebacks, changements de compte Connect).
"""
from decimal import Decimal
from flask import Blueprint, request, current_app

import stripe

from extensions import db, csrf, limiter
from models import Purchase, Wallet, WalletTransaction, User

stripe_webhook_bp = Blueprint('stripe_webhook_api', __name__, url_prefix='/api/stripe')

# TTL de déduplication des event ids Stripe (24h : Stripe re-livre pendant ~3 jours
# mais un même event traité une fois ne doit jamais l'être deux fois de suite).
_EVENT_DEDUP_TTL = 24 * 3600


def _already_processed(event_id: str) -> bool:
    """
    Idempotence via Redis : renvoie True si l'event a déjà été traité.
    SET NX pose la clé seulement si absente → premier passage renvoie False.
    Si Redis est indisponible, on ne bloque pas (au pire double-traitement, mais
    chaque handler est lui-même idempotent sur l'état du Purchase/wallet).
    """
    from extensions import redis_client
    if redis_client is None:
        return False
    try:
        # set(..., nx=True) renvoie True si la clé a été créée, None si elle existait.
        created = redis_client.set(f"stripe:evt:{event_id}", "1", nx=True, ex=_EVENT_DEDUP_TTL)
        return created is None
    except Exception:
        return False


def _reverse_beat_sale_credit(purchase: Purchase, reason: str) -> None:
    """
    Annule le crédit wallet lié à un achat remboursé / contesté.

    Verrouille le wallet (SELECT … FOR UPDATE) pour éviter toute course avec un
    retrait concurrent, puis retire le montant du solde correspondant si le crédit
    n'a pas encore été retiré :
      • crédit 'pending'   → déduit de balance_pending
      • crédit 'available' → déduit de balance_available
      • crédit 'transferred'/'expired' → fonds déjà partis : impossible de clawback
        automatiquement, on loggue en CRITICAL pour traitement manuel.
    Le crédit est marqué 'refunded' (la contrainte amount>0 interdit une txn négative,
    on neutralise donc la transaction existante plutôt que d'en créer une inverse).
    """
    from sqlalchemy import select

    credits = db.session.execute(
        select(WalletTransaction).where(
            WalletTransaction.purchase_id == purchase.id,
            WalletTransaction.type == 'credit_beat_sale',
            WalletTransaction.status.in_(['pending', 'available', 'transferred', 'expired']),
        )
    ).scalars().all()

    if not credits:
        return

    for txn in credits:
        if txn.status in ('transferred', 'expired'):
            current_app.logger.critical(
                "[STRIPE-WEBHOOK] %s purchase #%s : crédit wallet txn #%s déjà '%s' "
                "(montant %s€) — clawback manuel requis.",
                reason, purchase.id, txn.id, txn.status, txn.amount,
            )
            continue

        # Verrou du wallet avant modification des soldes.
        wallet = db.session.execute(
            select(Wallet).where(Wallet.id == txn.wallet_id).with_for_update()
        ).scalar_one_or_none()
        if wallet is None:
            continue

        amount = Decimal(str(txn.amount))
        if txn.status == 'pending':
            wallet.balance_pending = max(Decimal('0'), (wallet.balance_pending or Decimal('0')) - amount)
        else:  # available
            wallet.balance_available = max(Decimal('0'), (wallet.balance_available or Decimal('0')) - amount)

        txn.status = 'refunded'
        current_app.logger.info(
            "[STRIPE-WEBHOOK] %s purchase #%s : crédit wallet txn #%s (%s€) annulé.",
            reason, purchase.id, txn.id, amount,
        )


def _purchase_from_charge(charge) -> Purchase | None:
    """Retrouve le Purchase depuis le payment_intent de la charge Stripe."""
    payment_intent_id = charge.get('payment_intent')
    if not payment_intent_id:
        return None
    return db.session.query(Purchase).filter_by(
        stripe_payment_intent_id=payment_intent_id
    ).first()


@stripe_webhook_bp.route('/webhook', methods=['POST'])
@csrf.exempt
@limiter.limit('300 per minute')
def stripe_webhook():
    """Endpoint public appelé par Stripe. Aucune auth applicative : la confiance
    repose entièrement sur la signature HMAC de l'entête Stripe-Signature."""
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    if not webhook_secret:
        current_app.logger.error("[STRIPE-WEBHOOK] STRIPE_WEBHOOK_SECRET absent — webhook désactivé.")
        return ('', 500)

    # IMPORTANT : lire le corps BRUT (bytes), pas request.json — la signature est
    # calculée sur les octets exacts du payload.
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        current_app.logger.warning("[STRIPE-WEBHOOK] Payload invalide.")
        return ('', 400)
    except stripe.SignatureVerificationError:
        current_app.logger.warning("[STRIPE-WEBHOOK] Signature invalide.")
        return ('', 400)

    event_id   = event.get('id', '')
    event_type = event.get('type', '')

    # Idempotence : ne pas re-traiter un event déjà vu (Stripe re-livre en cas de
    # timeout / 5xx).
    if event_id and _already_processed(event_id):
        return ('', 200)

    obj = event.get('data', {}).get('object', {})

    try:
        if event_type == 'charge.refunded':
            purchase = _purchase_from_charge(obj)
            if purchase:
                purchase.license_status = 'cancelled'
                _reverse_beat_sale_credit(purchase, 'refund')
                db.session.commit()
                current_app.logger.info("[STRIPE-WEBHOOK] charge.refunded traité purchase #%s.", purchase.id)

        elif event_type == 'charge.dispute.created':
            charge_id = obj.get('charge')
            purchase = None
            if charge_id:
                try:
                    charge = stripe.Charge.retrieve(charge_id)
                    purchase = _purchase_from_charge(charge)
                except stripe.StripeError as e:
                    current_app.logger.error("[STRIPE-WEBHOOK] retrieve charge litige échoué: %s", e)
            if purchase:
                purchase.license_status = 'cancelled'
                _reverse_beat_sale_credit(purchase, 'dispute')
                db.session.commit()
                current_app.logger.warning("[STRIPE-WEBHOOK] litige ouvert purchase #%s — licence gelée.", purchase.id)

        elif event_type == 'account.updated':
            from stripe_connect_helpers import handle_webhook_account_updated
            account_id = obj.get('id')
            if account_id:
                handle_webhook_account_updated(account_id)

        else:
            # Event non géré : accusé de réception pour éviter les re-livraisons.
            current_app.logger.debug("[STRIPE-WEBHOOK] event non géré: %s", event_type)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error("[STRIPE-WEBHOOK] erreur traitement %s: %s", event_type, e, exc_info=True)
        # 500 → Stripe re-livrera l'event (l'idempotence Redis a expiré ou n'a pas
        # été posée en cas de crash avant commit).
        return ('', 500)

    return ('', 200)
