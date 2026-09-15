#!/usr/bin/env bash
#
# doctor.sh — Diagnostic LaProd : configuration, connectivité, certificats.
#
# Vérifie ce qui casse silencieusement en production : une variable d'env
# absente ne fait planter ni Flask ni Docker, elle fait juste échouer LA
# fonctionnalité concernée au moment où un utilisateur l'atteint (bouton
# Google/Apple qui 500, emails jamais envoyés, paiements refusés...). Ce
# script rend ces trous visibles AVANT qu'un utilisateur ne les découvre.
#
# Usage :
#   ./doctor.sh              # checks de base (dev ou prod)
#   ./doctor.sh --prod       # + certificat TLS, cron certbot, mode Stripe live
#   ./doctor.sh --quiet      # n'affiche que WARN/CRIT (pour un cron de supervision)
#   ./doctor.sh --url=https://laprod.net   # ping HTTP vers cette base au lieu de localhost:5000
#
# Niveaux : OK (vert) / WARN (jaune, dégradation d'une fonctionnalité précise,
# rien de bloquant) / CRIT (rouge, cœur de l'app cassé ou risque de sécurité).
# Sort en code 1 si au moins un CRIT est trouvé — utilisable tel quel dans un
# cron de supervision (`./doctor.sh --prod --quiet || mail -s "LaProd doctor" ...`).
#
# Fonctionne aussi bien lancé depuis l'hôte (dev, lit .env) que depuis le
# conteneur web (`docker compose exec web ./doctor.sh --prod` — lit alors les
# vraies variables d'environnement du process, pas de fichier .env dans l'image).

set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# ── Options ──────────────────────────────────────────────────────────────────

QUIET=false
PROD=false
PING_URL=""

for arg in "$@"; do
  case "$arg" in
    -q|--quiet) QUIET=true ;;
    --prod)     PROD=true ;;
    --url=*)    PING_URL="${arg#--url=}" ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Option inconnue : $arg (voir --help)" >&2
      exit 2
      ;;
  esac
done

# ── Couleurs (désactivées si pas un TTY ou NO_COLOR défini) ───────────────────

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_CRIT=$'\033[31m'; C_DIM=$'\033[2m'; C_RESET=$'\033[0m'
else
  C_OK=''; C_WARN=''; C_CRIT=''; C_DIM=''; C_RESET=''
fi

OK_COUNT=0
WARN_COUNT=0
CRIT_COUNT=0

pass() { OK_COUNT=$((OK_COUNT + 1));   $QUIET || echo "  ${C_OK}[ OK ]${C_RESET}   $1"; }
warn() { WARN_COUNT=$((WARN_COUNT + 1)); echo "  ${C_WARN}[WARN]${C_RESET}   $1"; }
crit() { CRIT_COUNT=$((CRIT_COUNT + 1)); echo "  ${C_CRIT}[CRIT]${C_RESET}   $1"; }
info() { $QUIET || echo "  ${C_DIM}[ .. ]   $1${C_RESET}"; }

section() { $QUIET || echo; $QUIET || echo "${C_DIM}── $1 ──${C_RESET}"; }

# ── Charger .env (dev) sans écraser un environnement déjà réel (conteneur) ────
# Dans le conteneur web, ces variables sont déjà exportées par docker-compose
# (env_file + environment:) — il n'y a pas de fichier .env dans l'image, cette
# étape est alors un no-op.
#
# .env n'est PAS un script shell valide en général (espaces autour de '=',
# lignes de commentaire sans '#', valeurs non quotées) — un simple `source`
# plante dessus. On réutilise python-dotenv (déjà une dépendance du projet,
# c'est ce que config.py utilise lui-même) pour un parsing fiable ; repli sur
# un filtre bash strict si uv/python3 est indisponible.

