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
./doctor.sh --prod                                             # ou : make doctor-prod
```

`doctor.sh --prod` (voir aussi § 8) couvre en une commande ce que les trois précédentes ne
couvrent qu'en partie : variables d'environnement manquantes/placeholder, cohérence des clés
Stripe (test vs live), connectivité DB/Redis réelle, migrations à jour, santé de chaque service
Docker, expiration du certificat TLS et présence du cron de renouvellement. Sort en code 1 s'il
trouve un problème critique — vaut la peine de le lancer avant de considérer un déploiement
terminé.

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

Sign in with Apple (cf. `docs/roadmap.md` § Sign in with Apple pour la procédure complète
côté Apple Developer Portal) : `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY`
(contenu du `.p8`, retours à la ligne encodés en `\n` littéral), `APPLE_SERVICES_ID`
(Services ID du flow web/Android), `APPLE_BUNDLE_ID` (flow natif iOS, défaut
`net.laprod.app`, à ne changer que si le bundle ID change).

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
4. `./doctor.sh --prod` — une nouvelle variable d'environnement oubliée dans `.env` (Apple,
   Firebase, un nouveau provider…) ne fait pas planter le déploiement, elle casse juste la
   fonctionnalité en silence. `doctor.sh` la lève avant qu'un utilisateur ne la découvre.

---

## 9. Prérequis de build mobile — moteur audio Rust (`native/`)

Le monitoring vocal temps réel avec autotune (Android + iOS) repose sur un moteur PSOLA+LPC
maison écrit en Rust (`native/psola-dsp` + `native/psola-ffi`, remplace Rubber Band Library
GPL-3.0/commerciale et TarsosDSP GPL-3.0 — voir `docs/roadmap.md` pour le détail complet).
Compilé à chaque build mobile (jamais de binaire committé), donc **requis pour `make
android-bundle`/`android-apk` et pour tout build Xcode (simulateur ou archive)** — un poste de
build sans Rust échoue avec un message explicite (`cargo introuvable...`), pas une erreur de
link cryptique.

1. Installer Rust via [rustup.rs](https://rustup.rs) — la version exacte du toolchain est
   épinglée dans `native/rust-toolchain.toml` (`rustup` la télécharge automatiquement à la
   première commande lancée depuis `native/`, aucune action manuelle supplémentaire).
2. Installer les cibles croisées, depuis `native/` :
   ```bash
   cd native
   # Android (les 4 ABI supportées par android/variables.gradle)
   rustup target add aarch64-linux-android armv7-linux-androideabi \
       i686-linux-android x86_64-linux-android
   # iOS (device + simulateur Apple Silicon + simulateur Intel)
   rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
   ```
3. Android : le NDK (déjà requis indépendamment de ce chantier, voir Android Studio) doit être
   installé — `android/app/src/main/cpp/CMakeLists.txt` le localise automatiquement.
4. iOS : rien d'autre à installer — le linker Apple des command line tools Xcode suffit.

Rien à faire de plus : `cargo build` est ensuite invoqué automatiquement à chaque build (CMake
côté Android, phase "Run Script" du target `App` côté Xcode) — comme pour n'importe quelle
dépendance native déjà présente dans le projet.
