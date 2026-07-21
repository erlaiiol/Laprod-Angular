"""
Tests de l'arithmétique monétaire (utils/money.py).

Ces tests protègent des invariants qui se paient en euros s'ils cassent :
un centime perdu à chaque vente, c'est une réconciliation Stripe fausse.
"""
from decimal import Decimal

import pytest

from utils.money import (
    from_cents,
    to_money, to_cents, compute_discount, apply_discount,
    split_platform_fee, is_chargeable, ALLOWED_DISCOUNT_PERCENTS,
    STRIPE_MIN_CHARGE_EUR,
)


class TestToMoney:
    def test_quantize_deux_decimales(self):
        assert to_money('10.005') == Decimal('10.01')   # ROUND_HALF_UP, pas HALF_EVEN
        assert to_money('10.004') == Decimal('10.00')

    def test_arrondi_commercial_pas_bancaire(self):
        # ROUND_HALF_EVEN (défaut Python) donnerait 2.02 : on veut 2.03.
        assert to_money('2.025') == Decimal('2.03')

    def test_float_ne_derive_pas(self):
        # Decimal(0.1) == 0.1000000000000000055... ; le passage par str() l'évite.
        assert to_money(0.1) == Decimal('0.10')

    def test_none_vaut_zero(self):
        assert to_money(None) == Decimal('0.00')


class TestToCents:
    def test_conversion_exacte(self):
        assert to_cents('70.00') == 7000
        assert to_cents('0.30') == 30

    @pytest.mark.parametrize('amount, expected', [
        ('0.29', 29), ('19.99', 1999), ('0.07', 7), ('1.10', 110),
    ])
    def test_pas_de_troncature(self, amount, expected):
        # int(0.29 * 100) vaut 28 en float : to_cents ne doit jamais tronquer.
        assert to_cents(amount) == expected


class TestApplyDiscount:
    @pytest.mark.parametrize('percent', ALLOWED_DISCOUNT_PERCENTS)
    def test_remise_plus_net_egale_toujours_le_brut(self, percent):
        # L'invariant central : si remise + net != brut, Stripe encaisse un montant
        # qui ne correspond plus à la répartition enregistrée en base.
        for gross in ['0.99', '19.99', '33.33', '100.00', '149.95', '1234.56']:
            discount, net = apply_discount(gross, percent)
            assert discount + net == Decimal(gross), (gross, percent)

    def test_valeurs_connues(self):
        assert apply_discount('100.00', 30) == (Decimal('30.00'), Decimal('70.00'))
        assert apply_discount('19.99', 70)  == (Decimal('13.99'), Decimal('6.00'))

    def test_pourcentage_hors_bareme_ne_remise_rien(self):
        # Défense en profondeur : une valeur forgée (99 %, négative) ne doit jamais
        # produire une remise, même si la validation amont était contournée.
        for bad in (99, 15, -10, 0, 100):
            discount, net = apply_discount('100.00', bad)
            assert discount == Decimal('0.00')
            assert net == Decimal('100.00')

    def test_net_jamais_negatif(self):
        discount, net = apply_discount('0.00', 70)
        assert net >= 0 and discount >= 0


class TestSplitPlatformFee:
    def test_commission_sur_le_montant_encaisse(self):
        # 10 % du NET (70 €), pas du prix catalogue : la remise du vendeur n'est
        # pas taxée, et LaProd ne prélève pas sur de l'argent que personne n'a payé.
        fee, seller = split_platform_fee('70.00')
        assert fee == Decimal('7.00')
        assert seller == Decimal('63.00')

    @pytest.mark.parametrize('total', ['0.50', '6.00', '19.99', '33.33', '100.00', '999.99'])
    def test_fee_plus_revenu_egale_le_total(self, total):
        fee, seller = split_platform_fee(total)
        assert fee + seller == Decimal(total)

    def test_chaine_complete_remise_puis_commission(self):
        # Scénario réel : beat 100 € avec un code -30 %.
        discount, net = apply_discount('100.00', 30)
        fee, seller = split_platform_fee(net)
        assert (discount, net, fee, seller) == (
            Decimal('30.00'), Decimal('70.00'), Decimal('7.00'), Decimal('63.00'),
        )
        assert fee + seller == net


class TestIsChargeable:
    def test_seuil_stripe(self):
        assert is_chargeable('0.50') is True
        assert is_chargeable('0.49') is False

    def test_grosse_remise_sur_petit_prix_devient_non_encaissable(self):
        # 0,99 € avec -70 % => 0,30 €, sous le minimum Stripe de 0,50 €.
        _discount, net = apply_discount('0.99', 70)
        assert net == Decimal('0.30')
        assert net < STRIPE_MIN_CHARGE_EUR
        assert is_chargeable(net) is False


class TestFromCents:
    """from_cents est le pendant obligatoire de to_cents. Son absence est ce qui
    faisait réapparaître des `amount / 100` flottants dans les routes Stripe."""

    def test_conversion_exacte(self):
        assert from_cents(1999) == Decimal('19.99')
        assert from_cents(7000) == Decimal('70.00')
        assert from_cents(0)    == Decimal('0.00')

    @pytest.mark.parametrize('cents', [1, 29, 115, 1999, 2995, 123456])
    def test_aller_retour_sans_perte(self, cents):
        assert to_cents(from_cents(cents)) == cents

    def test_pas_de_division_flottante(self):
        # 1999 / 100 vaut 19.990000000000002 en float : from_cents doit donner
        # exactement 19.99, sinon le montant enregistré diverge de l'encaissé.
        assert from_cents(1999) == Decimal('19.99')
        assert str(from_cents(1999)) == '19.99'
