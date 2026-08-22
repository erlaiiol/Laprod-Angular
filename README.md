# LaProd — Passe de ta passion à ta carrière

**LaProd** est une plateforme web full-stack qui accompagne la professionnalisation des créateurs de musique — beatmakers, artistes, ingénieurs du son, producteurs. Peu importe où l'utilisateur en est, LaProd fournit les outils pour travailler comme un professionnel : vendre des licences musicales (MP3, WAV, Stems), commander ou proposer des prestations de mix/mastering, contractualiser une collaboration, protéger un travail dès le premier upload. La marketplace de beats est l'un de ces outils, pas l'identité de la plateforme.

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Frontend | Angular 21 (standalone components, signals, WaveSurfer.js) |
| Application mobile | Capacitor 8 (iOS + Android) — plugins natifs Kotlin/Swift pour le topline |
| Backend | Flask 3 + SQLAlchemy 2 (Python 3.11) |
| Base de données | PostgreSQL 15 |
| Cache / files | Redis + RQ (workers asynchrones) |
| Paiement | Stripe (checkout, webhooks, wallet interne) |
| Auth | JWT (Flask-JWT-Extended) + Google OAuth (Authlib) |
| Stockage fichiers | Système de fichiers local (`db_assets/`) |
| Reverse proxy | nginx |
| Déploiement | Docker Compose (OVH VPS — `deploy@51.77.192.230`) |

---

## Architecture du projet

```
LaProd-Angular/
├── src/                    # Frontend Angular
│   ├── app/
│   │   ├── pages/          # Pages (home, track-detail, dashboard, mixmaster, legal…)
│   │   ├── components/     # Composants réutilisables (track-card, player, modals…)
│   │   ├── services/       # Services Angular (auth, player, track, playlist, mobile-audio-processor…)
│   │   ├── guards/         # Route guards (authGuard, adminGuard)
│   │   └── layout/         # Navbar, footer, player
│   └── styles/
│       ├── _variables.scss # Palette de couleurs centralisée (v.$primary, v.$gold…)
│       └── _mixins.scss    # Mixins SCSS partagés (badge, btn-ghost)
├── android/                 # Projet natif Android (Capacitor) — plugin Kotlin PitchMonitorPlugin
├── ios/                     # Projet natif iOS (Capacitor) — plugin Swift PitchMonitorPlugin
├── scripts/                 # Scripts de dev mobile (dev-android(.sh|-livereload.sh), dev-ios…)
├── routes/                 # Blueprints Flask (auth, tracks, dashboard, mixmaster…)
├── tasks/                  # Workers RQ (traitement audio, notifications…)
├── models.py               # Modèles SQLAlchemy
├── serializers.py          # Sérialisation JSON des entités
├── helpers.py              # CRUD helpers partagés
├── config.py               # Configuration Flask (ENV, DEBUG, STRIPE…)
├── nginx/                  # Configuration nginx + TLS
├── docker-compose.yml      # Production
└── docker-compose.dev.yml  # Développement local
```

---

## Prérequis

- Node.js 20+
- Python 3.11+
- PostgreSQL 15
- Redis 7
- Docker & Docker Compose (pour le déploiement)

---

## Makefile

