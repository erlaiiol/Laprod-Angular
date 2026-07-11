"""Migration : génère les variantes WebP des images déjà uploadées.

Parcourt db_assets/images/ (tracks, playlists, profiles…) et crée pour chaque
image source les déclinaisons `_thumb.webp` (400 px) et `_large.webp`
(1000 px) définies dans utils/image_variants.py.

Idempotent : relançable à volonté, ne régénère que les variantes manquantes
ou plus anciennes que leur source. Ne modifie ni ne supprime jamais les
originaux. Aucune écriture en base : les serializers découvrent les variantes
par convention de nommage sur le disque.

Usage (dans le conteneur web, depuis la racine du projet) :

    docker compose exec web python scripts/generate_image_variants.py
    docker compose exec web python scripts/generate_image_variants.py --force   # tout regénérer
    docker compose exec web python scripts/generate_image_variants.py --dry-run # lister sans écrire
"""

import argparse
import sys
from pathlib import Path

# Exécutable depuis la racine du projet ou depuis scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from utils.image_variants import VARIANTS, generate_variants, is_variant, variant_path

SOURCE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--force', action='store_true',
                        help='regénère même les variantes déjà à jour')
    parser.add_argument('--dry-run', action='store_true',
                        help="liste ce qui serait généré, sans rien écrire")
    args = parser.parse_args()

    images_root = Path(config.IMAGES_FOLDER)
    if not images_root.is_dir():
        print(f'Dossier introuvable : {images_root}', file=sys.stderr)
        return 1

    sources = sorted(
        p for p in images_root.rglob('*')
        if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES and not is_variant(p)
    )

    created = skipped = errors = 0
    bytes_sources = bytes_variants = 0

    for source in sources:
        bytes_sources += source.stat().st_size
        pending = [
            name for name in VARIANTS
            if args.force
            or not variant_path(source, name).exists()
            or variant_path(source, name).stat().st_mtime < source.stat().st_mtime
        ]
        if not pending:
            skipped += 1
            continue
        if args.dry_run:
            print(f'[dry-run] {source.relative_to(images_root)} → {", ".join(pending)}')
            created += 1
            continue
        if generate_variants(source, force=args.force):
            created += 1
            bytes_variants += sum(
                variant_path(source, name).stat().st_size
                for name in VARIANTS if variant_path(source, name).exists()
            )
            print(f'✓ {source.relative_to(images_root)}')
        else:
            errors += 1
            print(f'✗ {source.relative_to(images_root)} (voir logs)', file=sys.stderr)

    print(
        f'\n{len(sources)} images sources — '
        f'{created} traitées, {skipped} déjà à jour, {errors} erreurs.'
    )
    if bytes_variants and not args.dry_run:
        print(
            f'Poids originaux : {bytes_sources / 1e6:.1f} MB — '
            f'variantes générées : {bytes_variants / 1e6:.1f} MB '
            f'(les cartes serviront désormais les variantes).'
        )
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
