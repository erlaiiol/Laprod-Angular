"""
Service de recommandation de tracks — algorithme hybride content-based + collaboratif.

Flux :
  build_user_vector()  →  score_track()  →  get_recommendations()
  get_cold_start_tracks()  — pour utilisateurs avec < 3 événements d'écoute
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from extensions import db, redis_client
from models import Favorite, ListenEvent, Purchase, Track


# ── Poids d'écoute ────────────────────────────────────────────────────────────

def _listen_weight(completion_ratio: float) -> float:
    if completion_ratio < 0.10:
        return -0.2
    if completion_ratio < 0.30:
        return 0.3
    if completion_ratio < 0.80:
        return 1.0
    return 1.5


# ── Bonus récence (max 0.5, décroît linéairement sur 30 jours) ────────────────

def _recency_bonus(created_at: datetime) -> float:
    age_days = (datetime.now() - created_at).days
    if age_days >= 30:
        return 0.0
    return 0.5 * (1 - age_days / 30)


# ── Vecteur de préférences utilisateur ────────────────────────────────────────

def build_user_vector(user_id: int) -> dict:
    events = (
        db.session.query(ListenEvent)
        .filter_by(user_id=user_id)
        .order_by(ListenEvent.created_at.desc())
        .limit(90)
        .all()
    )

    keys: dict[str, float] = defaultdict(float)
    tags: dict[str, float] = defaultdict(float)
    styles: dict[str, float] = defaultdict(float)
    similar_artists: dict[str, float] = defaultdict(float)
    bpm_weighted_sum = 0.0
    duration_weighted_sum = 0.0
    total_weight = 0.0
    completions: list[float] = []
    beatmaker_scores: dict[int, float] = defaultdict(float)

    # Replay bonus : compter les écoutes par track
    replay_counts: dict[int, int] = defaultdict(int)
    for ev in events:
        replay_counts[ev.track_id] += 1

    # Bonus ×1.5 pour les beatmakers dont l'utilisateur a acheté ou mis en favori
    boosted_composers: set[int] = set()
    purchases = db.session.query(Purchase).filter_by(buyer_id=user_id).all()
    for p in purchases:
        if p.track and p.track.composer_id:
            boosted_composers.add(p.track.composer_id)
    favorites = db.session.query(Favorite).filter_by(user_id=user_id).all()
    for f in favorites:
        if f.track and f.track.composer_id:
            boosted_composers.add(f.track.composer_id)

    for ev in events:
        w = _listen_weight(ev.completion_ratio)
        if replay_counts[ev.track_id] >= 3:
            w += 0.3

        track = ev.track
        if track is None:
            continue

        if track.key:
            keys[track.key] += w
        if track.style:
            styles[track.style] += w
        for tag in track.tags:
            tags[tag.name] += w
        for artist in (track.similar_artists or []):
            similar_artists[artist.name] += w

        abs_w = abs(w)
        if w > 0 and track.bpm:
            bpm_weighted_sum += track.bpm * abs_w
            total_weight += abs_w
        if w > 0 and ev.track_duration > 0:
            duration_weighted_sum += ev.track_duration * abs_w

        completions.append(ev.completion_ratio)

        if track.composer_id in boosted_composers:
            beatmaker_scores[track.composer_id] += abs_w

    preferred_bpm = (bpm_weighted_sum / total_weight) if total_weight > 0 else 100.0
    preferred_duration = (duration_weighted_sum / total_weight) if total_weight > 0 else 180.0
    avg_completion = (sum(completions) / len(completions)) if completions else 0.0

    # Intégrer les corrélations Redis (atténuation ×0.4)
    _apply_redis_correlations(keys, 'key', attenuation=0.4)
    _apply_redis_correlations(tags, 'tag', attenuation=0.4)
    _apply_redis_correlations(styles, 'style', attenuation=0.4)
    _apply_redis_correlations(similar_artists, 'similar_artist', attenuation=0.4)

    return {
        'keys': dict(keys),
        'tags': dict(tags),
        'styles': dict(styles),
        'similar_artists': dict(similar_artists),
        'preferred_bpm_center': preferred_bpm,
        'preferred_duration': preferred_duration,
        'avg_completion': avg_completion,
        'favorite_beatmakers': dict(beatmaker_scores),
    }


def _apply_redis_correlations(scores: dict[str, float], kind: str, attenuation: float) -> None:
    if not redis_client:
        return
    existing_keys = list(scores.items())
    for key_a, score_a in existing_keys:
        if score_a <= 0:
            continue
        try:
            pattern = f'laprod:reco:{kind}_corr:{key_a}:*'
            for redis_key in redis_client.scan_iter(pattern):
                key_b = redis_key.split(':', maxsplit=4)[-1]
                prob = float(redis_client.get(redis_key) or 0)
                scores[key_b] += score_a * prob * attenuation
        except Exception:
            pass


# ── Score d'un track pour un vecteur utilisateur ──────────────────────────────

def score_track(track: Track, user_vector: dict) -> float:
    score = 0.0

    score += user_vector['keys'].get(track.key or '', 0) * 2.0

    for tag in track.tags:
        score += user_vector['tags'].get(tag.name, 0) * 1.5

    for artist in (track.similar_artists or []):
        score += user_vector.get('similar_artists', {}).get(artist.name, 0) * 1.8

    score += user_vector['styles'].get(track.style or '', 0) * 1.2

    bpm_center = user_vector['preferred_bpm_center']
    if track.bpm:
        score -= abs(track.bpm - bpm_center) / 50 * 0.5

    duration_center = user_vector['preferred_duration']
    score -= abs(120 - duration_center) / 60 * 0.3  # durée fixe 120s si non dispo sur track

    score += _recency_bonus(track.created_at)

    # Boost beatmaker favori
    beatmaker_score = user_vector['favorite_beatmakers'].get(track.composer_id, 0)
    if beatmaker_score > 0:
        score *= 1.5

    return score


# ── Recommandations personnalisées ────────────────────────────────────────────

def get_recommendations(user_id: int, limit: int = 20) -> tuple[list[Track], bool]:
    """Retourne (tracks, is_personalized). is_personalized=False si cold start."""
    event_count = (
        db.session.query(ListenEvent)
        .filter_by(user_id=user_id)
        .count()
    )

    if event_count < 3:
        return get_cold_start_tracks(limit), False

    # Tracks récemment complétés à ne pas re-proposer
    seven_days_ago = datetime.now() - timedelta(days=7)
    recently_completed_ids = {
        ev.track_id
        for ev in db.session.query(ListenEvent)
        .filter(
            ListenEvent.user_id == user_id,
            ListenEvent.completion_ratio >= 0.8,
            ListenEvent.created_at >= seven_days_ago,
        )
        .all()
    }

    pool = (
        db.session.query(Track)
        .filter_by(is_approved=True)
        .order_by(Track.created_at.desc())
        .limit(500)
        .all()
    )

    user_vector = build_user_vector(user_id)

    scored = []
    for track in pool:
        if track.id in recently_completed_ids:
            continue
        s = score_track(track, user_vector)
        scored.append((s, track))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [t for _, t in scored[:limit]], True


def get_cold_start_tracks(limit: int = 20) -> list[Track]:
    tracks = (
        db.session.query(Track)
        .filter_by(is_approved=True)
        .order_by(Track.created_at.desc())
        .limit(500)
        .all()
    )
    tracks.sort(key=lambda t: (t.purchase_count, t.created_at.timestamp()), reverse=True)
    return tracks[:limit]


# ── Signal playlist browse ─────────────────────────────────────────────────────

def record_playlist_browse(user_id: int, beatmaker_id: int, tracks: list) -> None:
    """
    Enregistre un signal de découverte lorsqu'un utilisateur parcourt une playlist.

    Crée des ListenEvent synthétiques (completion_ratio=0.2, ~30% d'une écoute passive)
    pour chaque track de la playlist, au même format que les vraies écoutes.
    Cela s'intègre naturellement dans build_user_vector() sans Redis supplémentaire.

    On évite de polluer l'historique avec des doublons : si un ListenEvent existe
    déjà dans les dernières 24h pour le même (user_id, track_id), on ne réinsère pas.
    """
    if len(tracks) < 3:
        return

    from datetime import timedelta
    from models import ListenEvent

    cutoff = datetime.now() - timedelta(hours=24)
    existing_ids: set[int] = {
        row[0]
        for row in db.session.query(ListenEvent.track_id)
        .filter(
            ListenEvent.user_id == user_id,
            ListenEvent.created_at >= cutoff,
        )
        .all()
    }
    new_events = []
    for track in tracks:
        if track.id in existing_ids:
            continue
        track_dur = float(getattr(track, 'duration', 120))
        new_events.append(ListenEvent(
            user_id=user_id,
            track_id=track.id,
            duration_listened=track_dur * 0.2,
            track_duration=track_dur,
            completion_ratio=0.2,
        ))
    if new_events:
        db.session.add_all(new_events)
        db.session.commit()