if [ -f .env ]; then
  DOTENV_EXPORTS=""
  if command -v uv >/dev/null 2>&1; then
    DOTENV_EXPORTS=$(uv run --no-sync python3 -c "
import shlex
from dotenv import dotenv_values
for k, v in dotenv_values('.env').items():
    if v is not None and k:
        print(f'export {k}={shlex.quote(v)}')
" 2>/dev/null)
  elif command -v python3 >/dev/null 2>&1; then
    DOTENV_EXPORTS=$(python3 -c "
import shlex
try:
    from dotenv import dotenv_values
except ImportError:
    raise SystemExit
for k, v in dotenv_values('.env').items():
    if v is not None and k:
        print(f'export {k}={shlex.quote(v)}')
" 2>/dev/null)
  fi

  if [ -n "$DOTENV_EXPORTS" ]; then
    eval "$DOTENV_EXPORTS"
  else
    # Repli minimal : uniquement les lignes strictement KEY=VALUE, tout le
    # reste (commentaires, lignes malformées) est silencieusement ignoré.
    while IFS='=' read -r key value; do
      [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
      export "$key=$value"
    done < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' .env)
  fi
fi

FLASK_ENV="${FLASK_ENV:-development}"
[ "$FLASK_ENV" = "production" ] && PROD=true

# ── Helpers ──────────────────────────────────────────────────────────────────

is_set() { [ -n "${!1:-}" ]; }

require_var() {
  # require_var VAR "explication si absente"
  if is_set "$1"; then pass "$1 défini"; else crit "$1 absent — $2"; fi
}

warn_var() {
  # warn_var VAR "explication si absente"
  if is_set "$1"; then pass "$1 défini"; else warn "$1 absent — $2"; fi
}

looks_like_placeholder() {
  # Détecte les valeurs par défaut connues du repo (entrypoint.sh, exemples README)
  local val="$1"
  case "$val" in
    *CHANGE_ME*|*changeme*|*change-me*|password|secret|test|"") return 0 ;;
  esac
  [ "${#val}" -lt 16 ]
}

run_py() {
  # Exécute un one-liner Python avec les dépendances du projet (psycopg2, redis…)
  # via uv si disponible, sinon python3 nu (marche dans le conteneur où le venv
  # uv est déjà sur PATH selon l'image). Renvoie 1 si ni l'un ni l'autre.
  if command -v uv >/dev/null 2>&1; then
    uv run --no-sync python3 -c "$1" 2>/dev/null
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "$1" 2>/dev/null
  else
    return 1
  fi
}

echo "LaProd doctor — $([ "$PROD" = true ] && echo 'mode prod' || echo 'mode dev') — $(date '+%Y-%m-%d %H:%M:%S')"

# ══════════════════════════════════════════════════════════════════════════
# 1. Variables d'environnement — cœur de l'app (CRIT si absentes)
# ══════════════════════════════════════════════════════════════════════════

section "Env — cœur de l'app"

require_var SECRET_KEY          "sessions/CSRF/tokens signés cassés"
require_var JWT_SECRET_KEY      "toute connexion échoue (signature JWT invalide)"
require_var CORS_ORIGINS        "le front (web ET WebView Capacitor) ne peut plus appeler l'API"
require_var FRONTEND_URL        "les emails (vérification, reset) pointent vers une URL cassée"
require_var ADMIN_PASSWORD      "le compte admin auto-créé reste sur le mot de passe par défaut"

if is_set DATABASE_URL; then
  pass "DATABASE_URL défini"
elif is_set DB_HOST && is_set DB_USER && is_set DB_PASSWORD && is_set DB_NAME; then
  pass "DB_HOST/DB_USER/DB_PASSWORD/DB_NAME définis (construction DATABASE_URL)"
else
  crit "Ni DATABASE_URL ni DB_HOST+DB_USER+DB_PASSWORD+DB_NAME complets — DB inatteignable"
fi

require_var REDIS_HOST "refresh tokens, cache OAuth, rate limiting cassés (R4 : dégradation partielle seulement)"
require_var REDIS_PORT "idem REDIS_HOST"

require_var STRIPE_SECRET_KEY    "tout paiement (achats, abonnements, retraits) cassé"
require_var STRIPE_PUBLIC_KEY    "Stripe Checkout ne s'affiche pas côté front"
require_var STRIPE_WEBHOOK_SECRET "les webhooks Stripe sont rejetés (signature invalide) — paiements jamais confirmés"

require_var MAIL_SERVER          "aucun email envoyé (vérification de compte, reset, notifications)"
require_var MAIL_USERNAME        "idem MAIL_SERVER"
require_var MAIL_PASSWORD        "idem MAIL_SERVER"
require_var MAIL_DEFAULT_SENDER  "idem MAIL_SERVER"

# ══════════════════════════════════════════════════════════════════════════
# 2. Placeholders / secrets trop faibles — sécurité
# ══════════════════════════════════════════════════════════════════════════

section "Sécurité — secrets"

for VAR in SECRET_KEY JWT_SECRET_KEY; do
  if is_set "$VAR"; then
    if looks_like_placeholder "${!VAR}"; then
      if [ "$PROD" = true ]; then crit "$VAR ressemble à une valeur par défaut/trop courte — à régénérer avant toute mise en prod"
      else warn "$VAR ressemble à une valeur par défaut/trop courte (dev : sans gravité)"; fi
    else
      pass "$VAR ne ressemble pas à un placeholder"
    fi
  fi
done

if is_set ADMIN_PASSWORD; then
  if [ "$ADMIN_PASSWORD" = "CHANGE_ME_NOW" ]; then
    if [ "$PROD" = true ]; then crit "ADMIN_PASSWORD est resté sur le défaut de entrypoint.sh (CHANGE_ME_NOW) — compte admin devinable"
    else warn "ADMIN_PASSWORD est le défaut de entrypoint.sh (dev : sans gravité)"; fi
  else
    pass "ADMIN_PASSWORD n'est pas le défaut de entrypoint.sh"
  fi
fi

# ══════════════════════════════════════════════════════════════════════════
# 3. Connexions sociales — OAuth Google / Sign in with Apple
# ══════════════════════════════════════════════════════════════════════════

section "OAuth — Google"

warn_var GOOGLE_CLIENT_ID     "bouton \"Continuer avec Google\" affiché mais échoue en 500"
warn_var GOOGLE_CLIENT_SECRET "idem GOOGLE_CLIENT_ID"

section "OAuth — Sign in with Apple"
# Tout ou rien : un sous-ensemble configuré est pire qu'aucune config (le
# bouton reste affiché — même code que Google — mais échoue en 500 au lieu
# d'être simplement absent). Voir docs/roadmap.md § Sign in with Apple.
APPLE_VARS=(APPLE_TEAM_ID APPLE_KEY_ID APPLE_PRIVATE_KEY APPLE_SERVICES_ID)
APPLE_SET=0
for V in "${APPLE_VARS[@]}"; do is_set "$V" && APPLE_SET=$((APPLE_SET + 1)); done

if [ "$APPLE_SET" -eq 0 ]; then
  warn "Sign in with Apple non configuré (APPLE_TEAM_ID/KEY_ID/PRIVATE_KEY/SERVICES_ID absents) — bouton visible, échouera en 500. Voir docs/roadmap.md § Sign in with Apple."
elif [ "$APPLE_SET" -lt "${#APPLE_VARS[@]}" ]; then
  crit "Sign in with Apple partiellement configuré ($APPLE_SET/${#APPLE_VARS[@]} variables) — pire que rien, corrige ou retire les toutes"
else
  pass "APPLE_TEAM_ID/KEY_ID/PRIVATE_KEY/SERVICES_ID tous définis"
  case "${APPLE_PRIVATE_KEY:-}" in
    *"BEGIN PRIVATE KEY"*) pass "APPLE_PRIVATE_KEY a le format PEM attendu (BEGIN PRIVATE KEY)" ;;
    *) warn "APPLE_PRIVATE_KEY ne contient pas l'en-tête PEM \"BEGIN PRIVATE KEY\" — vérifier le contenu du .p8 (retours à la ligne en \\n littéral, cf. utils/apple_signin.py)" ;;
  esac
