"""Déclinaisons WebP des images uploadées (cartes / pages détail).

Problème : les pochettes uploadées par les beatmakers pèsent 2 à 2,5 MB (PNG
plein format) et sont servies telles quelles dans des cartes de ~200 px — la
home peut tirer ~25 MB d'images à froid.

Convention : pour ``db_assets/images/tracks/foo.png``, les variantes vivent à
côté du fichier source :

    foo_thumb.webp   (max 400 px  — cartes, grilles, listes)
    foo_large.webp   (max 1000 px — page détail)

Les serializers exposent la variante si elle existe sur disque, sinon
l'original : aucune migration bloquante, le site fonctionne à l'identique tant
que ``scripts/generate_image_variants.py`` n'a pas été exécuté.
"""

import logging
from pathlib import Path

from PIL import Image

import config

# nom de variante → dimension max (le ratio est préservé, jamais d'upscale)
VARIANTS = {'thumb': 400, 'large': 1000}

_VARIANT_SUFFIXES = tuple(f'_{name}.webp' for name in VARIANTS)


def is_variant(path: Path) -> bool:
    """Vrai si le fichier est lui-même une variante générée (à ne pas re-décliner)."""
    return path.name.endswith(_VARIANT_SUFFIXES)


def variant_path(source: Path, name: str) -> Path:
    return source.with_name(f'{source.stem}_{name}.webp')


def generate_variants(source: Path, force: bool = False) -> bool:
    """Génère les variantes WebP d'une image source. Idempotent.

    Best-effort : toute erreur est loggée mais jamais propagée — l'original
    reste servi en fallback, un thumbnail manquant ne doit jamais faire
    échouer un upload ou un job worker.

    Retourne True si au moins une variante a été (ré)écrite.
    """
    written = False
    try:
        with Image.open(source) as im:
            # P/LA → RGBA pour préserver la transparence éventuelle en WebP.
            if im.mode in ('P', 'LA'):
                im = im.convert('RGBA')
            for name, max_size in VARIANTS.items():
                out = variant_path(source, name)
                if not force and out.exists() and out.stat().st_mtime >= source.stat().st_mtime:
                    continue
                variant = im.copy()
                variant.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
                variant.save(out, 'WEBP', quality=82, method=4)
                written = True
    except Exception:
        logging.exception(f'Génération des variantes WebP échouée pour {source}')
    return written


def delete_variants(source: Path) -> None:
    """Supprime les variantes d'une image (à appeler quand l'original est supprimé)."""
    for name in VARIANTS:
        variant = variant_path(source, name)
        if variant.exists():
            try:
                variant.unlink()
            except OSError:
                logging.warning(f'Suppression de variante impossible : {variant}')


def variant_or_original(rel_path: str | None, name: str) -> str | None:
    """Chemin relatif de la variante si elle existe sur disque, sinon l'original.

    ``'images/tracks/x.png'`` → ``'images/tracks/x_thumb.webp'`` ou ``'images/tracks/x.png'``.
    Pensé pour les serializers : le front consomme le champ sans se soucier
    de l'état de la migration.
    """
    if not rel_path or rel_path.startswith(('http://', 'https://')):
        return rel_path
    source = config.BASE_DIR / 'db_assets' / rel_path
    variant = variant_path(source, name)
    if variant.exists():
        return str(Path(rel_path).with_name(variant.name))
    return rel_path
