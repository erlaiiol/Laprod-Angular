"""
utils/music_stats.py — Statistiques « scientifico-musicales » du catalogue
==========================================================================

Corrélations calculées à partir des MÉTADONNÉES des beats (tonalité, mode, tempo,
style) — pas du comportement des utilisateurs. Dans le prolongement des corrélations
de gammes déjà exploitées par l'algo de reco, mais à l'échelle du catalogue : « quel
est le portrait musical de ce qui se produit sur LaProd ? ».

Destiné à l'admin. Chaque série est formatée pour un type de graphe précis, choisi
selon la nature de la donnée :
  · une part d'un tout        → camembert  (mode majeur/mineur, styles)
  · une distribution ordonnée → barres     (tonalités chromatiques, familles de tempo)
  · une corrélation croisée   → barres      (mode par style, tempo moyen par style)
"""
from collections import defaultdict

from extensions import db
from models import Track, Topline

# Ordre chromatique des toniques (et non alphabétique) : c'est l'ordre musical,
# celui d'un clavier. Une distribution de tonalités rangée de A à G n'a aucun sens.
CHROMATIC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

# Familles de tempo pensées pour la prod (et non les tempos classiques Largo/Presto,
# hors sujet ici) : bornes = (min inclus, max exclus), None = pas de borne haute.
TEMPO_FAMILIES = [
    ('Lo-fi / Ambient',        0,   70),
    ('Boom bap / Soul',        70,  90),
    ('Hip-hop / Trap lent',    90,  110),
    ('Trap / Drill',           110, 130),
    ('Afro / Dance',           130, 150),
    ('Rapide (DnB, Phonk…)',   150, None),
]

MAX_STYLES = 8   # au-delà, on regroupe la traîne dans « Autres » (camembert lisible)


def _parse_key(raw):
    """« C# minor » → ('C#', 'minor'). Renvoie (None, None) si illisible."""
    if not raw:
        return None, None
    parts = raw.strip().split()
    if len(parts) != 2:
        return None, None
    tonic, mode = parts[0], parts[1].lower()
    if tonic not in CHROMATIC or mode not in ('minor', 'major'):
        return None, None
    return tonic, mode


def _tempo_family(bpm):
    if not bpm:
        return None
    for name, lo, hi in TEMPO_FAMILIES:
        if bpm >= lo and (hi is None or bpm < hi):
            return name
    return None


def catalog_music_stats() -> dict:
    """Portrait musical du catalogue approuvé. Une seule passe sur les métadonnées."""
    rows = db.session.query(Track.key, Track.style, Track.bpm).filter(
        Track.is_approved.is_(True),
    ).all()

    total = len(rows)

    tonic_counts = defaultdict(int)
    mode_counts = {'minor': 0, 'major': 0}
    tempo_counts = defaultdict(int)
    style_counts = defaultdict(int)
    # Corrélations croisées.
    mode_by_style = defaultdict(lambda: {'minor': 0, 'major': 0})
    bpm_sum_by_style = defaultdict(float)
    bpm_n_by_style = defaultdict(int)

    for key, style, bpm in rows:
        tonic, mode = _parse_key(key)
        if tonic:
            tonic_counts[tonic] += 1
        if mode:
            mode_counts[mode] += 1

        fam = _tempo_family(bpm)
        if fam:
            tempo_counts[fam] += 1

        if style:
            style_counts[style] += 1
            if mode:
                mode_by_style[style][mode] += 1
            if bpm:
                bpm_sum_by_style[style] += bpm
                bpm_n_by_style[style] += 1

    # ── Tonalités : barres, ordre chromatique (toniques absentes = 0) ─────────
    keys_series = [{'label': t, 'value': tonic_counts.get(t, 0)} for t in CHROMATIC]

    # ── Mode majeur/mineur : camembert ───────────────────────────────────────
    modes_series = [
        {'label': 'Mineur', 'value': mode_counts['minor']},
        {'label': 'Majeur', 'value': mode_counts['major']},
    ]

    # ── Familles de tempo : barres, dans l'ordre croissant du tempo ───────────
    tempo_series = [
        {'label': name, 'range': f'{lo}–{hi}' if hi else f'{lo}+',
         'value': tempo_counts.get(name, 0)}
        for name, lo, hi in TEMPO_FAMILIES
    ]

    # ── Styles : camembert, top N + « Autres » ───────────────────────────────
    ranked = sorted(style_counts.items(), key=lambda x: x[1], reverse=True)
    styles_series = [{'label': s, 'value': n} for s, n in ranked[:MAX_STYLES]]
    tail = sum(n for _, n in ranked[MAX_STYLES:])
    if tail:
        styles_series.append({'label': 'Autres', 'value': tail})

    # ── Corrélation mode × style : barres empilées (part mineur/majeur) ───────
    # Ne garde que les styles au volume suffisant : un ratio sur 2 beats ne veut
    # rien dire.
    mode_style_series = []
    for style, n in ranked[:MAX_STYLES]:
        mm = mode_by_style[style]
        if mm['minor'] + mm['major'] >= 3:
            mode_style_series.append({
                'style': style, 'minor': mm['minor'], 'major': mm['major'],
            })

    # ── Corrélation tempo × style : barres (tempo moyen par style) ────────────
    tempo_style_series = [
        {'style': style,
         'avg_bpm': round(bpm_sum_by_style[style] / bpm_n_by_style[style], 1),
         'count': bpm_n_by_style[style]}
        for style, _ in ranked[:MAX_STYLES]
        if bpm_n_by_style[style] >= 3
    ]

    # ── Ratio mineur : une seule proportion → JAUGE (demi-anneau) ─────────────
    mode_total = mode_counts['minor'] + mode_counts['major']
    minor_ratio = {
        'minor':     mode_counts['minor'],
        'major':     mode_counts['major'],
        'pct_minor': round(100 * mode_counts['minor'] / mode_total, 1) if mode_total else 0.0,
    }

    return {
        'total_tracks':       total,
        'keys':               keys_series,
        'modes':              modes_series,
        'tempo_families':     tempo_series,
        'styles':             styles_series,
        'mode_by_style':      mode_style_series,
        'avg_tempo_by_style': tempo_style_series,
        'minor_ratio':        minor_ratio,
        'topline_by_tempo':   topline_by_tempo_family(),
    }


def topline_by_tempo_family() -> list:
    """Nombre de toplines enregistrées par famille de tempo du beat sous-jacent.

    Corrélation COMPORTEMENT (topline) × MÉTADONNÉE (tempo) : sur quels tempos les
    artistes ont-ils le plus envie de poser leur voix ? Profil multi-axes (6
    familles) → RADAR, qui montre d'un coup d'œil la « forme » de cette préférence.

    Topline.track_id → Track.bpm. On ne compte que les toplines publiées : un
    brouillon abandonné n'exprime pas une préférence.
    """
    counts = {name: 0 for name, _, _ in TEMPO_FAMILIES}
    rows = (
        db.session.query(Track.bpm)
        .join(Topline, Topline.track_id == Track.id)
        .filter(Topline.is_published.is_(True))
        .all()
    )
    for (bpm,) in rows:
        fam = _tempo_family(bpm)
        if fam:
            counts[fam] += 1
    return [{'label': name, 'value': counts[name]} for name, _, _ in TEMPO_FAMILIES]