fi
warn_var APPLE_BUNDLE_ID "défaut net.laprod.app appliqué par config.py — vérifier que ça correspond au bundle ID iOS réel"

# ══════════════════════════════════════════════════════════════════════════
# 4. Intégrations optionnelles — dégradation gracieuse déjà en place côté code
# ══════════════════════════════════════════════════════════════════════════

section "Intégrations optionnelles"

warn_var FIREBASE_CREDENTIALS_JSON "notifications push silencieusement désactivées (utils/push_service.py dégrade déjà proprement)"
warn_var GROQ_API_KEY              "Contract Analyzer (analyse IA) désactivé"

if [ "${TURNSTILE_ENABLED:-false}" = "true" ]; then
  if is_set TURNSTILE_SECRET_KEY; then
    pass "TURNSTILE_ENABLED=true avec TURNSTILE_SECRET_KEY défini"
  else
    crit "TURNSTILE_ENABLED=true mais TURNSTILE_SECRET_KEY absent — TOUT login/register web échoue (CAPTCHA jamais validable)"
  fi
else
  pass "CAPTCHA Turnstile désactivé (TURNSTILE_ENABLED≠true) — cohérent si non voulu"
fi

# ══════════════════════════════════════════════════════════════════════════
# 5. Cohérence Stripe (mode test vs live)
# ══════════════════════════════════════════════════════════════════════════

