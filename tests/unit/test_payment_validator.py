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
        assert bonus == Decimal('66.60')

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
            assert calc.calculate_base_price(track, format_type='mp3')   == Decimal('9.99')
            assert calc.calculate_base_price(track, format_type='wav')   == Decimal('19.99')
            assert calc.calculate_base_price(track, format_type='stems') == Decimal('39.99')

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

    # ── Tests _resolve : prix track > défaut config ───────────────────────────

    def _track_with_prices(self, **prices):
        t = MagicMock()
        # Tous les champs contract_price_* à None par défaut
        for attr in [
            'contract_price_exclusive', 'contract_price_duration_3y',
            'contract_price_duration_5y', 'contract_price_duration_10y',
            'contract_price_lifetime', 'contract_price_mechanical',
            'contract_price_public_show', 'contract_price_arrangement',
            'contract_price_territory_eu', 'contract_price_territory_world',
        ]:
            setattr(t, attr, None)
        for attr, val in prices.items():
            setattr(t, attr, val)
        return t

    def test_custom_exclusive_price(self, app):
        """track.contract_price_exclusive=500 → total inclut 500, pas 150."""
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()
        track = self._track_with_prices(contract_price_exclusive=500)
        track.price_mp3 = 10

        with app.app_context():
            options = {
                'is_exclusive': True, 'is_lifetime': False,
                'duration_years': 3, 'territory': 'France',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            _base, opts_price, _total = calc.calculate_total(track, options, format_type='mp3')
            assert opts_price >= Decimal('500')

    def test_fallback_to_config_when_null(self, app):
        """track.contract_price_exclusive=None → utilise la config (150)."""
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()
        track = self._track_with_prices()  # tout à None
        track.price_mp3 = 10

        with app.app_context():
            options = {
                'is_exclusive': True, 'is_lifetime': False,
                'duration_years': 3, 'territory': 'France',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            _base, opts_price, _total = calc.calculate_total(track, options, format_type='mp3')
            # CONTRACT_EXCLUSIVE_PRICE = 150 dans test_config
            assert opts_price >= Decimal('150')

    def test_custom_duration_price(self, app):
        """track.contract_price_duration_3y=20 → durée 3 ans coûte 20€."""
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()
        track = self._track_with_prices(contract_price_duration_3y=20)
        track.price_mp3 = 10

        with app.app_context():
            options = {
                'is_exclusive': False, 'is_lifetime': False,
                'duration_years': 3, 'territory': 'France',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            _base, opts_price, _total = calc.calculate_total(track, options, format_type='mp3')
            assert opts_price == Decimal('20')

    def test_custom_territory_world_price(self, app):
        """track.contract_price_territory_world=25 → territoire monde = 25€."""
        from utils.payment_validator import TrackPriceCalculator
        calc = TrackPriceCalculator()
        track = self._track_with_prices(contract_price_territory_world=25)
        track.price_mp3 = 10

        with app.app_context():
            options = {
                'is_exclusive': False, 'is_lifetime': False,
                'duration_years': 3, 'territory': 'Monde entier',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            _base, opts_price, _total = calc.calculate_total(track, options, format_type='mp3')
            # durée 3 ans (config=10) + territoire monde (custom=25) = 35
            assert opts_price == Decimal('35')


# ── TrackPriceCalculator — scénarios presets quick-start ──────────────────────

class TestTrackPriceCalculatorPresets:
    """
    Vérifie que chaque preset quick-start produit le prix attendu côté serveur,
    garantissant que le total_price envoyé par le frontend passe le contrôle
    anti-manipulation de payment_track_api.py.

    Config de test (conftest.py) :
      CONTRACT_DURATIONS  : {'1': 5, '2': 8, '3': 10, 'lifetime': 30}
      CONTRACT_TERRITORY_EUROPE : 5  /  CONTRACT_TERRITORY_WORLD : 10
      CONTRACT_MECHANICAL_REPRODUCTION_PRICE : 30
      CONTRACT_PUBLIC_SHOW_PRICE              : 40
      CONTRACT_ARRANGEMENT_PRICE              : 10
      Seuils : MECHANICAL_THRESHOLD=199.99 / PUBLIC_SHOW_THRESHOLD=74.99
    """

    def _make_track(self, mp3=9.99):
        t = MagicMock()
        t.price_mp3 = mp3
        for attr in [
            'contract_price_exclusive', 'contract_price_duration_3y',
            'contract_price_duration_5y', 'contract_price_duration_10y',
            'contract_price_lifetime', 'contract_price_mechanical',
            'contract_price_public_show', 'contract_price_arrangement',
            'contract_price_territory_eu', 'contract_price_territory_world',
        ]:
            setattr(t, attr, None)
        return t

    def test_preset_starter_equals_base_price_only(self, app):
        """
        Starter : streaming seul (duration_years=0), France, aucun droit.
        Options fee = 0 → total = prix de base uniquement.
        Couvre aussi le fix du bug duration_years=0 (anciennement +5€ par défaut).
        """
        from utils.payment_validator import TrackPriceCalculator
        track = self._make_track(mp3=9.99)

        with app.app_context():
            options = {
                'is_exclusive': False, 'is_lifetime': False,
                'duration_years': 0,   'territory': 'France',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            _base, opts_price, total = TrackPriceCalculator().calculate_total(
                track, options, format_type='mp3'
            )
        assert opts_price == Decimal('0'), "Streaming seul ne doit ajouter aucun surcoût"
        assert total == Decimal('9.99')

    def test_preset_standard_includes_duration_territory_and_rights(self, app):
        """
        Standard : 5 ans, Europe, reproduction mécanique + diffusion publique.
        Calcul (test config) :
          duration_years=5 → CONTRACT_DURATIONS.get('5', 5) = 5
          Europe           → CONTRACT_TERRITORY_EUROPE = 5
          sous-total intermédiaire = 9.99 + 10 = 19.99 < 74.99 → droits facturés
          mechanical       → +30
          public_show      → +40
          options_fee      = 5 + 5 + 30 + 40 = 80
          total            = 9.99 + 80 = 89.99
        """
        from utils.payment_validator import TrackPriceCalculator
        track = self._make_track(mp3=9.99)

        with app.app_context():
            options = {
                'is_exclusive': False, 'is_lifetime': False,
                'duration_years': 5,   'territory': 'Europe',
                'mechanical_reproduction': True, 'public_show': True, 'arrangement': False,
            }
            _base, opts_price, total = TrackPriceCalculator().calculate_total(
                track, options, format_type='mp3'
            )
        assert opts_price == Decimal('80')
        assert total == Decimal('89.99')

    def test_preset_integral_all_rights_lifetime_worldwide(self, app):
        """
        Liberté totale : à vie, monde entier, tous les droits y compris arrangement.
        Calcul (test config) :
          is_lifetime=True → CONTRACT_DURATIONS['lifetime'] = 30
          Monde entier     → CONTRACT_TERRITORY_WORLD = 10
          arrangement      → +10  (traité avant le calcul des seuils)
          sous-total intermédiaire = 9.99 + 50 = 59.99 < 74.99 → droits facturés
          mechanical       → +30
          public_show      → +40
          options_fee      = 30 + 10 + 10 + 30 + 40 = 120
          total            = 9.99 + 120 = 129.99
        """
        from utils.payment_validator import TrackPriceCalculator
        track = self._make_track(mp3=9.99)

        with app.app_context():
            options = {
                'is_exclusive': False, 'is_lifetime': True,
                'duration_years': 999, 'territory': 'Monde entier',
                'mechanical_reproduction': True, 'public_show': True, 'arrangement': True,
            }
            _base, opts_price, total = TrackPriceCalculator().calculate_total(
                track, options, format_type='mp3'
            )
        assert opts_price == Decimal('120')
        assert total == Decimal('129.99')

    def test_duration_years_zero_does_not_charge_default_duration_fee(self, app):
        """
        Régression : avant le fix, duration_years=0 déclenchait CONTRACT_DURATIONS.get('0', 5)
        et ajoutait 5€ côté serveur alors que le frontend affichait +0€.
        Ce test garantit que le scénario 'streaming seul' ne provoque plus
        d'erreur PRICE_TAMPERED lors du checkout.
        """
        from utils.payment_validator import TrackPriceCalculator
        track = self._make_track(mp3=15.00)

        with app.app_context():
            options_stream = {
                'is_exclusive': False, 'is_lifetime': False,
                'duration_years': 0,   'territory': 'France',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            options_3y = {
                'is_exclusive': False, 'is_lifetime': False,
                'duration_years': 3,   'territory': 'France',
                'mechanical_reproduction': False, 'public_show': False, 'arrangement': False,
            }
            _, _, total_stream = TrackPriceCalculator().calculate_total(
                track, options_stream, format_type='mp3'
            )
            _, _, total_3y = TrackPriceCalculator().calculate_total(
                track, options_3y, format_type='mp3'
            )

        assert total_stream == Decimal('15.00'), "Streaming seul = prix de base exact"
        assert total_3y > total_stream, "3 ans doit coûter plus cher que streaming seul"
