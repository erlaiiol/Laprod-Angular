#!/usr/bin/env bash
# =============================================================================
# dev-android.sh — Lance LaProd sur l'émulateur Android avec hot reload Angular
#
# Prérequis :
#   1. Android Studio installé (il installe automatiquement adb + l'émulateur)
#   2. Un AVD créé (Android Studio > Device Manager > "Pixel 8" ou autre)
#
# Usage :
#   ./scripts/dev-android.sh           # lance l'AVD par défaut et déploie
#   ./scripts/dev-android.sh Pixel_9   # cible un AVD spécifique
# =============================================================================

set -euo pipefail

TARGET_AVD="${1:-}"

# ── Ajouter les outils Android SDK au PATH ───────────────────────────────────
# Android Studio les installe dans ~/Library/Android/sdk/ mais ne les ajoute
# pas au PATH système. Ce bloc les rend disponibles pour la durée du script.

ANDROID_SDK="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_HOME="$ANDROID_SDK"
export PATH="$ANDROID_SDK/platform-tools:$ANDROID_SDK/emulator:$PATH"

# Fait tourner l'app en HTTP (androidScheme) le temps du dev local — voir
# capacitor.config.ts. Évite tout mixed content vis-à-vis du backend Flask
# local (10.0.2.2:5000), lui aussi en HTTP.
export MOBILE_DEV=1

# ── JAVA_HOME — le projet Capacitor requiert Java 21 ─────────────────────────
# Le build Gradle échoue si Java 21 n'est pas installé.
# Installation : brew install --cask temurin@21
JAVA21=$(/usr/libexec/java_home -v 21 2>/dev/null || true)
if [[ -n "$JAVA21" ]]; then
  export JAVA_HOME="$JAVA21"
else
  echo "Java 21 introuvable. Installez-le avec :"
  echo "  brew install --cask temurin@21"
  echo ""
  echo "Java disponible : $(java -version 2>&1 | head -1)"
  echo "Le build Gradle va probablement échouer."
fi

# ── 1. Vérifier adb + émulateur ──────────────────────────────────────────────

if ! command -v adb &>/dev/null; then
  echo "adb introuvable même dans ~/Library/Android/sdk/platform-tools"
  echo "Installez Android Studio et lancez-le une fois pour finaliser l'installation du SDK."
  exit 1
fi

AVDS=$("$ANDROID_SDK/emulator/emulator" -list-avds 2>/dev/null)
if [[ -z "$AVDS" ]]; then
  echo "Aucun AVD Android trouvé."
  echo "Créez-en un : Android Studio > Device Manager > + Create Device"
  exit 1
fi

echo "→ AVDs disponibles :"
echo "$AVDS"

# ── 2. Choisir l'AVD ─────────────────────────────────────────────────────────

if [[ -n "$TARGET_AVD" ]]; then
  if ! echo "$AVDS" | grep -q "$TARGET_AVD"; then
    echo "AVD '$TARGET_AVD' introuvable. AVDs disponibles :"
    echo "$AVDS"
    exit 1
  fi
  SELECTED_AVD="$TARGET_AVD"
else
  # Premier AVD de la liste par défaut
  SELECTED_AVD=$(echo "$AVDS" | head -1)
fi

echo ""
echo "→ AVD sélectionné : $SELECTED_AVD"

# ── 3. Démarrer l'émulateur si pas déjà en cours ────────────────────────────

BOOTED=$(adb devices | grep emulator | grep -v "offline" | awk '{print $1}' | head -1)

if [[ -z "$BOOTED" ]]; then
  echo ""
  echo "→ Démarrage de l'émulateur $SELECTED_AVD (peut prendre ~30s)..."
  "$ANDROID_SDK/emulator/emulator" -avd "$SELECTED_AVD" -no-snapshot-save &
  EMULATOR_PID=$!

  echo "   Attente du boot Android..."
  # Attendre que adb détecte le device et que le boot soit terminé
  adb wait-for-device
  until adb shell getprop sys.boot_completed 2>/dev/null | grep -q "^1$"; do
    sleep 2
  done
  echo "   Emulateur prêt."
else
  echo "→ Émulateur déjà en cours ($BOOTED)"
fi

# ── 4. Build Angular (config mobile) ────────────────────────────────────────

echo ""
echo "→ Build Angular (configuration=mobile-dev-android)..."
# Pointe l'app vers le backend local (10.0.2.2:5000, cf. docker-compose.dev.yml),
# pas vers laprod.net — voir environment.mobile-dev-android.ts.
npx ng build --configuration=mobile-dev-android

# ── 5. Sync Capacitor ────────────────────────────────────────────────────────

echo ""
echo "→ Sync Capacitor..."
npx cap sync android

# ── 6. Déployer sur l'émulateur ──────────────────────────────────────────────

echo ""
echo "→ Déploiement sur l'émulateur Android..."
npx cap run android --no-sync

echo ""
echo "L'app LaProd est installée et lancée dans l'émulateur."
echo ""
echo "Pour du hot reload (rechargement à chaque sauvegarde), relancez avec :"
echo "  ./scripts/dev-android-livereload.sh"
