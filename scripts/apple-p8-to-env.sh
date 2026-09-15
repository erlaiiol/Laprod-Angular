#!/usr/bin/env bash
#
# apple-p8-to-env.sh — Convertit une clé .p8 "Sign in with Apple" (Apple
# Developer Portal > Keys) au format attendu par APPLE_PRIVATE_KEY dans .env :
# une seule ligne, retours à la ligne réels remplacés par des "\n" littéraux
# (cf. utils/apple_signin.py::_client_secret, qui fait l'opération inverse).
#
# Usage :
#   ./scripts/apple-p8-to-env.sh                        # cherche un .p8 unique dans ~/Downloads
#   ./scripts/apple-p8-to-env.sh ~/Downloads/AuthKey_XXXXXXXXXX.p8
#   ./scripts/apple-p8-to-env.sh <fichier.p8> --write    # écrit directement dans .env (recommandé)
#
# Sans --write : affiche les lignes à copier-coller dans .env (la clé transite
# alors par ton terminal — normal si c'est voulu, mais --write l'évite).
# Avec --write : met à jour (ou ajoute) APPLE_PRIVATE_KEY et APPLE_KEY_ID dans
# le .env du repo directement, sans jamais afficher la clé.
#
# Le Key ID est déduit du nom de fichier Apple standard AuthKey_<KEYID>.p8 —
# à vérifier/compléter dans .env si le fichier a été renommé.

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENV_FILE=".env"
WRITE=false
P8_PATH=""

for arg in "$@"; do
  case "$arg" in
    --write) WRITE=true ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) P8_PATH="$arg" ;;
  esac
done

# ── Localiser le fichier .p8 ────────────────────────────────────────────────

if [ -z "$P8_PATH" ]; then
  MATCHES=()
  while IFS= read -r -d '' f; do MATCHES+=("$f"); done \
    < <(find "$HOME/Downloads" -maxdepth 1 -iname "*.p8" -print0 2>/dev/null)

  if [ "${#MATCHES[@]}" -eq 0 ]; then
    echo "Aucun .p8 trouvé dans ~/Downloads. Précise le chemin :" >&2
    echo "  $0 /chemin/vers/AuthKey_XXXXXXXXXX.p8" >&2
    exit 1
  elif [ "${#MATCHES[@]}" -gt 1 ]; then
    echo "Plusieurs fichiers .p8 trouvés dans ~/Downloads — précise lequel utiliser" >&2
    echo "(une clé Apple sert parfois à plusieurs usages : Push/APNs, MusicKit, Sign in with Apple...) :" >&2
    printf '  %s\n' "${MATCHES[@]}" >&2
    exit 1
  else
    P8_PATH="${MATCHES[0]}"
    echo "→ Fichier trouvé : $P8_PATH" >&2
  fi
fi

if [ ! -f "$P8_PATH" ]; then
  echo "Fichier introuvable : $P8_PATH" >&2
  exit 1
fi

# ── Sanity check : ça ressemble bien à une clé privée PEM ──────────────────

if ! grep -q "BEGIN PRIVATE KEY" "$P8_PATH"; then
  echo "⚠️  $P8_PATH ne contient pas l'en-tête PEM attendu (\"BEGIN PRIVATE KEY\")." >&2
  echo "   Vérifie que c'est bien le fichier téléchargé depuis Apple Developer Portal." >&2
  exit 1
fi

# ── Key ID depuis le nom de fichier (convention Apple : AuthKey_<KEYID>.p8) ──

BASENAME="$(basename "$P8_PATH")"
KEY_ID=""
if [[ "$BASENAME" =~ ^AuthKey_([A-Z0-9]+)\.p8$ ]]; then
  KEY_ID="${BASH_REMATCH[1]}"
fi

# ── Conversion : retours à la ligne réels → "\n" littéral, une seule ligne ──

ONE_LINE=$(awk '{printf "%s\\n", $0}' "$P8_PATH")

# ── Sortie ───────────────────────────────────────────────────────────────────

if [ "$WRITE" = true ]; then
  touch "$ENV_FILE"

  # Un fichier .env édité à la main finit souvent SANS retour à la ligne final
  # (dernier `save` d'un éditeur qui ne l'ajoute pas). `>>` colle alors la
  # nouvelle ligne directement à la suite de la dernière — silencieusement,
  # ça corrompt les DEUX variables (la précédente ET celle qu'on ajoute) sans
  # qu'aucune commande ne remonte d'erreur. On s'en assure avant tout append.
  ensure_trailing_newline() {
    [ -s "$ENV_FILE" ] || return 0
    [ "$(tail -c1 "$ENV_FILE")" = "" ] && return 0
    printf '\n' >> "$ENV_FILE"
  }

  if grep -q '^APPLE_PRIVATE_KEY=' "$ENV_FILE"; then
    # Remplace la ligne existante sans jamais faire transiter la valeur par un
    # argument de commande visible (historique shell / ps) : awk lit la
    # variable d'environnement, pas un argument.
    NEW_LINE="$ONE_LINE" awk '
      /^APPLE_PRIVATE_KEY=/ { print "APPLE_PRIVATE_KEY=\"" ENVIRON["NEW_LINE"] "\""; next }
      { print }
    ' "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    echo "✓ APPLE_PRIVATE_KEY mis à jour dans $ENV_FILE"
  else
    ensure_trailing_newline
    NEW_LINE="$ONE_LINE" awk 'BEGIN { print "APPLE_PRIVATE_KEY=\"" ENVIRON["NEW_LINE"] "\"" }' >> "$ENV_FILE"
    echo "✓ APPLE_PRIVATE_KEY ajouté à $ENV_FILE"
  fi

  if [ -n "$KEY_ID" ]; then
    if grep -q '^APPLE_KEY_ID=' "$ENV_FILE"; then
      sed -i.bak "s/^APPLE_KEY_ID=.*/APPLE_KEY_ID=$KEY_ID/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
      echo "✓ APPLE_KEY_ID mis à jour dans $ENV_FILE ($KEY_ID)"
    else
      ensure_trailing_newline
      echo "APPLE_KEY_ID=$KEY_ID" >> "$ENV_FILE"
      echo "✓ APPLE_KEY_ID ajouté à $ENV_FILE ($KEY_ID)"
    fi
  else
    echo "⚠️  Key ID non déduit du nom de fichier ($BASENAME) — renseigne APPLE_KEY_ID manuellement (visible dans Apple Developer Portal > Keys)." >&2
  fi

  echo ""
  echo "Reste à renseigner à la main dans $ENV_FILE (pas dans ce fichier .p8) :"
  echo "  APPLE_TEAM_ID=...       (Membership, en haut à droite du portail développeur)"
  echo "  APPLE_SERVICES_ID=...   (Identifiers > le Services ID créé pour le flow web)"
else
  echo "# À copier dans .env :"
  echo "APPLE_PRIVATE_KEY=\"$ONE_LINE\""
  [ -n "$KEY_ID" ] && echo "APPLE_KEY_ID=$KEY_ID"
fi
