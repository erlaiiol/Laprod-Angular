"""
utils/promo_service.py — Résolution et application des codes promo
=================================================================

Point d'entrée UNIQUE pour tout ce qui touche à l'application d'un code promo.
Les routes de paiement ET l'endpoint d'aperçu (« combien ça me coûterait ? »)
passent par les mêmes fonctions : le prix annoncé à l'acheteur et le prix
encaissé par Stripe sont calculés par le même code, ils ne peuvent pas diverger.

Le code promo n'est JAMAIS de confiance côté client : on ne reçoit qu'une chaîne
de caractères. Le pourcentage, le périmètre et la remise sont toujours relus en
base et recalculés côté serveur.
"""
from decimal import Decimal

from extensions import db
from models import PromoCode, PromoCodeScope, PromoCodeRedemption
from utils.money import to_money, compute_discount, apply_discount, is_chargeable

# Part du prix de référence de l'ingénieur imputable à chaque prestation.
# Doit rester aligné sur MixMasterRequest.calculate_service_price().
MIXMASTER_SERVICE_WEIGHTS = {
    'cleaning':  Decimal('0.35'),
    'effects':   Decimal('0.45'),
    'artistic':  Decimal('0.60'),
    'mastering': Decimal('0.20'),
    'stems':     Decimal('0.20'),
}

ERROR_MESSAGES = {
    'PROMO_NOT_FOUND':     "Ce code promo n'existe pas.",
    'PROMO_INACTIVE':      "Ce code promo a été désactivé.",
    'PROMO_EXPIRED':       "Ce code promo a expiré.",
    'PROMO_EXHAUSTED':     "Ce code promo a atteint son nombre maximum d'utilisations.",
    'PROMO_ALREADY_USED':  "Vous avez déjà utilisé ce code promo.",
    'PROMO_OWN_CODE':      "Vous ne pouvez pas utiliser votre propre code promo.",
    'PROMO_NOT_APPLICABLE': "Ce code promo ne s'applique pas à cette commande.",
    'PROMO_AMOUNT_TOO_LOW': "Le montant après remise est trop faible pour être encaissé (minimum 0,50 €).",
}


class PromoError(Exception):
    """Refus d'application d'un code promo, porteur d'un code d'erreur stable."""

    def __init__(self, code):
        self.code = code
        self.message = ERROR_MESSAGES.get(code, "Code promo invalide.")
        super().__init__(self.message)


def resolve(code_str, owner_id, scope):
    """Retrouve le code d'un vendeur donné. Lève PromoError si introuvable.

    La résolution est TOUJOURS bornée au vendeur (owner_id) : c'est ce qui rend
    l'unicité par vendeur sûre. Deux vendeurs peuvent avoir « SUMMER30 », on ne
    peut jamais appliquer par erreur celui du voisin puisqu'on part du beat ou
    de l'ingénieur ciblé.
    """
    normalized = PromoCode.normalize_code(code_str)
    if not normalized:
        raise PromoError('PROMO_NOT_FOUND')

    promo = PromoCode.query.filter_by(
        owner_id=owner_id, code=normalized, scope=scope,
    ).first()
    if not promo:
        raise PromoError('PROMO_NOT_FOUND')
    return promo


def _guard_usable(promo, buyer_id):
    usable, error_code = promo.check_usable_by(buyer_id)
    if not usable:
        raise PromoError(error_code)


def _finalize(promo, gross, discount):
    """Clamp, vérifie l'encaissabilité, renvoie le détail de la remise."""
    gross_d = to_money(gross)
    discount = to_money(min(to_money(discount), gross_d))
    net = to_money(gross_d - discount)

    # Une remise de 70 % sur un beat à 1 € donnerait 0,30 € : Stripe refuse tout
    # paiement sous 0,50 €. Mieux vaut refuser le code avec un message clair que
    # de laisser l'acheteur se prendre une erreur Stripe opaque au checkout.
    if not is_chargeable(net):
        raise PromoError('PROMO_AMOUNT_TOO_LOW')

    return {
        'promo':    promo,
        'code':     promo.code,
        'percent':  promo.percent,
        'gross':    gross_d,
        'discount': discount,
        'net':      net,
    }


