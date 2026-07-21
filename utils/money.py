"""
utils/money.py — Arithmétique monétaire standardisée (LaProd)
============================================================

Source unique de vérité pour tout calcul portant sur de l'argent : remises,
commissions, conversion en centimes Stripe.

Règles non négociables :
  1. Jamais de float. Tout montant est un Decimal quantizé à 2 décimales.
  2. Un seul mode d'arrondi : ROUND_HALF_UP (arrondi commercial français).
     ROUND_HALF_EVEN (le défaut de Python) répartit les .005 vers le pair et
     produit des écarts d'un centime avec ce qu'affiche le front.
  3. `remise + net == brut` est une identité EXACTE, garantie par construction :
     on quantize la remise puis on soustrait (au lieu de quantizer les deux).
     Sans ça, 2 arrondis indépendants dérivent d'un centime et Stripe encaisse
     un montant qui ne correspond plus à la répartition enregistrée en base.
  4. La conversion en centimes passe par to_cents() : `int(x * 100)` sur un
     float tronque (int(0.29 * 100) == 28), sur un Decimal non quantizé aussi.
"""
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal('0.01')

# Montant minimum encaissable par Stripe en EUR (limite API : 0,50 €).
# Une remise ne doit jamais faire passer une commande sous ce seuil.
STRIPE_MIN_CHARGE_EUR = Decimal('0.50')

# Barème fermé des remises. Une liste blanche, pas un intervalle : un pourcentage
# arbitraire (99 %, -10 %…) forgé côté client ne doit pas pouvoir atteindre le calcul.
ALLOWED_DISCOUNT_PERCENTS = (10, 20, 30, 50, 70)


def to_money(value) -> Decimal:
    """Normalise n'importe quel montant en Decimal à 2 décimales (ROUND_HALF_UP).

    Accepte int, float, str, Decimal. Le passage par str() est volontaire :
    Decimal(0.1) vaut 0.1000000000000000055511151231257827, Decimal('0.1') non.
    """
    if isinstance(value, Decimal):
        d = value
    else:
        d = Decimal(str(value if value is not None else 0))
    return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_cents(value) -> int:
    """Convertit un montant en centimes entiers pour Stripe (unit_amount)."""
    return int(to_money(value) * 100)


def from_cents(cents) -> Decimal:
    """Convertit des centimes Stripe (entier) en montant Decimal.

    Le pendant obligatoire de to_cents(). Son absence est un piège : sans elle on
    écrit `amount_total / 100`, une division FLOTTANTE qui réintroduit exactement
    l'imprécision que tout ce module sert à éliminer. Toute lecture d'un montant
    renvoyé par Stripe passe par ici.
    """
    return to_money(Decimal(int(cents)) / Decimal('100'))


def compute_discount(gross, percent) -> Decimal:
    """Montant de la remise pour un brut et un pourcentage du barème.

    Renvoie 0 si le pourcentage est hors barème — l'appelant est censé avoir
    validé en amont, mais on ne veut aucun chemin où une valeur inattendue
    produirait une remise silencieusement fausse.
    """
    pct = int(percent)
    if pct not in ALLOWED_DISCOUNT_PERCENTS:
        return Decimal('0.00')
    gross_d = to_money(gross)
    if gross_d <= 0:
        return Decimal('0.00')
    return to_money(gross_d * Decimal(pct) / Decimal('100'))


def apply_discount(gross, percent) -> tuple[Decimal, Decimal]:
    """Applique une remise. Renvoie (montant_remise, montant_net).

    Invariant garanti : remise + net == brut, au centime près, toujours.
    """
    gross_d = to_money(gross)
    discount = compute_discount(gross_d, percent)
    if discount > gross_d:  # défense : ne jamais produire un net négatif
        discount = gross_d
    return discount, to_money(gross_d - discount)


def split_platform_fee(total, commission=Decimal('0.10')) -> tuple[Decimal, Decimal]:
    """Répartit un montant encaissé entre commission plateforme et revenu vendeur.

    `total` est le montant RÉELLEMENT payé (après remise) : la commission de 10 %
    porte sur la transaction, pas sur le prix catalogue. Le vendeur finance donc
    sa remise sur sa propre part, et la commission suit à la baisse.

    Invariant garanti : platform_fee + seller_revenue == total.
    """
    total_d = to_money(total)
    fee = to_money(total_d * to_money(commission))
    return fee, to_money(total_d - fee)


def is_chargeable(amount) -> bool:
    """Le montant peut-il être encaissé par Stripe (>= 0,50 €) ?"""
    return to_money(amount) >= STRIPE_MIN_CHARGE_EUR