`make help` liste toutes les cibles disponibles. Elles couvrent Docker (dev/prod),
Angular, et le mobile (émulateur/simulateur + release Android signée) — voir
[Application mobile](#application-mobile-ios--android) et
[Déploiement](#déploiement-production--ovh) pour le détail des cibles pertinentes
à chaque section.

```bash
make dev              # db+redis+web+worker en Docker, ports exposés (puis 'make serve')
make prod-up           # stack prod complète (serveur)
make android-emulator  # build + déploiement sur l'émulateur Android ("fake install")
make android-bundle    # .aab signé pour le Play Store, versionCode auto-incrémenté
```

---

## Setup local (développement)

### 1. Cloner le dépôt

```bash
git clone <url-du-repo>
cd LaProd-Angular
```

### 2. Backend Flask

```bash
python -m venv venv
source venv/bin/activate
pip install -r pyproject.toml   # ou pip install -e .

cp .env.example .env            # remplir les variables
flask db upgrade                # migrations Alembic
python app.py                   # serveur de dev Flask (port 5000)
```

### 3. Worker RQ (audio processing)

```bash
rq worker --with-scheduler
```

### 4. Frontend Angular

```bash
npm install
ng serve                        # http://localhost:4200
```

Le proxy Angular (`proxy.conf.json`) redirige `/api` → `http://localhost:5000`.

---

## Application mobile (iOS / Android)

L'app est packagée en natif via [Capacitor](https://capacitorjs.com) (`android/`, `ios/`). Le shell (WebView) charge le même build Angular que le web (`ng build --configuration=mobile`) ; deux plugins natifs (un par plateforme) exposent au JS un accès bas niveau au micro pour la fonctionnalité **topline** (détection de hauteur temps réel + monitoring autotune pendant l'enregistrement) :

| Plateforme | Plugin natif | Détection de hauteur |
|---|---|---|
| Android | `android/app/src/main/java/net/laprod/app/PitchMonitorPlugin.kt` | YIN via [TarsosDSP](https://github.com/JorenSix/TarsosDSP) |
| iOS | `ios/App/App/PitchMonitorPlugin.swift` | YIN maison (`YINDetector.swift`, accéléré vDSP/Accelerate) |

Le reste du pipeline audio (mix, EQ, de-esser, reverb, export MP3…) est en TypeScript côté client dans `MobileAudioProcessorService` (`src/app/services/mobile-audio-processor.service.ts`), commun aux deux plateformes.

**Particularité Android — dépendance TarsosDSP** : `be.tarsos.dsp:core` (Maven, dépôt `mvn.0110.be`) ne contient plus le module `io.android` depuis la 2.5. Le plugin a donc besoin du jar historique **TarsosDSP-Android-2.4** (qui embarque core + pitch + I/O Android), résolu au build via un dépôt `ivy` déclaré dans `android/build.gradle` (pas de binaire committé). Voir les commentaires dans `android/build.gradle` / `android/app/build.gradle` avant de faire évoluer cette dépendance.

### Prérequis mobile

- **Android** : Android Studio (fournit `adb` + l'émulateur), un AVD créé (Device Manager), **Java 21** (`brew install --cask temurin@21` — les scripts le sélectionnent automatiquement via `JAVA_HOME`, indépendamment du JDK par défaut du système)
- **iOS** : Xcode + au moins un simulateur iOS installé (Xcode > Settings > Platforms)

### Backend local (émulateur/simulateur ↔ docker-compose)

`npm run dev:android`/`dev:ios` construisent l'app avec des configurations Angular dédiées (`mobile-dev-android` / `mobile-dev-ios`, voir `angular.json`) qui pointent vers le backend Flask local lancé via :

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml -f docker-compose.dev.yml up -d --build
```

… et non vers `laprod.net` (contrairement à la configuration `mobile` utilisée par `npm run cap:android`/`cap:ios`, réservée aux builds "release"). Le WebView natif ne peut pas résoudre `localhost` de la même façon selon la plateforme :

| Plateforme | `apiUrl` (voir `src/environments/environment.mobile-dev-*.ts`) | Pourquoi |
|---|---|---|
| Android (émulateur) | `http://10.0.2.2:5000` | `10.0.2.2` est l'alias réseau standard de l'émulateur vers le localhost de la machine hôte — `localhost` depuis l'émulateur pointerait vers l'émulateur lui-même |
| iOS (simulateur) | `http://localhost:5000` | Le simulateur iOS partage la pile réseau du Mac hôte, `localhost` fonctionne directement (uniquement en simulateur — un iPhone physique nécessiterait l'IP LAN du Mac) |

Deux prérequis pour que ça fonctionne réellement :

1. **CORS** — `CORS_ORIGINS` (dans `.env`) doit inclure l'origine du WebView : `https://app.laprod.net` (Android, `androidScheme: 'https'`) et `capacitor://app.laprod.net` (iOS, scheme par défaut `capacitor`), en plus de `http://localhost:4200` pour le web.
2. **Cleartext Android** — Android bloque le HTTP en clair par défaut (targetSdk 28+). Une exception scoped au build **debug uniquement** (`android/app/src/debug/res/xml/network_security_config.xml`, jamais mergée en release) autorise `10.0.2.2` en HTTP.

### Lancer sur émulateur/simulateur

```bash
make android-emulator        # (ou npm run dev:android) build Angular + sync Capacitor + déploiement émulateur — "fake install"
make android-emulator-live   # idem, avec hot reload Angular (ng serve + livereload)
make android-emulator AVD=Pixel_9   # cible un AVD précis

make ios-simulator           # (ou npm run dev:ios) build Angular + sync Capacitor + déploiement simulateur
make ios-simulator-live      # idem, avec hot reload Angular
```

Ces scripts (`scripts/dev-*.sh`, invoqués par les cibles `make` ci-dessus) gèrent le choix de l'AVD/simulateur, le démarrage de l'émulateur si besoin, et le `JAVA_HOME` Android. Pour un rebuild manuel sans passer par les scripts :

```bash
npm run cap:android   # build + sync + ouvre Android Studio
make ios-open          # (ou npm run cap:ios) build + sync + ouvre Xcode
```

### Release Android (Play Store)

`make android-bundle` construit un `.aab` signé avec la configuration `mobile`
(pointe vers `https://laprod.net`, CORS/OAuth déjà couverts par `CORS_ORIGINS`),
incrémente automatiquement `versionCode` dans `android/app/build.gradle`, et
range l'artefact dans `builds/android/v<versionName>-<versionCode>/` (dossier
gitignored).

```bash
make android-keystore   # UNE SEULE FOIS — génère android/app/laprod-release.keystore
                         # + android/keystore.properties (gitignorés). À sauvegarder
                         # précieusement : sans eux, impossible de publier une mise à
                         # jour de l'app sous net.laprod.app.
make android-bundle     # .aab signé pour l'upload Play Console
make android-apk        # .apk signé, pour du sideload direct hors Play Store
```

`versionName` (le numéro affiché aux utilisateurs) reste manuel — à éditer dans
`android/app/build.gradle` avant une release notable.

### Tests natifs

```bash
cd android && JAVA_HOME=$(/usr/libexec/java_home -v 21) ./gradlew :app:testDebugUnitTest   # PitchCorrectionEngine, ScaleBuilder (JVM pur, pas d'émulateur requis)
```

Côté iOS, les tests (`ios/App/AppTests/`) s'exécutent depuis Xcode (⌘U) ou `xcodebuild test`.

### Icône et splash screen

Générés via [`@capacitor/assets`](https://github.com/ionic-team/capacitor-assets) à partir de `assets/logo.png` (copie de `public/assets/logo.png`, le logo utilisé sur le site). Pour régénérer après un changement de logo :

```bash
npx capacitor-assets generate --android --ios \
  --iconBackgroundColor '#ffffff' --iconBackgroundColorDark '#ffffff' \
  --splashBackgroundColor '#ffffff' --splashBackgroundColorDark '#ffffff'
```

Fond blanc choisi car le logo est un glyphe noir sur fond transparent (illisible sur le fond sombre `#101218` de l'app) — écrase les icônes/splash Android (`android/app/src/main/res/mipmap-*`, `drawable*/splash.png`) et iOS (`ios/App/App/Assets.xcassets/`). Sans `--android --ios`, l'outil génère aussi des assets PWA (`public/manifest.webmanifest`) non utilisés par le projet.

---

## Variables d'environnement

Créer un fichier `.env` à la racine (ne jamais committer) :

```env
# Flask
FLASK_ENV=development
SECRET_KEY=<clé secrète>

# Base de données
DATABASE_URL=postgresql://user:password@localhost/laprod

# Redis
REDIS_URL=redis://localhost:6379/0

# JWT
JWT_SECRET_KEY=<clé JWT>

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Email (SMTP)
MAIL_SERVER=smtp.example.com
MAIL_USERNAME=...
MAIL_PASSWORD=...

# Comptes de service (créés automatiquement au démarrage, voir entrypoint.sh)
ADMIN_PASSWORD=...
TEST_ACCOUNT_PASSWORD=...
```

---

## Déploiement (production — OVH)

```bash
# Sur le serveur
ssh deploy@51.77.192.230
cd /var/www/LaProd/Laprod-Angular/Laprod-Angular

git pull && make prod-up   # (ou : git pull && docker compose -f docker-compose.yml up -d --build)
```

Pour reconstruire uniquement le frontend : `make deploy-frontend` (ou `docker compose -f docker-compose.yml up -d --build frontend`).

Pour reconstruire uniquement le backend : `docker compose -f docker-compose.yml up -d --build web`.

Autres cibles utiles : `make prod-down`, `make prod-logs [SERVICE=web]`, `make certbot-renew`.

### Compte de test Play Store

À chaque démarrage du conteneur `web` (donc à chaque `prod-deploy`/`prod-up`), `entrypoint.sh`
crée automatiquement — de façon idempotente — un compte `playstore_review` /
`playstore-review@laprod.net`, tous droits débloqués (plan le plus élevé, rôles artiste +
beatmaker), pour la review Google Play (Play Console > App content > App access). Mot de passe
défini par `TEST_ACCOUNT_PASSWORD` dans `.env` sur le serveur — à renseigner tel quel dans la
fiche Play Console.

---

## Fonctionnalités principales

Chaque outil ci-dessous répond à une étape concrète de la professionnalisation d'un créateur — de la première vente à la gestion d'une équipe.

- **Marketplace de beats** — commencer à générer des revenus : catalogue filtrable par BPM, tonalité, style, gamme ; algorithme de recommandation basé sur des critères musicaux réels
- **Licences musicales** — sécuriser ses créations : MP3, WAV, Stems à la carte ; contrat PDF généré automatiquement à l'achat ; droits calés sur le budget
- **Mix & Mastering** — accéder à des prestations professionnelles : commande d'ingénierie sonore avec paiement progressif (acompte + solde à la livraison), briefing détaillé, révisions
- **Analyse de contrats** — travailler légalement dès les premières collaborations : dépôt de n'importe quel contrat musical pour analyse des droits cédés, exclusivités et durée
- **Playlists** — développer un projet musical : création, gestion, image de couverture générée ou uploadée
- **Wallet interne** — exercer une activité économique : accumulation des revenus, payout Stripe à la demande
- **Premium** — accéder aux outils Pro plus tôt dans son parcours : abonnement mensuel/annuel, fonctionnalités Pro et accès topline
- **Topline** — transformer une idée en morceau : système de réponse audio sur les beats (artistes enregistrent par-dessus) ; pitch-detection et monitoring autotune temps réel via plugins natifs sur mobile (voir [Application mobile](#application-mobile-ios--android))
- **Watermark automatique** — protéger son travail dès le premier upload
- **Contract Builder & signature en ligne** — travailler légalement dès les premières collaborations, sans juriste
- **Module producteur** — rencontrer les bons collaborateurs et coordonner une équipe déjà présente sur LaProd (roster, planning, royalties)
- **Gamification** — concours de beats (à venir)
- **OAuth** — connexion Google
- **Notifications** — système interne temps réel

---

## Mobile Studio — Pipeline d'extension de beat

La fonctionnalité **Topline** permet aux artistes d'enregistrer leur voix par-dessus un instrumental. Pour allonger le beat avant l'enregistrement, un pipeline DSP côté client analyse et étend l'audio sans serveur.

### Architecture

```
BeatExtenderService          (src/app/services/beat-extender.service.ts)
 ├── analyzeBeat(url, bpm)   → BeatAnalysis + Float32Array brut
 │    ├── _fetchAndDecode()  — fetch + OfflineAudioContext.decodeAudioData()
 │    ├── _refineBeatGrid()  — BPM précis + phase du 1er temps (voir ci-dessous)
 │    ├── _detectFadeStart() — détecte le fade anti-piratage (RMS windows)
 │    └── _analyzeSection()  — énergie, transients, waveform miniature par section
 └── createExtendedBeat()    → ExtendedBeatResult { blob, totalSamples, addedStart… }
      └── _crossfade()       — micro-fade 3 ms anti-clic à chaque jonction

BeatSectionPickerComponent   (src/app/components/beat-section-picker/)
 └── Affiche les sections analysées, permet de prévisualiser et d'émettre
     `(extended): ExtendedBeatResult` vers MobileStudioComponent

MobileStudioComponent        (src/app/components/mobile-studio/)
 ├── onSectionExtended()     — hot-swap de l'audioEl, accumule les régions bleues
 ├── _drawBeatWaveform()     — canvas bicolore : rouge (original) + bleu (ajouté)
 └── MobileMetronomeService  — métronome scoped au composant (providers: […])
```

### _refineBeatGrid — détection du tempo et de la phase

Le BPM fourni dans la base de données est souvent arrondi à l'entier, et le fichier peut avoir une intro silencieuse avant le 1er temps. `_refineBeatGrid` corrige les deux :

1. **ODF** (Onset Detection Function) : filtre passe-bas 200 Hz (bande kick) → flux d'énergie positif par fenêtre de 5 ms.
2. **Autocorrélation** sur ±12 % du lag nominal → pic dominant → `bestLag`.
3. **Interpolation parabolique** sur le triplet autour du pic → `fracLag` → `samplesPerBeat` sub-frame.
4. **Phase grid scoring** : pour chaque offset `p ∈ [0, bestLag)`, score = somme ODF aux multiples du lag → meilleur alignement.
5. **Affinement au sample** : pic d'énergie grave dans ±2.5 ms autour de la frame gagnante → `beatPhase`.
6. **Fallback** : si le BPM raffiné dévie > 5 % du nominal, le BPM nominal est conservé ; la phase détectée est toujours gardée.

### Jonction sans artefact (SPLICE_FADE_MS = 3 ms)

Un beat de prod est une boucle parfaite : la fin de la mesure 8 enchaîne naturellement sur la mesure 1. Dès que le point de coupe est sur un temps exact, il n'y a aucune discontinuité musicale à « fondre ». Seule la discontinuité d'amplitude au sample de coupure risque de produire un clic. Un micro-fade de 3 ms (~132 samples à 44 100 Hz) l'élimine sans créer de doublement de mélodie. **Ne pas augmenter cette constante** : un fondu plus long crée un effet de doublage audible.

### Régions bleues dans la waveform

Chaque extension accumule une région `{ startFrac, lengthFrac }` (fractions du total) dans `_beatAddedRegions`. Ces fractions restent valides quand le buffer grandit à chaque nouvelle extension. `_drawBeatWaveform()` les rend en bleu semi-transparent par-dessus les barres rouges.

### Tests

```bash
ng test   # suite Angular (Karma/Jasmine)
```

Les tests de `BeatExtenderService` (src/app/services/beat-extender.service.spec.ts) couvrent :
- DSP helpers : `_rmsOf`, `_miniWaveform`, `_countTransients`, `_lowpass`, `_highpass`, `_crossfade`
- Pipeline : `_detectFadeStart`, `_refineBeatGrid`, `_corrAt`, `_assignNames`
- Intégration : `createExtendedBeat` en modes `end` et `after`

Les utilitaires waveform purs (src/app/utils/waveform.utils.spec.ts) sont testés sans TestBed.

### Ajouter une nouvelle fonctionnalité d'analyse

1. Enrichir `BeatAnalysis` avec le nouveau champ.
2. Le calculer dans `analyzeBeat()` après `_refineBeatGrid()`.
3. L'exposer dans `BeatSectionPickerComponent` si nécessaire pour l'UI.
4. Ajouter un test dans `beat-extender.service.spec.ts`.

---

## Philosophie produit

LaProd est conçu par des musiciens pour des musiciens. La plateforme n'est pas l'endroit où l'on fait de la musique, c'est l'endroit où l'on construit une carrière musicale — à son rythme, quel que soit le point de départ. Elle ne promet pas le succès ; elle fournit les outils pour travailler comme un professionnel : une rémunération juste pour chaque créateur, un marché géré par ses acteurs — pas par des intermédiaires — et des fonctionnalités de paiement, de contrat ou de licence pensées pour protéger à la fois l'acheteur et le vendeur. Voir [`docs/positioning.md`](docs/positioning.md) pour le détail des engagements que ça implique.

---

## Contact

- Site : [laprod.net](https://laprod.net)
- Email : [contact@laprod.net](mailto:contact@laprod.net)
