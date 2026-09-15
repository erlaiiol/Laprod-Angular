#!/usr/bin/env bash
# =============================================================================
# deploy-frontend.sh — Rebuild et redémarrage du frontend UNIQUEMENT
#
# Ce script rebuild le container frontend sans toucher au backend (web, db,
# redis, worker). Utilise --no-deps pour éviter que Docker Compose ne recrée
# les dépendances, et -f docker-compose.yml pour ignorer l'override local.
#
# Usage (depuis le répertoire du projet) :
#   ./scripts/deploy-frontend.sh
# =============================================================================

set -euo pipefail

COMPOSE="docker compose -f docker-compose.yml"

log() { echo "→ $1"; }

log "Build de l'image frontend..."
$COMPOSE build frontend

log "Redémarrage du frontend (sans toucher aux autres services)..."
$COMPOSE up -d --no-deps --force-recreate frontend

log "Vérification de l'état des services..."
$COMPOSE ps

echo "✓ Frontend redémarré. Logs disponibles avec :"
echo "  docker compose -f docker-compose.yml logs -f frontend"
