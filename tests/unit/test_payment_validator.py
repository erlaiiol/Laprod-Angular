"""
Tests unitaires — utils/payment_validator.py

MixMasterRequestPriceCalculator et PriceCalculator.validate_price sont purs
(pas de current_app) → testables sans contexte Flask.

TrackPriceCalculator.calculate_options_price utilise current_app.config
→ testé dans le contexte de l'app fixture.
"""

from decimal import Decimal
from unittest.mock import MagicMock
import pytest


# ── PriceCalculator.validate_price (méthode parente, logique pure) ─────────────

class TestValidatePrice:

    @pytest.fixture(autouse=True)
    def calculator(self):
        from utils.payment_validator import MixMasterRequestPriceCalculator
        self.calc = MixMasterRequestPriceCalculator()

    def test_accepts_price_within_range(self):
        assert self.calc.validate_price(50.0) is True

    def test_accepts_minimum_price(self):
        assert self.calc.validate_price(1.0) is True

    def test_accepts_maximum_price(self):
        assert self.calc.validate_price(10000.0) is True

    def test_rejects_price_below_minimum(self):
        assert self.calc.validate_price(0.99) is False

    def test_rejects_zero_price(self):
        assert self.calc.validate_price(0.0) is False

    def test_rejects_negative_price(self):
        assert self.calc.validate_price(-5.0) is False

    def test_rejects_price_above_maximum(self):
        assert self.calc.validate_price(10000.01) is False

    def test_custom_min_max(self):
        assert self.calc.validate_price(25.0, min_price=20.0, max_price=30.0) is True
        assert self.calc.validate_price(19.99, min_price=20.0, max_price=30.0) is False
        assert self.calc.validate_price(30.01, min_price=20.0, max_price=30.0) is False


# ── MixMasterRequestPriceCalculator ───────────────────────────────────────────

class TestMixMasterRequestPriceCalculator:

    @pytest.fixture(autouse=True)
    def calculator(self):
        from utils.payment_validator import MixMasterRequestPriceCalculator
        self.calc = MixMasterRequestPriceCalculator()

    def _make_engineer(self, ref_price=100.0, price_min=0.0):
        e = MagicMock()
        e.mixmaster_reference_price = ref_price
        e.mixmaster_price_min = price_min
        return e

    # -- calculate_base_price --

    def test_single_service_cleaning(self):
        engineer = self._make_engineer(ref_price=100.0)
        price = self.calc.calculate_base_price(engineer, service_cleaning=True)
        assert price == 35.0  # 100 * 0.35

    def test_single_service_effects(self):
        engineer = self._make_engineer(ref_price=100.0)
        price = self.calc.calculate_base_price(engineer, service_effects=True)
        assert price == 45.0  # 100 * 0.45

    def test_single_service_artistic(self):
        engineer = self._make_engineer(ref_price=100.0)
        price = self.calc.calculate_base_price(engineer, service_artistic=True)
        assert price == 60.0  # 100 * 0.60

    def test_single_service_mastering(self):
        engineer = self._make_engineer(ref_price=100.0)
        price = self.calc.calculate_base_price(engineer, service_mastering=True)
        assert price == 20.0  # 100 * 0.20

    def test_all_services_combined(self):
        engineer = self._make_engineer(ref_price=100.0)
        price = self.calc.calculate_base_price(
            engineer,
            service_cleaning=True,
            service_effects=True,
            service_artistic=True,
            service_mastering=True,
        )
        # 0.35 + 0.45 + 0.60 + 0.20 = 1.60 → 160€
        assert price == 160.0

    def test_no_service_raises_value_error(self):
        engineer = self._make_engineer()
        with pytest.raises(ValueError, match="Aucun service"):
            self.calc.calculate_base_price(engineer)

    def test_custom_reference_price(self):
        engineer = self._make_engineer(ref_price=200.0)
        price = self.calc.calculate_base_price(engineer, service_cleaning=True)
        assert price == 70.0  # 200 * 0.35

    # -- calculate_options_price --

    def test_stems_bonus_20_percent(self):
        options = {'has_separated_stems': True, 'reference_price': 100.0}
        bonus = self.calc.calculate_options_price(options)
        assert bonus == 20.0  # 100 * 0.20

    def test_no_stems_no_bonus(self):
        options = {'has_separated_stems': False, 'reference_price': 100.0}
        bonus = self.calc.calculate_options_price(options)
        assert bonus == 0.0

    def test_stems_bonus_rounds_to_2_decimals(self):
        options = {'has_separated_stems': True, 'reference_price': 333.0}
        bonus = self.calc.calculate_options_price(options)
        assert bonus == round(333.0 * 0.20, 2)

    # -- calculate_total --

    def test_minimum_price_applied(self):
        """Si le total calculé est inférieur au prix minimum, le minimum s'applique."""
        engineer = self._make_engineer(ref_price=50.0, price_min=40.0)
        # cleaning seul: 50 * 0.35 = 17.5 → en dessous du minimum de 40
        _base, _opts, total = self.calc.calculate_total(
            engineer, {}, service_cleaning=True
        )
        assert total == 40.0

    def test_total_above_minimum_not_capped(self):
        engineer = self._make_engineer(ref_price=200.0, price_min=40.0)
        _base, _opts, total = self.calc.calculate_total(
            engineer, {}, service_cleaning=True, service_effects=True
        )
        # 200 * (0.35 + 0.45) = 160 → supérieur au minimum
        assert total == 160.0

    def test_total_with_stems_bonus(self):
        engineer = self._make_engineer(ref_price=100.0, price_min=0.0)
        _base, _opts, total = self.calc.calculate_total(
            engineer,
            {'has_separated_stems': True},
            service_mastering=True,
        )
        # base: 100 * 0.20 = 20, stems: 100 * 0.20 = 20, total: 40
        assert total == 40.0


# ── TrackPriceCalculator (nécessite un contexte Flask) ────────────────────────

class TestTrackPriceCalculator:

    def test_price_by_format(self, app):
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()

        track = MagicMock()
        track.price_mp3 = 9.99
        track.price_wav = 19.99
        track.price_stems = 39.99

        with app.app_context():
            assert calc.calculate_base_price(track, format_type='mp3') == 9.99
            assert calc.calculate_base_price(track, format_type='wav') == 19.99
            assert calc.calculate_base_price(track, format_type='stems') == 39.99

    def test_invalid_format_raises(self, app):
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()
        track = MagicMock()
        track.price_mp3 = 9.99
        track.price_wav = None
        track.price_stems = None

        with app.app_context():
            with pytest.raises(ValueError):
                calc.calculate_base_price(track, format_type='flac')

    def test_exclusive_adds_to_options_price(self, app):
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()

        with app.app_context():
            options = {'is_exclusive': True, 'duration_years': 3, 'territory': 'France'}
            price = calc.calculate_options_price(options)
            assert price >= 150.0  # CONTRACT_EXCLUSIVE_PRICE = 150 dans test_config

    def test_france_territory_no_extra_cost(self, app):
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()

        with app.app_context():
            options_france = {'is_exclusive': False, 'duration_years': 3, 'territory': 'France'}
            options_world = {'is_exclusive': False, 'duration_years': 3, 'territory': 'Monde entier'}
            price_france = calc.calculate_options_price(options_france)
            price_world = calc.calculate_options_price(options_world)
            assert price_world > price_france
