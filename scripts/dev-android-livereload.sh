#!/usr/bin/env bash
# =============================================================================
# dev-android-livereload.sh — Hot reload Angular sur émulateur Android
#
# Usage : ./scripts/dev-android-livereload.sh
# =============================================================================

set -euo pipefail

PORT=4200

# ── Ajouter les outils Android SDK au PATH ───────────────────────────────────

ANDROID_SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME="$ANDROID_SDK"
export PATH="$ANDROID_SDK/platform-tools:$ANDROID_SDK/emulator:$PATH"

# Fait tourner l'app en HTTP (androidScheme) le temps du dev local — voir capacitor.config.ts.
export MOBILE_DEV=1

# ── JAVA_HOME — le projet Capacitor requiert Java 21 ─────────────────────────
JAVA21=$(/usr/libexec/java_home -v 21 2>/dev/null || true)
if [[ -n "$JAVA21" ]]; then
  export JAVA_HOME="$JAVA21"
else
  echo "Java 21 introuvable. Installez-le avec :"
  echo "  brew install --cask temurin@21"
  exit 1
fi

if ! command -v adb &>/dev/null; then
  echo "adb introuvable. Installez Android Studio."
  exit 1
fi

# ── Démarrer l'émulateur si nécessaire ───────────────────────────────────────

BOOTED=$(adb devices | grep emulator | grep -v "offline" | awk '{print $1}' | head -1)

if [[ -z "$BOOTED" ]]; then
  FIRST_AVD=$("$ANDROID_SDK/emulator/emulator" -list-avds 2>/dev/null | head -1)
  if [[ -z "$FIRST_AVD" ]]; then
    echo "Aucun AVD Android. Créez-en un dans Android Studio > Device Manager."
    exit 1
  fi
  echo "→ Démarrage émulateur $FIRST_AVD..."
  "$ANDROID_SDK/emulator/emulator" -avd "$FIRST_AVD" -no-snapshot-save &
  adb wait-for-device
  until adb shell getprop sys.boot_completed 2>/dev/null | grep -q "^1$"; do sleep 2; done
  echo "   Émulateur prêt."
fi

# ── Sync Capacitor une seule fois ────────────────────────────────────────────

echo ""
echo "→ Sync Capacitor (plugins natifs)..."
npx cap sync android

# ── Lancer ng serve ───────────────────────────────────────────────────────────

echo ""
echo "→ Démarrage ng serve (port $PORT)..."
# --host=0.0.0.0 expose le serveur sur le réseau local (requis pour livereload
# depuis un device physique ; pour l'émulateur seul, localhost suffit).
npx ng serve --configuration=mobile-dev-android --port=$PORT --host=0.0.0.0 &
NG_PID=$!

cleanup() {
  echo ""
  echo "→ Arrêt du serveur Angular (PID $NG_PID)..."
  kill "$NG_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "   Attente de ng serve..."
until curl -sf "http://localhost:$PORT" >/dev/null 2>&1; do sleep 1; done
echo "   ng serve prêt."

# ── Livereload vers l'émulateur ───────────────────────────────────────────────

echo ""
echo "→ Déploiement Android avec livereload..."
# L'émulateur Android accède au host via 10.0.2.2 (alias réseau interne).
# --livereload-url doit pointer vers cette adresse, pas localhost.
npx cap run android --no-sync --livereload --livereload-url="http://10.0.2.2:$PORT"

wait "$NG_PID"
