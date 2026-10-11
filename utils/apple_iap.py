"""
Achats intégrés Apple (StoreKit 2) — vérification des transactions et crédit
de l'abonnement LaProd+ acheté dans l'app iOS.

Pourquoi ce module existe : Apple refuse en review (guideline 3.1.1) toute app
iOS qui vend un contenu ou une fonctionnalité numérique autrement que par son
achat intégré — y compris en renvoyant vers le site. Sur iOS, LaProd+ passe
donc par l'App Store ; le web et Android restent sur Stripe (routes/premium_api).

Le produit App Store est un « abonnement sans renouvellement automatique » de
30 jours : c'est l'exact équivalent du paiement unique Stripe (mode='payment',
PREMIUM_DURATION_DAYS). Conséquences qui simplifient tout :
  - pas de renouvellement à suivre, donc pas de clé d'API App Store Server ;
  - la seule chose à faire est de VÉRIFIER la signature de la transaction que
    l'app nous présente, puis de créditer 30 jours, une seule fois.

Trois responsabilités, séparées comme dans le reste de `utils/` :
1. Vérifier une transaction signée (JWS) contre les certificats racine d'Apple.
   L'app n'est jamais crue sur parole : elle ne transmet qu'une chaîne opaque.
2. Créditer / reprendre les jours d'abonnement (idempotent par transaction).
3. Exposer la politique d'achat de l'app iOS, catégorie par catégorie.

Utilisé par routes/apple_iap_api.py.
"""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from flask import current_app

from extensions import db
from utils import plans
from utils.money import to_money

_CERTS_DIR = Path(__file__).parent / 'apple_certs'

# Espace de noms fixe : le jeton de compte d'un utilisateur doit être le même à
# chaque appel, sur chaque serveur. Ne jamais le changer — les transactions déjà
# émises portent des jetons dérivés de cette valeur.
_ACCOUNT_TOKEN_NAMESPACE = uuid.UUID('6f1d2c7e-3a54-4b0e-9c61-2d7a5e8b4f10')

POLICY_IAP = 'iap'
POLICY_STRIPE = 'stripe'
POLICY_UNAVAILABLE = 'unavailable'


class AppleIapError(Exception):
    """Transaction refusée. `message` est affichable tel quel (R14), `code` est
    stable pour le front."""

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


# ── Configuration ────────────────────────────────────────────────────────────

def product_ids() -> dict:
    """Palier → identifiant de produit App Store."""
    cfg = current_app.config
    return {
        plans.PREMIUM:       cfg.get('APPLE_IAP_PRODUCT_PREMIUM'),
        plans.SEMI_PRO:      cfg.get('APPLE_IAP_PRODUCT_SEMI_PRO'),
        plans.PRO_STRUCTURE: cfg.get('APPLE_IAP_PRODUCT_PRO_STRUCTURE'),
    }


def plan_for_product(product_id: str):
    for plan, pid in product_ids().items():
        if pid and pid == product_id:
            return plan
    return None


def _app_apple_id():
    raw = current_app.config.get('APPLE_APP_ID')
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def is_configured() -> bool:
    """L'achat intégré est-il vendable ? Tout ou rien : un réglage partiel
    désactive l'achat (l'app affiche « indisponible ») plutôt que de laisser un
    client payer Apple pour un abonnement qu'on ne saurait pas créditer."""
    return (
        bool(current_app.config.get('APPLE_BUNDLE_ID'))
        and _app_apple_id() is not None
        and all(product_ids().values())
    )


def account_token_for(user_id: int) -> str:
    """UUID stable dérivé de l'utilisateur, attaché à l'achat par StoreKit
    (appAccountToken) et resigné par Apple dans la transaction. C'est ce qui
    empêche de créditer sur un compte LaProd l'achat fait depuis un autre."""
    return str(uuid.uuid5(_ACCOUNT_TOKEN_NAMESPACE, f'laprod-user-{int(user_id)}'))


