"""
utils/track_pricing.py — Normalisation des options de licence et prix brut d'un beat
===================================================================================

Extrait de payment_track_api pour être partagé avec l'aperçu de code promo :
le prix affiché à l'acheteur quand il saisit son code et le prix effectivement
encaissé au checkout DOIVENT sortir du même calcul. Deux implémentations
parallèles finiraient par diverger, et l'écart se paierait en euros.
"""
from decimal import Decimal

from utils.payment_validator import TrackPriceCalculator
from utils.license_service import ALLOWED_DURATION_YEARS

VALID_FORMATS = ('mp3', 'wav', 'stems')


def normalize_track_options(data):
    """Valide et normalise les options de licence. Renvoie (options, error_code).

    error_code vaut None si tout est valide.
    """
    is_lifetime_opt = bool(data.get('is_lifetime', False))
    try:
        duration_years_opt = int(data.get('duration_years', 0))
    except (TypeError, ValueError):
        return None, 'INVALID_DURATION'

    # Barème fermé : sans cette liste blanche, une durée hors barème (7 ans…)
    # retomberait sur le fee par défaut du calculateur tout en étant écrite telle
    # quelle dans le contrat.
    if not is_lifetime_opt and duration_years_opt not in ALLOWED_DURATION_YEARS:
        return None, 'INVALID_DURATION'

    # « Streaming seul » : aucun droit additionnel n'est concédé. Sans cette
    # normalisation, une requête forgée produirait un contrat qui se contredit
    # lui-même et ferait payer des droits fantômes.
    stream_only = not is_lifetime_opt and duration_years_opt == 0

    options = {
        'is_exclusive':            bool(data.get('is_exclusive', False)),
        'is_lifetime':             is_lifetime_opt,
        'duration_years':          duration_years_opt,
        'territory':               data.get('territory', 'Monde entier'),
        'mechanical_reproduction': not stream_only and bool(data.get('mechanical_reproduction', False)),
        'public_show':             not stream_only and bool(data.get('public_show', False)),
        'arrangement':             not stream_only and bool(data.get('arrangement', False)),
    }
    return options, None


def compute_track_gross(track, options, format_type) -> Decimal:
    """Prix catalogue (beat + contrat), avant toute remise. Lève ValueError."""
    calculator = TrackPriceCalculator()
    _base, _opts, total = calculator.calculate_total(
        resource=track, options=dict(options), format_type=format_type,
    )
    return total
