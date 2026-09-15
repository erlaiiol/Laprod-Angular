"""Migration one-shot : fusionne les styles de tracks dupliqués à la casse près.

Avant l'ajout de la normalisation de casse (utils/styles.py:resolve_style_casing,
appelée désormais à chaque écriture de Track.style), rien n'empêchait de créer
"trap" ET "Trap" comme deux styles distincts — ils apparaissaient comme deux
entrées séparées dans les filtres. Ce script aligne une bonne fois le stock
existant sur une seule casse par style (la plus utilisée ; à égalité, la variante
en casse "Titre" est préférée).

Idempotent : relançable à volonté, ne touche que les tracks encore désynchronisées.

Usage (depuis la racine du projet) :

    python scripts/merge_duplicate_styles.py --dry-run   # liste sans écrire
    python scripts/merge_duplicate_styles.py             # applique
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import app
from extensions import db
from models import Track


def _pick_canonical(variant_counts: dict[str, int]) -> str:
    """Le plus utilisé gagne ; à égalité, la casse "Titre" est préférée ; sinon
    ordre alphabétique (déterministe, pour des relances idempotentes)."""
    def score(casing: str):
        return (variant_counts[casing], casing == casing.title(), casing)
    return max(variant_counts, key=score)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--dry-run', action='store_true',
                        help="liste les fusions à faire sans écrire en base")
    args = parser.parse_args()

    with app.app_context():
        rows = db.session.query(Track.style).filter(
            Track.style.isnot(None), Track.style != '',
        ).all()

        groups: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for (style,) in rows:
            groups[style.lower()][style] += 1

        duplicated = {k: v for k, v in groups.items() if len(v) > 1}

        if not duplicated:
            print("Aucun style dupliqué à la casse près — rien à faire.")
            return 0

        total_tracks_to_update = 0
        for variants in duplicated.values():
            canonical = _pick_canonical(variants)
            for casing, count in variants.items():
                if casing == canonical:
                    continue
                total_tracks_to_update += count
                print(f'  "{casing}" ({count} track(s)) → "{canonical}"')

        if args.dry_run:
            print(f"\n[dry-run] {total_tracks_to_update} track(s) seraient mis à jour.")
            return 0

        for variants in duplicated.values():
            canonical = _pick_canonical(variants)
            for casing in variants:
                if casing == canonical:
                    continue
                db.session.query(Track).filter(Track.style == casing).update(
                    {'style': canonical}, synchronize_session=False,
                )
        db.session.commit()
        print(f"\n{total_tracks_to_update} track(s) mis à jour.")
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