def ios_purchase_policy() -> dict:
    """Ce que l'app iOS a le droit de proposer, par catégorie d'achat.

      subscription    LaProd+ : achat intégré Apple, ou rien. JAMAIS Stripe.
      beat_license    Licence d'un beat (contrat + fichiers exploités hors de l'app).
      mix_order       Prestation de mix/master réalisée par un ingénieur.
      campaign_boost  Option payante d'une campagne de mailing.

    Une valeur inconnue dans l'environnement retombe sur 'unavailable' : une
    faute de frappe ne doit jamais ouvrir un paiement qu'Apple refuserait."""
    cfg = current_app.config

    def _pick(key, allowed):
        value = (cfg.get(key) or '').strip().lower()
        return value if value in allowed else POLICY_UNAVAILABLE

    subscription = _pick('IOS_POLICY_SUBSCRIPTION', (POLICY_IAP, POLICY_UNAVAILABLE))
    if subscription == POLICY_IAP and not is_configured():
        subscription = POLICY_UNAVAILABLE

    stripe_or_nothing = (POLICY_STRIPE, POLICY_UNAVAILABLE)
    return {
        'subscription':   subscription,
        'beat_license':   _pick('IOS_POLICY_BEAT_LICENSE', stripe_or_nothing),
        'mix_order':      _pick('IOS_POLICY_MIX_ORDER', stripe_or_nothing),
        'campaign_boost': _pick('IOS_POLICY_CAMPAIGN_BOOST', stripe_or_nothing),
    }


# ── Vérification ─────────────────────────────────────────────────────────────

def _root_certificates() -> list:
    return [p.read_bytes() for p in sorted(_CERTS_DIR.glob('*.cer'))]


def _verifiers() -> list:
    """Vérificateurs à essayer, dans l'ordre. Production d'abord, puis Sandbox :
    une même app en ligne reçoit des achats réels ET des achats de test
    (TestFlight, et surtout l'équipe de review d'Apple, qui achète en Sandbox)."""
    from appstoreserverlibrary.models.Environment import Environment
    from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier

    bundle_id = current_app.config.get('APPLE_BUNDLE_ID')
    roots = _root_certificates()
    # Contrôle de révocation en ligne (OCSP) coupé : il ajoute un appel réseau
    # bloquant à chaque achat, et une panne côté Apple ferait échouer un paiement
    # déjà encaissé. La chaîne de certificats reste intégralement vérifiée.
    verifiers = [
        SignedDataVerifier(roots, False, Environment.PRODUCTION, bundle_id, _app_apple_id()),
        SignedDataVerifier(roots, False, Environment.SANDBOX, bundle_id, _app_apple_id()),
    ]
    if current_app.config.get('APPLE_IAP_ALLOW_XCODE'):
        verifiers.append(
            SignedDataVerifier(roots, False, Environment.XCODE, bundle_id, _app_apple_id()))
    return verifiers


def _verify(signed: str, method: str):
    """Essaie chaque environnement ; ne passe au suivant que si Apple dit
    « mauvais environnement ». Toute autre erreur est un refus définitif."""
    from appstoreserverlibrary.signed_data_verifier import (
        VerificationException, VerificationStatus,
    )

    if not is_configured():
        raise AppleIapError(
            "Les abonnements ne sont pas disponibles dans l'application pour le moment.",
            code='IAP_NOT_CONFIGURED')

    last = None
    for verifier in _verifiers():
        try:
            return getattr(verifier, method)(signed)
        except VerificationException as exc:
            last = exc
            if exc.status == VerificationStatus.INVALID_ENVIRONMENT:
                continue
            break
        except Exception as exc:  # JWS illisible, tronqué, mal formé…
            last = exc
            break

    current_app.logger.warning("[APPLE-IAP] %s refusé : %r", method, last)
    raise AppleIapError(
        "Nous n'avons pas pu valider cet achat auprès d'Apple. Si tu as été débité, "
        "utilise « Restaurer mes achats » ou contacte le support.",
        code='IAP_INVALID_TRANSACTION')


def verify_transaction(signed_transaction: str):
    """Transaction signée → payload décodé et authentifié (bundle ID vérifié)."""
    return _verify(signed_transaction, 'verify_and_decode_signed_transaction')


def verify_notification(signed_payload: str):
    """Notification serveur App Store (V2) → payload décodé et authentifié."""
    return _verify(signed_payload, 'verify_and_decode_notification')


# ── Crédit / reprise ─────────────────────────────────────────────────────────

def _from_ms(ms) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000) if ms else datetime.now()


def _environment_label(tx) -> str:
    return getattr(tx, 'rawEnvironment', None) or 'Production'