section "Stripe — cohérence des clés"

if is_set STRIPE_SECRET_KEY && is_set STRIPE_PUBLIC_KEY; then
  SK_MODE="test"; PK_MODE="test"
  case "$STRIPE_SECRET_KEY" in sk_live_*) SK_MODE="live" ;; sk_test_*) SK_MODE="test" ;; *) SK_MODE="?" ;; esac
  case "$STRIPE_PUBLIC_KEY" in pk_live_*) PK_MODE="live" ;; pk_test_*) PK_MODE="test" ;; *) PK_MODE="?" ;; esac

  if [ "$SK_MODE" = "?" ] || [ "$PK_MODE" = "?" ]; then
    warn "Impossible de déterminer le mode Stripe (préfixe sk_/pk_ inattendu)"
  elif [ "$SK_MODE" != "$PK_MODE" ]; then
    crit "STRIPE_SECRET_KEY (mode $SK_MODE) et STRIPE_PUBLIC_KEY (mode $PK_MODE) ne correspondent pas — Checkout cassé"
  elif [ "$PROD" = true ] && [ "$SK_MODE" = "test" ]; then
    crit "Clés Stripe en mode test alors que FLASK_ENV=production — aucun paiement réel ne sera encaissé"
  else
    pass "Clés Stripe cohérentes (mode $SK_MODE)$([ "$PROD" = true ] && echo ', live comme attendu en prod')"
  fi
fi

# ══════════════════════════════════════════════════════════════════════════
# 6. Connectivité réelle — DB / Redis
# ══════════════════════════════════════════════════════════════════════════

section "Connectivité"

DB_CHECK_OUT=$(run_py "
import os, sys
try:
    import psycopg2
except Exception as e:
    print('SKIP:' + str(e)); sys.exit(0)
url = os.environ.get('DATABASE_URL')
if not url:
    u, p, h, port, n = (os.environ.get(k) for k in ('DB_USER','DB_PASSWORD','DB_HOST','DB_PORT','DB_NAME'))
    if not all([u, p, h, n]):
        print('SKIP:pas assez de variables DB pour construire une URL'); sys.exit(0)
    url = f'postgresql://{u}:{p}@{h}:{port or 5432}/{n}'
if url.startswith('postgres://'):
    url = url.replace('postgres://', 'postgresql://', 1)
try:
    conn = psycopg2.connect(url, connect_timeout=4)
    conn.close()
    print('OK')
except Exception as e:
    print('FAIL:' + str(e).splitlines()[0])
")
case "$DB_CHECK_OUT" in
  OK)        pass "PostgreSQL joignable (connexion réussie)" ;;
  SKIP:*)    info "Connectivité PostgreSQL non vérifiée (${DB_CHECK_OUT#SKIP:})" ;;
  FAIL:*)    crit "PostgreSQL injoignable — ${DB_CHECK_OUT#FAIL:}" ;;
  *)         info "Connectivité PostgreSQL non vérifiée (uv/python3 introuvable)" ;;
esac

REDIS_CHECK_OUT=$(run_py "
import os
try:
    import redis
except Exception as e:
    print('SKIP:' + str(e)); raise SystemExit
try:
    r = redis.Redis(host=os.environ.get('REDIS_HOST','localhost'),
                     port=int(os.environ.get('REDIS_PORT', 6379)),
                     db=int(os.environ.get('REDIS_DB', 0)),
                     socket_connect_timeout=4)
    r.ping()
    print('OK')
except Exception as e:
    print('FAIL:' + str(e).splitlines()[0])
")
case "$REDIS_CHECK_OUT" in
  OK)     pass "Redis joignable (PING réussi)" ;;
  SKIP:*) info "Connectivité Redis non vérifiée (${REDIS_CHECK_OUT#SKIP:})" ;;
  FAIL:*) crit "Redis injoignable — ${REDIS_CHECK_OUT#FAIL:} (R4 : dégradation partielle, pas un crash — mais à corriger)" ;;
  *)      info "Connectivité Redis non vérifiée (uv/python3 introuvable)" ;;
esac

