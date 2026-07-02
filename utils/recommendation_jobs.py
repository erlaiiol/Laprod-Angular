"""
Jobs APScheduler pour l'algorithme de recommandation.

run_correlation_job(app) — tourne chaque nuit à 3h00.
Calcule les co-occurrences de clés, tags et styles entre utilisateurs
et les stocke dans Redis (TTL 48h).

Formule : P(B|A) = |users ayant écouté A et B| / |users ayant écouté A|
Support minimum : 3 utilisateurs (évite les faux positifs sur petits échantillons).
"""

from __future__ import annotations

from collections import defaultdict


def run_correlation_job(app) -> None:
    with app.app_context():
        from extensions import db, redis_client
        from models import ListenEvent

        if not redis_client:
            app.logger.warning("[reco] Redis indisponible — job de corrélation ignoré")
            return

        try:
            _compute_correlations(db, redis_client)
            app.logger.info("[reco] Job de corrélation terminé")
        except Exception as exc:
            app.logger.error(f"[reco] Erreur job corrélation : {exc}")


def _compute_correlations(db, redis_client) -> None:
    from models import ListenEvent, Track

    TTL = 172_800  # 48h en secondes
    MIN_SUPPORT = 3

    # Charger tous les événements positifs (completion > 0.30)
    events = (
        db.session.query(ListenEvent)
        .filter(ListenEvent.completion_ratio >= 0.30)
        .all()
    )

    # Construire : user_id → {keys, tags, styles} qu'il a écoutés positivement
    user_keys: dict[int, set[str]] = defaultdict(set)
    user_tags: dict[int, set[str]] = defaultdict(set)
    user_styles: dict[int, set[str]] = defaultdict(set)

    user_similar_artists: dict[int, set[str]] = defaultdict(set)

    for ev in events:
        track = ev.track
        if track is None:
            continue
        uid = ev.user_id
        if track.key:
            user_keys[uid].add(track.key)
        if track.style:
            user_styles[uid].add(track.style)
        for tag in track.tags:
            user_tags[uid].add(tag.name)
        for artist in track.similar_artists:
            user_similar_artists[uid].add(artist.name)

    _write_correlations(redis_client, user_keys, 'key', MIN_SUPPORT, TTL)
    _write_correlations(redis_client, user_tags, 'tag', MIN_SUPPORT, TTL)
    _write_correlations(redis_client, user_styles, 'style', MIN_SUPPORT, TTL)
    _write_correlations(redis_client, user_similar_artists, 'similar_artist', MIN_SUPPORT, TTL)


def _write_correlations(
    redis_client,
    user_to_values: dict[int, set[str]],
    kind: str,
    min_support: int,
    ttl: int,
) -> None:
    """Calcule et écrit P(B|A) pour toutes les paires (A, B) dans Redis."""
    # Inverser : value → set of user_ids
    value_to_users: dict[str, set[int]] = defaultdict(set)
    for uid, values in user_to_values.items():
        for v in values:
            value_to_users[v].add(uid)

    all_values = list(value_to_users.keys())

    pipe = redis_client.pipeline()
    written = 0

    for i, val_a in enumerate(all_values):
        users_a = value_to_users[val_a]
        if len(users_a) < min_support:
            continue
        for val_b in all_values:
            if val_b == val_a:
                continue
            users_b = value_to_users[val_b]
            users_ab = users_a & users_b
            if len(users_ab) < min_support:
                continue
            prob = len(users_ab) / len(users_a)
            redis_key = f'laprod:reco:{kind}_corr:{val_a}:{val_b}'
            pipe.set(redis_key, prob, ex=ttl)
            written += 1

        # Flush par batch de 500 pour éviter les gros pipelines
        if (i + 1) % 100 == 0:
            pipe.execute()
            pipe = redis_client.pipeline()

    pipe.execute()
