#!/usr/bin/env bash
# =============================================================================
# dev-ios-livereload.sh — Hot reload Angular sur simulateur iOS
#
# L'app se recharge dans le simulateur à chaque sauvegarde de fichier.
# Idéal pour itérer vite sur l'UI. Le code natif Swift (PitchMonitorPlugin)
# est compilé une seule fois au premier lancement ; seul le JS/HTML/SCSS recharge.
#
# Usage : ./scripts/dev-ios-livereload.sh
# =============================================================================

set -euo pipefail

PORT=4200

# ── Sync Capacitor une seule fois (plugins natifs) ───────────────────────────

echo "→ Sync Capacitor (plugins natifs)..."
npx cap sync ios

# ── Lancer ng serve en arrière-plan ──────────────────────────────────────────

echo ""
echo "→ Démarrage ng serve (port $PORT)..."
npx ng serve --configuration=mobile-dev-ios --port=$PORT &
NG_PID=$!

# Nettoyage automatique si le script est interrompu (Ctrl+C)
cleanup() {
  echo ""
  echo "→ Arrêt du serveur Angular (PID $NG_PID)..."
  kill "$NG_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Attendre que ng serve soit prêt
echo "   Attente de ng serve..."
until curl -sf "http://localhost:$PORT" >/dev/null 2>&1; do
  sleep 1
done
echo "   ng serve prêt sur http://localhost:$PORT"

# ── Déployer sur simulateur iOS avec livereload ───────────────────────────────

echo ""
echo "→ Déploiement iOS avec livereload..."
# --livereload-url=localhost:PORT — le simulateur étant sur la même machine,
# localhost fonctionne directement (contrairement à un device physique).
npx cap run ios --no-sync --livereload --livereload-url="http://localhost:$PORT"

# ng serve continue de tourner tant que le simulateur est ouvert
wait "$NG_PID"