# ══════════════════════════════════════════════════════════════════════════
# 7. Migrations Alembic — une migration non appliquée est un site à moitié cassé
# ══════════════════════════════════════════════════════════════════════════

section "Migrations"

if command -v uv >/dev/null 2>&1; then
  MIG_OUT=$(FLASK_APP=app.py uv run --no-sync flask db current 2>&1)
  MIG_HEADS=$(FLASK_APP=app.py uv run --no-sync flask db heads 2>&1)
  if echo "$MIG_OUT" | grep -qi "error\|traceback"; then
    MIG_ERR_LINE=$(echo "$MIG_OUT" | grep -iE "error" | grep -v "sqlalche.me" | tail -1)
    warn "Impossible de lire l'état des migrations (DB injoignable ou venv non synchronisé) : ${MIG_ERR_LINE:-$(echo "$MIG_OUT" | tail -1)}"
  else
    CURRENT_REV=$(echo "$MIG_OUT" | grep -oE '^[0-9a-f]+' | head -1)
    HEAD_REV=$(echo "$MIG_HEADS" | grep -oE '^[0-9a-f]+' | head -1)
    if [ -z "$CURRENT_REV" ]; then
      warn "Aucune révision appliquée détectée (base vide ou jamais migrée ?)"
    elif [ "$CURRENT_REV" = "$HEAD_REV" ]; then
      pass "Migrations à jour (révision $CURRENT_REV)"
    else
      if [ "$PROD" = true ]; then crit "Migration(s) en attente : DB à $CURRENT_REV, head à $HEAD_REV — 'flask db upgrade head' requis"
      else warn "Migration(s) en attente : DB à $CURRENT_REV, head à $HEAD_REV"; fi
    fi
  fi
else
  info "Migrations non vérifiées (uv introuvable)"
fi

# ══════════════════════════════════════════════════════════════════════════
# 8. Docker Compose — santé des services (si la stack tourne)
# ══════════════════════════════════════════════════════════════════════════

section "Docker Compose"

if command -v docker >/dev/null 2>&1 && [ -f docker-compose.yml ] && docker compose version >/dev/null 2>&1; then
  COMPOSE_PS=$(docker compose -f docker-compose.yml ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null)
  if [ -z "$COMPOSE_PS" ]; then
    info "Stack Docker non démarrée (docker compose ps ne renvoie rien) — normal si lancé hors déploiement"
  else
    while read -r SERVICE STATE HEALTH; do
      [ -z "$SERVICE" ] && continue
      CRITICAL_SERVICE=false
      case "$SERVICE" in db|redis|web|frontend) CRITICAL_SERVICE=true ;; esac
      if [ "$STATE" != "running" ]; then
        if $CRITICAL_SERVICE; then crit "Service '$SERVICE' : $STATE (attendu: running)"
        else warn "Service '$SERVICE' : $STATE"; fi
      elif [ -n "$HEALTH" ] && [ "$HEALTH" != "healthy" ]; then
        if $CRITICAL_SERVICE; then crit "Service '$SERVICE' running mais healthcheck=$HEALTH"
        else warn "Service '$SERVICE' running mais healthcheck=$HEALTH"; fi
      else
        pass "Service '$SERVICE' : $STATE${HEALTH:+ ($HEALTH)}"
      fi
    done <<< "$COMPOSE_PS"
  fi
else
  info "Docker Compose non vérifié (docker introuvable ou docker-compose.yml absent du répertoire courant)"
fi

# ══════════════════════════════════════════════════════════════════════════
# 9. Certificat TLS + cron de renouvellement — uniquement en mode --prod
#    (incident déjà vécu : aucun cron n'existait, le certificat a expiré —
#    voir docs/roadmap.md § cron certbot)
# ══════════════════════════════════════════════════════════════════════════