def apply_to_track(code_str, track, buyer_id, gross_total):
    """Applique un code promo à un achat de beat.

    La remise porte sur le TOTAL (beat + contrat) : les deux reviennent au
    vendeur à 90 %, la remise est donc financée sur sa part quelle que soit la
    ventilation interne.
    """
    promo = resolve(code_str, track.composer_id, PromoCodeScope.TRACK.value)
    _guard_usable(promo, buyer_id)

    if not promo.covers_track(track.id):
        raise PromoError('PROMO_NOT_APPLICABLE')

    discount = compute_discount(gross_total, promo.percent)
    return _finalize(promo, gross_total, discount)


def apply_to_mixmaster(code_str, engineer, buyer_id, gross_total, selected_services):
    """Applique un code promo à une commande mix/master.

    `selected_services` : itérable de clés parmi MIXMASTER_SERVICE_WEIGHTS.

    La remise ne porte que sur la part de prix imputable aux prestations
    couvertes ET commandées. Un code « -30 % sur le mastering » sur une commande
    nettoyage + mastering ne remise que la ligne mastering : l'ingénieur solde
    ce qu'il a choisi de solder, pas le reste de sa prestation.
    """
    promo = resolve(code_str, engineer.id, PromoCodeScope.MIXMASTER.value)
    _guard_usable(promo, buyer_id)

    covered = [k for k in selected_services if promo.covers_service(k)]
    if not covered:
        raise PromoError('PROMO_NOT_APPLICABLE')

    reference = to_money(engineer.mixmaster_reference_price or 100)
    gross_d = to_money(gross_total)

    if promo.applies_to_all:
        # Toutes les prestations sont couvertes : on remise le total encaissé
        # directement, ce qui absorbe aussi le plancher mixmaster_price_min.
        discount = compute_discount(gross_d, promo.percent)
    else:
        covered_base = sum(
            (to_money(reference * MIXMASTER_SERVICE_WEIGHTS[k]) for k in covered),
            Decimal('0'),
        )
        # Le total facturé peut être relevé au plancher mixmaster_price_min : la
        # part couverte ne peut alors pas dépasser ce qui est réellement payé.
        covered_base = min(to_money(covered_base), gross_d)
        discount = compute_discount(covered_base, promo.percent)

    return _finalize(promo, gross_d, discount)


def preview_or_none(applier, *args, **kwargs):
    """Exécute un applier et renvoie (résultat, None) ou (None, PromoError)."""
    try:
        return applier(*args, **kwargs), None
    except PromoError as e:
        return None, e


def consume(promo, buyer_id, gross, discount, net, purchase=None, mixmaster_request=None):
    """Enregistre l'utilisation d'un code après un paiement réussi.

    Renvoie True si le quota a bien été décrémenté. Renvoie False si le code
    était épuisé entre le checkout et l'encaissement (course très étroite) :
    dans ce cas la remise est tout de même honorée — l'acheteur a déjà payé le
    montant remisé chez Stripe, on ne peut pas revenir dessus — mais l'appelant
    doit le journaliser. On trace la redemption dans tous les cas, pour que la
    comptabilité reflète l'argent réellement encaissé.

    Ne commit pas : l'appelant intègre l'opération à la transaction du paiement.
    """
    consumed = promo.try_consume(buyer_id)

    db.session.add(PromoCodeRedemption(
        promo_code_id=promo.id,
        user_id=buyer_id,
        purchase_id=purchase.id if purchase else None,
        mixmaster_request_id=mixmaster_request.id if mixmaster_request else None,
        gross_amount=to_money(gross),
        discount_amount=to_money(discount),
        net_amount=to_money(net),
        percent_applied=promo.percent,
    ))
    return consumed
