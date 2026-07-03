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
    from extensions import redis_client
    from utils.recommendation_service import get_recommendations

    if not redis_client:
        logger.warning('[reco] Redis indisponible — calcul abandonné')
        return

    try:
        tracks, is_personalized = get_recommendations(user_id, limit=200)
        track_ids = [t.id for t in tracks]
        key = RESULT_CACHE_KEY.format(user_id=user_id)
        redis_client.setex(key, RESULT_CACHE_TTL, json.dumps(track_ids))
        logger.info(
            '[reco] user=%s → %d tracks mis en cache (personalized=%s)',
            user_id, len(track_ids), is_personalized,
        )
    except Exception:
        logger.exception('[reco] Erreur dans compute_recommendations(user_id=%s)', user_id)
