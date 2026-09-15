"""
Normalisation de la casse du champ libre Track.style.

Plusieurs styles identiques à la casse près pouvaient coexister ("Trap" / "trap"),
ce qui les faisait apparaître comme deux entrées distinctes dans les filtres. Cette
fonction est appelée à chaque écriture de Track.style (upload, édition, admin) pour
réutiliser silencieusement la casse déjà présente en base plutôt que d'en créer une
nouvelle variante.
"""
from sqlalchemy import select, func

from extensions import db


def resolve_style_casing(style: str) -> str:
    """
    Si un style existe déjà en base à la casse près, renvoie sa casse canonique
    (le premier match trouvé). Sinon renvoie le style tel quel : il devient la
    référence pour les prochaines saisies.
    """
    style = (style or '').strip()
    if not style:
        return style

    from models import Track

    existing = db.session.execute(
        select(Track.style)
        .where(
            Track.style.isnot(None),
            Track.style != '',
            func.lower(Track.style) == style.lower(),
        )
        .limit(1)
    ).scalar()

    return existing or style