if [ "$PROD" = true ]; then
  section "TLS — certificat et renouvellement"

  if command -v docker >/dev/null 2>&1 && docker compose -f docker-compose.yml version >/dev/null 2>&1; then
    CERT_OUT=$(docker compose -f docker-compose.yml exec -T frontend sh -c \
      "openssl x509 -enddate -noout -in /etc/letsencrypt/live/laprod.net/fullchain.pem 2>/dev/null" 2>/dev/null)
    if [ -z "$CERT_OUT" ]; then
      warn "Certificat non vérifiable (conteneur frontend arrêté, openssl absent, ou certificat introuvable au chemin attendu)"
    else
      END_DATE=$(echo "$CERT_OUT" | sed -n 's/notAfter=//p')
      END_EPOCH=$(date -d "$END_DATE" +%s 2>/dev/null || date -j -f "%b %e %T %Y %Z" "$END_DATE" +%s 2>/dev/null)
      NOW_EPOCH=$(date +%s)
      if [ -n "$END_EPOCH" ]; then
        DAYS_LEFT=$(( (END_EPOCH - NOW_EPOCH) / 86400 ))
        if   [ "$DAYS_LEFT" -lt 14 ]; then crit "Certificat TLS expire dans $DAYS_LEFT jour(s) ($END_DATE)"
        elif [ "$DAYS_LEFT" -lt 30 ]; then warn "Certificat TLS expire dans $DAYS_LEFT jours ($END_DATE)"
        else pass "Certificat TLS valide $DAYS_LEFT jours ($END_DATE)"; fi
      else
        warn "Date d'expiration du certificat illisible : $END_DATE"
      fi
    fi
  else
    info "Certificat non vérifié (docker compose indisponible)"
  fi

  if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -q certbot; then
    pass "Cron de renouvellement certbot présent (crontab -l)"
  else
    crit "Aucun cron de renouvellement certbot détecté — le certificat expirera sans renouvellement automatique (déjà arrivé, voir docs/roadmap.md)"
  fi
fi

# ══════════════════════════════════════════════════════════════════════════
# 10. Espace disque — db_assets (uploads) et logs
# ══════════════════════════════════════════════════════════════════════════

section "Espace disque"

for DIR in db_assets logs .; do
  [ -d "$DIR" ] || continue
  USAGE=$(df -P "$DIR" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')
  if [ -z "$USAGE" ]; then
    continue
  elif [ "$USAGE" -ge 95 ]; then
    crit "Disque à ${USAGE}% sur le volume de '$DIR' — risque d'échec d'écriture imminent"
  elif [ "$USAGE" -ge 85 ]; then
    warn "Disque à ${USAGE}% sur le volume de '$DIR'"
  else
    pass "Disque à ${USAGE}% sur le volume de '$DIR'"
  fi
  break  # les trois chemins sont presque toujours sur le même volume — un seul suffit
done

# ══════════════════════════════════════════════════════════════════════════
# 11. Ping HTTP applicatif — /api/auth/ping (vérifie aussi Redis vu par Flask)
# ══════════════════════════════════════════════════════════════════════════

section "API — ping applicatif"

if [ -z "$PING_URL" ]; then
  if [ "$PROD" = true ]; then PING_URL="${FRONTEND_URL:-https://laprod.net}"
  else PING_URL="http://localhost:5000"; fi
fi

if command -v curl >/dev/null 2>&1; then
  PING_BODY=$(curl -fsS --max-time 5 "${PING_URL%/}/api/auth/ping" 2>&1)
  if [ $? -ne 0 ]; then
    warn "API injoignable sur ${PING_URL%/}/api/auth/ping (normal si le service n'est pas démarré) : $PING_BODY"
  elif echo "$PING_BODY" | grep -q '"redis": *true'; then
    pass "API répond, Redis confirmé joignable depuis le process Flask lui-même"
  elif echo "$PING_BODY" | grep -q '"status": *"ok"'; then
    warn "API répond mais signale Redis injoignable côté Flask : $PING_BODY"
  else
    warn "Réponse de /api/auth/ping inattendue : $PING_BODY"
  fi
else
  info "Ping HTTP non vérifié (curl introuvable)"
fi

# ══════════════════════════════════════════════════════════════════════════
# Résumé
# ══════════════════════════════════════════════════════════════════════════

echo
echo "── Résumé ──"
echo "  ${C_OK}OK: $OK_COUNT${C_RESET}   ${C_WARN}WARN: $WARN_COUNT${C_RESET}   ${C_CRIT}CRIT: $CRIT_COUNT${C_RESET}"

if [ "$CRIT_COUNT" -gt 0 ]; then
  echo "  ${C_CRIT}→ Au moins un problème critique détecté.${C_RESET}"
  exit 1
elif [ "$WARN_COUNT" -gt 0 ]; then
  echo "  ${C_WARN}→ Fonctionne, mais des fonctionnalités sont dégradées.${C_RESET}"
  exit 0
else
  echo "  ${C_OK}→ Tout est vert.${C_RESET}"
  exit 0
fi
