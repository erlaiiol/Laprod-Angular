# Déploiement

Production : VPS OVH, Docker Compose, nginx en frontal, Let's Encrypt.
`ssh deploy@51.77.192.230` — le dépôt est dans `/var/www/LaProd/Laprod-Angular/Laprod-Angular`.

---

## 1. Déployer

```bash
ssh deploy@51.77.192.230
cd /var/www/LaProd/Laprod-Angular/Laprod-Angular

git pull
docker compose -f docker-compose.yml up -d --build
```

Le fichier est **toujours nommé explicitement** (`-f docker-compose.yml`) : sans ça,
Docker Compose ramasse silencieusement tout `docker-compose.override.yml` /
`docker-compose.dev.yml` qui traînerait sur le serveur (fichiers de dev, jamais destinés
à la prod) et le fusionne dans le déploiement.

Reconstruction ciblée quand un seul côté a bougé :

```bash
docker compose -f docker-compose.yml up -d --build frontend   # build Angular + nginx
docker compose -f docker-compose.yml up -d --build web        # Flask + gunicorn
docker compose -f docker-compose.yml up -d --build worker     # jobs RQ
```

Vérifications après déploiement :

```bash
docker compose -f docker-compose.yml ps                       # tous les services "Up"/"healthy"
docker compose -f docker-compose.yml logs -f web --tail=100
docker compose -f docker-compose.yml logs -f worker --tail=50
```

---

## 2. Ce que fait `entrypoint.sh` au démarrage de `web`

1. `flask db upgrade head` — les migrations Alembic sont appliquées **automatiquement**.
   Une migration cassée bloque donc le démarrage du service : la tester en local avant.
2. Seeds idempotents (`seed-contract-builder`, `seed-performance-contracts`) et création
   du compte admin.
3. `exec gunicorn` — `worker_class = "gthread"`, `workers = 2*nproc+1`, 4 threads par
   worker, `timeout = 120`. Sans threads, quelques connexions lentes suffisaient à saturer
   le serveur (voir les commentaires de `gunicorn.conf.py`).

Tout ce qui tourne dans le conteneur s'exécute via `gosu appuser`, jamais en root.

---

## 3. Services

| Service | Rôle | À savoir |
|---|---|---|
| `db` | PostgreSQL 16 | Volume `postgres_data`. Sauvegarder avant toute migration destructive |
| `redis` | Redis 7 | `appendonly yes`, `maxmemory 128mb`, `allkeys-lru` — **le cache peut être évincé à tout moment**, aucun code ne doit supposer sa présence |
| `web` | Flask + gunicorn | Applique les migrations au démarrage |
| `worker` | RQ | Traitement audio, emails, recommandations, campagnes |
| `frontend` | nginx + build Angular | Expose 80/443, sert `db_assets/` en lecture seule |
| `certbot` | Let's Encrypt | Profil `certbot`, déclenché manuellement ou par cron |

---

## 4. TLS et renouvellement

Premier certificat :

```bash
docker compose -f docker-compose.yml run --rm certbot certonly --webroot \
  --webroot-path=/var/www/certbot \
  -d laprod.net -d www.laprod.net \
  --email contact@laprod.net --agree-tos --no-eff-email
```

Renouvellement — **cron installé sur l'hôte**, à ne pas supprimer (un certificat a déjà
expiré parce qu'aucun cron n'existait) :

```cron
0 3 * * 1 docker compose -f docker-compose.yml run --rm certbot renew \
          && docker compose -f docker-compose.yml exec -T frontend nginx -s reload
```

`exec -T` est **obligatoire** en cron : sans lui, docker tente d'allouer un TTY et la
commande échoue silencieusement.

---

## 5. En-têtes de sécurité et CSP

`nginx/snippets/security-headers.conf` regroupe les cinq en-têtes (HSTS, X-Frame-Options,
nosniff, Referrer-Policy, CSP). Il doit être inclus dans **chaque** bloc `location` qui
déclare son propre `add_header` : en nginx, un `add_header` local fait perdre la totalité
des en-têtes hérités du bloc `server`.

La CSP (`$csp`, défini dans `nginx/nginx.conf`) est une liste blanche stricte :

```
script-src  'self' js.stripe.com cdn.jsdelivr.net challenges.cloudflare.com
style-src   'self' 'unsafe-inline' fonts.googleapis.com cdn.jsdelivr.net
img-src     'self' data: https:
connect-src 'self' api.stripe.com challenges.cloudflare.com
frame-src   js.stripe.com challenges.cloudflare.com
object-src  'none'
```

Conséquences pratiques :

- **Aucun gestionnaire d'événement inline** dans le HTML généré (`onload=`, `onerror=`).
  C'est la cause de l'incident où la navbar est arrivée sans style en production :
  l'inlining du critical CSS d'Angular produisait un `onload=`. `inlineCritical: false`
  est resté positionné dans `angular.json` pour cette raison, et `ImgFallbackDirective`
  remplace les `onerror=` inline.
- Ajouter un domaine tiers à la CSP est une **décision d'architecture**, pas un ajustement
  de configuration. Voir `docs/positioning.md` § 2.2.

---

## 6. Variables d'environnement

`.env` à la racine, jamais commité. Clés attendues : `SECRET_KEY`, `JWT_SECRET_KEY`,
`DATABASE_URL`, `REDIS_URL`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`,
`GOOGLE_CLIENT_ID/SECRET`, `MAIL_*`, `CORS_ORIGINS`.

`CORS_ORIGINS` doit inclure les origines du WebView Capacitor en plus du web :
`https://app.laprod.net` (Android), `capacitor://app.laprod.net` (iOS),
`http://localhost:4200` (dev).

---

## 7. Migrations

```bash
flask db migrate -m "description courte"   # génère
flask db upgrade                           # applique en local
```

Avant de pousser une migration :

- la relire **entièrement** — l'autogénération se trompe sur les enums, les valeurs
  serveur par défaut et les renommages ;
- vérifier que `downgrade()` est écrit et cohérent ;
- pour un nouvel enum PostgreSQL, créer le type explicitement (`sa.Enum(...).create(bind)`)
  avant la colonne qui l'utilise, sinon l'upgrade échoue en production alors qu'il passe
  en local sur SQLite ;
- pour une colonne `NOT NULL` sur une table existante, prévoir un `server_default`.

Le service `web` refuse de démarrer si `flask db upgrade head` échoue : une migration
non testée met le site hors ligne.

---

## 8. Après un déploiement visible par les utilisateurs

1. Ajouter l'entrée correspondante dans `updates.json` (`sent_at: null`).
2. Vérifier les pages légales si la fonctionnalité touche aux données, au classement du
   catalogue ou au paiement (`/cgu`, `/privacy`, `/cookies`).
3. Contrôler `docker compose -f docker-compose.yml logs web | grep -i error` dans les minutes qui suivent.
