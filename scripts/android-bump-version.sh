#!/usr/bin/env bash
# =============================================================================
# android-bump-version.sh — incrémente versionCode dans android/app/build.gradle
#
# Le Play Store exige un versionCode strictement croissant à chaque upload
# (bundle ou apk) : on l'incrémente donc automatiquement à chaque build de
# release (voir `make android-bundle` / `make android-apk`).
#
# versionName (le numéro affiché aux utilisateurs, ex. "1.2.0") reste manuel —
# à éditer directement dans android/app/build.gradle avant une release notable.
#
# Affiche le nouveau versionCode sur stdout.
# =============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GRADLE_FILE="$ROOT_DIR/android/app/build.gradle"

CURRENT=$(grep -oE 'versionCode [0-9]+' "$GRADLE_FILE" | grep -oE '[0-9]+')
NEXT=$((CURRENT + 1))

# perl -pi plutôt que sed -i : comportement identique entre BSD (macOS) et GNU (Linux/CI).
perl -pi -e "s/versionCode $CURRENT\b/versionCode $NEXT/" "$GRADLE_FILE"

echo "$NEXT"
