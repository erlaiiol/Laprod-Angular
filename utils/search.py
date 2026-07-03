"""
Helpers de recherche textuelle — purs, sans dépendances projet.

Importés par routes.tracks_api pour la route GET /api/tracks/tracks.
Séparés pour être testables indépendamment et réutilisables.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def normalize_search_term(text: str) -> str:
    """
    Lowercase, strip accents, collapse separators (& , ; / etc.) to spaces.

    Exemple : 'Djadja & Dinaz' → 'djadja dinaz'
              'Aya Nakamura'   → 'aya nakamura'
    """
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^\w]+', ' ', text).strip().lower()


def extract_bpm(text: str) -> int | None:
    """
    Détecte une intention BPM dans la saisie libre.

    Accepte  : '140', '140bpm', '140 bpm'
    Retourne : int dans [40, 250] ou None.
    """
    m = re.fullmatch(r'(\d+)\s*(?:bpm)?', text.strip(), re.IGNORECASE)
    if m:
        val = int(m.group(1))
        return val if 40 <= val <= 250 else None
    return None


def split_search_words(text: str) -> list[str]:
    """
    Découpe un terme de recherche normalisé en mots significatifs.

    - Sépare sur les espaces ET les délimiteurs courants (&, ,, ;, |, /).
    - Filtre les mots < 3 chars, les entiers purs (BPM déjà traité séparément)
      et le mot-clé 'bpm'.

    Exemple : 'djadja & dinaz 140 bpm' → ['djadja', 'dinaz']
    """
    norm = normalize_search_term(text)
    return [
        w for w in re.split(r'[\s&,;|/]+', norm)
        if len(w) >= 3 and not w.isdigit() and w != 'bpm'
    ]


def fuzzy_name_matches(
    words: list[str],
    candidates: list[str],
    ratio: float = 0.80,
) -> list[str]:
    """
    Retourne les candidats dont au moins un token fuzzy-matche un mot de la recherche.

    Stratégie :
      - Le nom candidat est tokenisé (gère 'djadja & dinaz' → ['djadja', 'dinaz']).
      - Seuls les mots de longueur >= 4 participent (évite les faux positifs sur 'pop', 'bpm').
      - SequenceMatcher ratio >= 0.80 ≈ tolérance d'1 caractère sur 5.

    Exemples de matches attendus :
      'traap'  → 'trap'    (ratio 0.89) ✓
      'dinaaz' → 'dinaz'   (ratio 0.91) ✓
      'djadja' → token de 'djadja & dinaz' (ratio 1.0) ✓
      'pop'    → ignoré    (len < 4) — substring ilike suffit
    """
    matched: set[str] = set()
    for candidate in candidates:
        candidate_tokens = normalize_search_term(candidate).split()
        for word in words:
            if len(word) < 4:
                continue
            for token in candidate_tokens:
                if len(token) >= 3 and SequenceMatcher(None, word, token).ratio() >= ratio:
                    matched.add(candidate)
                    break
            if candidate in matched:
                break
    return list(matched)
