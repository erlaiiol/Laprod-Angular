"""
utils/behavior_stats.py — Statistiques comportementales du catalogue (admin)
===========================================================================

Complète utils/music_stats.py (métadonnées pures) par ce qui touche au COMPORTEMENT
des utilisateurs : rythme de publication, moments d'activité, parcours avant une
topline, provenance des écoutes.

Chaque série est formatée pour le type de graphe le plus pertinent selon la forme
de la donnée — pas pour la variété :
  · une série temporelle       → aire / ligne  (uploads par semaine)
  · une donnée cyclique         → polaire       (uploads par jour de la semaine)
  · une distribution            → barres        (beats écoutés avant une topline)
  · une part d'un tout          → anneau        (provenance des écoutes)
"""
from collections import defaultdict
from datetime import datetime, timedelta

from extensions import db
from models import Track, ListenEvent, Topline

# Jours de la semaine en français, index 0 = lundi (comme datetime.weekday()).
WEEKDAYS_FR = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']

# Fenêtre d'écoute retenue avant une topline : on regarde ce que l'artiste a écouté
# dans les jours qui précèdent sa création — son « repérage » avant de poser sa voix.
TOPLINE_BROWSE_WINDOW_DAYS = 7

# Buckets d'histogramme pour « beats écoutés avant une topline ».
BROWSE_BUCKETS = [
    ('0',    0, 1),
    ('1–2',  1, 3),
    ('3–5',  3, 6),
    ('6–10', 6, 11),
    ('11+',  11, None),
]


def upload_regularity(weeks: int = 12) -> list:
    """Nombre de beats approuvés publiés, par semaine, sur les N dernières semaines.

    Série temporelle → graphe en aire. Révèle l'élan (ou l'essoufflement) de la
    production sur la plateforme.
    """
    now = datetime.now()
    start = (now - timedelta(weeks=weeks - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    # Lundi de la semaine de départ.
    start -= timedelta(days=start.weekday())

    buckets = defaultdict(int)
    rows = db.session.query(Track.created_at).filter(
        Track.is_approved.is_(True), Track.created_at >= start,
    ).all()
    for (created,) in rows:
        if not created:
            continue
        week_index = (created - start).days // 7
        if 0 <= week_index < weeks:
            buckets[week_index] += 1

    series = []
    for i in range(weeks):
        label_date = start + timedelta(weeks=i)
        series.append({'label': label_date.strftime('%d/%m'), 'value': buckets.get(i, 0)})
    return series


def uploads_by_weekday() -> list:
    """Répartition des publications par jour de la semaine.

    Donnée CYCLIQUE (lun→dim boucle) → graphe polaire, plus juste qu'une barre
    linéaire pour représenter un cycle.
    """
    counts = [0] * 7
    rows = db.session.query(Track.created_at).filter(
        Track.is_approved.is_(True), Track.created_at.isnot(None),
    ).all()
    for (created,) in rows:
        counts[created.weekday()] += 1
    return [{'label': WEEKDAYS_FR[i], 'value': counts[i]} for i in range(7)]


def listen_sources() -> list:
    """Provenance des écoutes (home / search / profile…).

    Part d'un tout → anneau. Dit d'où vient réellement l'écoute : découverte
    (home), intention (search), ou fidélité (profile).
    """
    counts = defaultdict(int)
    rows = db.session.query(ListenEvent.source).all()
    for (source,) in rows:
        counts[source or 'inconnu'] += 1
    return [{'label': s, 'value': n}
            for s, n in sorted(counts.items(), key=lambda x: x[1], reverse=True)]


def beats_before_topline() -> dict:
    """Combien de beats un artiste écoute-t-il avant de poser une topline ?

    Pour chaque topline (artiste identifié), on compte ses écoutes dans les jours
    précédant sa création. Distribution → histogramme (barres).

    Renvoie {'histogram': [...], 'median': float|None, 'sample': int}.
    """
    toplines = db.session.query(Topline.artist_id, Topline.created_at).filter(
        Topline.artist_id.isnot(None), Topline.created_at.isnot(None),
    ).all()

    per_topline_counts = []
    for artist_id, created in toplines:
        window_start = created - timedelta(days=TOPLINE_BROWSE_WINDOW_DAYS)
        n = db.session.query(ListenEvent.id).filter(
            ListenEvent.user_id == artist_id,
            ListenEvent.created_at >= window_start,
            ListenEvent.created_at <= created,
        ).count()
        per_topline_counts.append(n)

    histogram = []
    for label, lo, hi in BROWSE_BUCKETS:
        c = sum(1 for n in per_topline_counts if n >= lo and (hi is None or n < hi))
        histogram.append({'label': label, 'value': c})

    median = None
    if per_topline_counts:
        s = sorted(per_topline_counts)
        mid = len(s) // 2
        median = s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2

    return {
        'histogram': histogram,
        'median':    median,
        'sample':    len(per_topline_counts),
    }


def behavior_stats() -> dict:
    """Toutes les statistiques comportementales, pour l'endpoint admin."""
    return {
        'upload_regularity':   upload_regularity(),
        'uploads_by_weekday':  uploads_by_weekday(),
        'listen_sources':      listen_sources(),
        'beats_before_topline': beats_before_topline(),
    }