def credit_transaction(user, tx):
    """Crédite l'abonnement correspondant à une transaction VÉRIFIÉE.

    Renvoie (ligne AppleIapTransaction, credited: bool). credited=False quand la
    transaction était déjà connue pour ce compte : StoreKit représente les mêmes
    transactions à chaque lancement et à chaque restauration, ce n'est pas une
    erreur. L'appelant commit.
    """
    from models import AppleIapTransaction

    transaction_id = getattr(tx, 'transactionId', None)
    plan = plan_for_product(getattr(tx, 'productId', None) or '')
    if not transaction_id or plan is None:
        current_app.logger.error(
            "[APPLE-IAP] produit inconnu ou transaction sans identifiant : product=%r tx=%r",
            getattr(tx, 'productId', None), transaction_id)
        raise AppleIapError(
            "Cet achat ne correspond à aucun abonnement LaProd+. Contacte le support.",
            code='IAP_UNKNOWN_PRODUCT')

    token = getattr(tx, 'appAccountToken', None)
    if token and str(token).lower() != account_token_for(user.id):
        raise AppleIapError(
            "Cet achat a été effectué depuis un autre compte LaProd. Connecte-toi "
            "avec ce compte pour le retrouver.",
            code='IAP_OTHER_ACCOUNT')

    # Verrou de ligne sur l'utilisateur : purchase() et l'écouteur de transactions
    # de StoreKit envoient souvent la MÊME transaction en parallèle. Sans verrou,
    # les deux requêtes ne voient aucune ligne et créditent chacune 30 jours.
    from models import User
    db.session.execute(
        db.select(User.id).where(User.id == user.id).with_for_update())

    existing = AppleIapTransaction.query.filter_by(transaction_id=transaction_id).first()
    if existing is not None:
        if existing.user_id != user.id:
            raise AppleIapError(
                "Cet achat est déjà rattaché à un autre compte LaProd.",
                code='IAP_OTHER_ACCOUNT')
        return existing, False

    if getattr(tx, 'revocationDate', None):
        raise AppleIapError(
            "Cet achat a été remboursé par Apple : il ne peut plus être activé.",
            code='IAP_REVOKED')

    duration_days = int(current_app.config.get('PREMIUM_DURATION_DAYS', 30))
    purchased_at = _from_ms(getattr(tx, 'purchaseDate', None))

    # Apple exprime le prix en millièmes d'unité monétaire.
    price = None
    if getattr(tx, 'price', None) is not None:
        price = to_money(Decimal(int(tx.price)) / Decimal('1000'))

    row = AppleIapTransaction(
        transaction_id=transaction_id,
        user_id=user.id,
        product_id=tx.productId,
        plan=plan,
        duration_days=duration_days,
        environment=_environment_label(tx),
        price=price,
        currency=getattr(tx, 'currency', None),
        purchased_at=purchased_at,
    )
    db.session.add(row)

    # Même règle que l'activation Stripe : un abonnement encore actif est
    # PROLONGÉ, jamais écrasé — on ne reprend pas des jours déjà payés.
    now = datetime.now()
    if user.is_premium_active and user.premium_expires_at:
        user.premium_expires_at = user.premium_expires_at + timedelta(days=duration_days)
    else:
        user.premium_since = now
        user.premium_expires_at = now + timedelta(days=duration_days)

    user.subscription_plan = plan
    user.premium_source = 'apple'
    user.premium_price_paid = price if price is not None else plans.price_of(plan)
    user.apply_premium_tokens()
    return row, True


def revoke_transaction(transaction_id: str):
    """Remboursement / révocation notifiés par Apple : reprend les jours crédités.

    Renvoie l'utilisateur concerné, ou None si la transaction nous est inconnue
    ou déjà reprise (Apple renvoie ses notifications jusqu'à obtenir un 200 :
    le traitement doit pouvoir être rejoué sans effet). L'appelant commit.
    """
    from models import AppleIapTransaction

    row = AppleIapTransaction.query.filter_by(transaction_id=transaction_id).first()
    if row is None or row.revoked_at is not None:
        return None

    now = datetime.now()
    row.revoked_at = now
    user = row.user
    if user is None or not user.premium_expires_at:
        return user

    user.premium_expires_at = user.premium_expires_at - timedelta(days=row.duration_days)
    if user.premium_expires_at <= now:
        user.subscription_plan = plans.FREE
        user.premium_expires_at = None
        user.premium_source = None
    return user
