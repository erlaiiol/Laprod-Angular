#!/usr/bin/env bash
# =============================================================================
# dev-ios.sh — Lance LaProd sur le simulateur iOS avec hot reload Angular
#
# Prérequis :
#   1. Xcode installé (App Store ou developer.apple.com)
#   2. Au moins un iOS Simulator Runtime installé :
#      Xcode > Settings > Platforms > iOS > télécharger la dernière version
#
# Usage :
#   ./scripts/dev-ios.sh                  # choisit le simulateur interactivement
#   ./scripts/dev-ios.sh "iPhone 16 Pro"  # cible un simulateur spécifique
# =============================================================================

set -euo pipefail

TARGET_DEVICE="${1:-}"

# ── 1. Vérifier que le simulateur cible existe ──────────────────────────────

echo "→ Simulateurs iOS disponibles :"
xcrun simctl list devices available | grep -E "iPhone|iPad" || {
  echo ""
  echo "Aucun simulateur iOS trouvé."
  echo "Solution : ouvrir Xcode > Settings > Platforms > iOS > télécharger un runtime."
  exit 1
}

# ── 2. Sélectionner un UDID ─────────────────────────────────────────────────

if [[ -n "$TARGET_DEVICE" ]]; then
  UDID=$(xcrun simctl list devices available | grep "$TARGET_DEVICE" | head -1 | sed 's/.*(\([A-F0-9-]*\)).*/\1/')
  if [[ -z "$UDID" ]]; then
    echo "Simulateur '$TARGET_DEVICE' introuvable. Relancez sans argument pour voir la liste."
    exit 1
  fi
  echo "→ Simulateur cible : $TARGET_DEVICE ($UDID)"
fi

# ── 3. Build Angular (config mobile) ────────────────────────────────────────

echo ""
echo "→ Build Angular (configuration=mobile-dev-ios)..."
# Pointe l'app vers le backend local (localhost:5000, cf. docker-compose.dev.yml),
# pas vers laprod.net — voir environment.mobile-dev-ios.ts.
npx ng build --configuration=mobile-dev-ios

# ── 4. Sync Capacitor (copie dist/ + plugins natifs) ────────────────────────

echo ""
echo "→ Sync Capacitor..."
npx cap sync ios

# ── 5. Lancer sur simulateur ─────────────────────────────────────────────────

echo ""
echo "→ Déploiement sur simulateur iOS..."

if [[ -n "$UDID" ]]; then
  npx cap run ios --target "$UDID" --no-sync
else
  # Capacitor propose le choix interactivement si plusieurs simulateurs existent
  npx cap run ios --no-sync
fi

echo ""
echo "L'app LaProd est installée et lancée dans le simulateur."
echo ""
echo "Pour du hot reload (rechargement à chaque sauvegarde), relancez avec :"
echo "  ./scripts/dev-ios-livereload.sh"
