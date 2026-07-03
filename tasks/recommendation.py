"""
Tâche RQ — calcul asynchrone des recommandations personnalisées.

Déclenchée par routes.tracks_api quand le cache Redis est absent (cache miss).
Le résultat (liste d'IDs triée) est stocké sous :
    laprod:reco:result:{user_id}  TTL = 30 min

L'endpoint retourne immédiatement le tri "recent" pendant le calcul ;
la prochaine requête de l'utilisateur trouvera le cache chaud.
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

RESULT_CACHE_KEY = 'laprod:reco:result:{user_id}'
RESULT_CACHE_TTL = 1_800  # 30 minutes


def compute_recommendations(user_id: int) -> None:
    """
    Point d'entrée RQ.
    Crée son propre app context (le worker RQ est un process séparé).
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        _compute(user_id)


def _compute(user_id: int) -> None:
    from extensions import db, redis_client
    from models import Track
    from sqlalchemy import select
    from utils.recommendation_service import get_recommendations

    if not redis_client:
        logger.warning('[reco] Redis indisponible — calcul abandonné')
        return

    try:
        # 1. Ranking personnalisé (peut exclure des tracks récemment complétés)
        scored_tracks, is_personalized = get_recommendations(user_id, limit=200)
        scored_ids = [t.id for t in scored_tracks]
        scored_set  = set(scored_ids)

        # 2. Tous les IDs approuvés — pour garantir que le cache couvre 100% du catalogue
        all_approved_ids = db.session.execute(
            select(Track.id)
            .where(Track.is_approved.is_(True), Track.is_exclusive_sold.is_(False))
            .order_by(Track.created_at.desc())
        ).scalars().all()

        # 3. Tracks non scorés (récemment complétés, hors pool, etc.) poussés en fin de liste
        tail_ids = [tid for tid in all_approved_ids if tid not in scored_set]
        full_ordered_ids = scored_ids + tail_ids

        key = RESULT_CACHE_KEY.format(user_id=user_id)
        redis_client.setex(key, RESULT_CACHE_TTL, json.dumps(full_ordered_ids))
        logger.info(
            '[reco] user=%s → %d/%d tracks mis en cache (personalized=%s, tail=%d)',
            user_id, len(full_ordered_ids), len(all_approved_ids), is_personalized, len(tail_ids),
        )
    except Exception:
        logger.exception('[reco] Erreur dans compute_recommendations(user_id=%s)', user_id)
