# Checklist de lancement — Play Store / App Store / Cloud Console / Firebase / Apple Developer

Ce document recense tout ce qui reste à faire pour publier LaProd sur Android et iOS, dans
l'ordre qui minimise les allers-retours (chaque étape déverrouille la suivante). Le code
(Rust PSOLA, Sign in with Apple, push notifications) est **déjà livré et testé** — tout ce
qui suit est de la configuration externe (comptes, consoles, machine de build) ou des tests
manuels qu'aucun agent ne peut faire à ta place.

Sources : `docs/roadmap.md` (§ 2.11, § 3.9, § Sign in with Apple), `docs/deployment.md` (§ 9),
`doctor.sh`, état vérifié en direct sur Play Console / Cloud Console / Firebase Console au
14-15/09/2026.

---

## 0. Prérequis machine — Rust (bloquant pour TOUT build mobile, Android et iOS)

Sans ça, `make android-bundle`/`android-apk` et tout build Xcode échouent immédiatement
(message explicite `cargo introuvable`, pas une erreur cryptique). Aucune cible `make` ne
couvre cette étape — c'est un prérequis système, en amont de toutes les cibles du
Makefile (`android-bundle` se contente de vérifier sa présence, il ne l'installe pas) —
donc les commandes ci-dessous restent les commandes `rustup` classiques.

- [ ] Installer Rust via [rustup.rs](https://rustup.rs) (la version exacte est épinglée dans
      `native/rust-toolchain.toml`, téléchargée automatiquement au premier `cargo build`).
- [ ] Depuis `native/`, installer les cibles croisées :
  ```bash
  cd native
  rustup target add aarch64-linux-android armv7-linux-androideabi \
      i686-linux-android x86_64-linux-android
  rustup target add aarch64-apple-ios aarch64-apple-ios-sim x86_64-apple-ios
  ```
- [ ] Android : vérifier que le NDK est installé (Android Studio > SDK Manager) —
      `CMakeLists.txt` le localise automatiquement.
- [ ] iOS : rien d'autre, les command line tools Xcode suffisent.

---

## 1. Apple Developer — à faire en premier (déverrouille Firebase APNs, le backend Apple, et App Store Connect)

Connexion nécessaire dans le navigateur (2FA) — je peux ensuite naviguer et configurer avec
toi une fois connecté.

- [x] **Certificates, Identifiers & Profiles > Identifiers** > App ID `net.laprod.app` :
      cocher la capacité **Sign In with Apple**, et **Push Notifications** (si pas déjà
      cochée automatiquement par Xcode).
- [x] **Identifiers > créer un Services ID** (ex. `net.laprod.app.web`) pour le flow
      web/Android, avec :
  - domaine : `laprod.net`
  - URL de retour : `https://laprod.net/api/auth/apple/callback`
- [x] **Keys > créer une clé** avec **Sign in with Apple** ET **Apple Push Notifications
      service (APNs)** cochées ensemble (une seule clé peut couvrir les deux usages) →
      télécharger le `.p8` (téléchargement **unique**, à sauvegarder immédiatement dans un
      coffre-fort/password manager, hors du repo) → noter le **Key ID**.
- [x] Noter le **Team ID** (visible en haut à droite du portail Apple Developer) → **`A899CGSWX8`**
      (compte "Eliott Raillere").

Étape 1 terminée ✅ — Team ID confirmé : `A899CGSWX8`. Il ne reste qu'à vérifier que le
**Key ID** et le fichier `.p8` téléchargé à l'instant sont bien sauvegardés en lieu sûr (le
`.p8` ne se télécharge qu'une seule fois) avant de passer à l'étape 2 — sans ça il faudra
révoquer la clé et en régénérer une.

---

## 2. Firebase — upload de la clé APNs + clé de service backend

Projet déjà créé (`laprod-e1e4c`), apps Android + iOS déjà enregistrées,
`google-services.json` déjà dans le repo.

- [x] [console.firebase.google.com](https://console.firebase.google.com/project/laprod-e1e4c/settings/cloudmessaging)
      → Cloud Messaging → Apple app configuration → **Upload** le `.p8`. **Vérifié en
      direct** : Development ET Production APNs auth key toutes les deux présentes, Key ID
      `Y9H96D467V`, Team ID `A899CGSWX8` — cohérent avec l'étape 1.
- [x] Project Settings → **Service accounts** → clé de service backend générée —
      **vérifié** : `FIREBASE_CREDENTIALS_JSON` est défini dans le `.env` local et
      `make doctor` le confirme `OK`.

Étape 2 entièrement terminée. ✅

---

## 3. Backend — variables d'environnement (local + serveur prod)

Variables attendues par `utils/apple_signin.py` / `utils/push_service.py`, vérifiées par
`doctor.sh` :

```env
# Sign in with Apple
APPLE_TEAM_ID=A899CGSWX8
APPLE_KEY_ID=<Key ID, étape 1>
APPLE_PRIVATE_KEY=<contenu du .p8, \n littéraux>
APPLE_SERVICES_ID=net.laprod.app.web
APPLE_BUNDLE_ID=net.laprod.app   # déjà la valeur par défaut dans config.py

# Push notifications
FIREBASE_CREDENTIALS_JSON='{"type":"service_account",...}'   # contenu entier du JSON, étape 2, sur une seule ligne
```

- [x] Ajouter ces variables au `.env` local → `make dev` pour relancer la stack (rebuild
      les images, donc prend en compte la nouvelle dépendance `firebase-admin`).
- [x] `make doctor` en local : **vérifié en direct** — tous les checks Apple/Firebase/Google
      sont `OK`, y compris la validation PEM de `APPLE_PRIVATE_KEY`. Aucun `WARN`/`CRIT`.
- [ ] Sur le serveur (`ssh deploy@51.77.192.230`) : ajouter les mêmes variables à `.env`, puis :
  ```bash
  make prod-up
  ```
  (équivalent à `git pull && make prod-deploy` si le code n'est pas déjà à jour sur le
  serveur — les deux **rebuild** les images, pas un simple restart, ce qui est nécessaire
  ici puisque `firebase-admin` est une nouvelle dépendance `pyproject.toml`.)
  Les migrations (`device_token_and_push_opt_in`, `a1c9f2e7d4b3`) s'appliquent
  automatiquement au démarrage (`entrypoint.sh`) — `doctor.sh` vérifie leur statut
  (`flask db current` vs `flask db heads`, CRIT en `--prod` si des migrations restent en
  attente).
- [ ] `make doctor-prod` sur le serveur : confirmer `OK` partout (aucun `CRIT`).

### Ce que vérifie `doctor.sh` (`make doctor` / `make doctor-prod`)

Script de diagnostic à 3 niveaux (`OK`/`WARN`/`CRIT`, coloré, sortie 1 sur tout `CRIT` —
donc utilisable en cron) :

- **Variables d'env** : le cœur (`SECRET_KEY`, `JWT_SECRET_KEY`, DB, Redis, Stripe, Mail,
  CORS, admin) en `CRIT` si absent ; les intégrations optionnelles (Google, **Apple —
  vérification tout-ou-rien** des 5 variables ci-dessus, Firebase, Groq, Turnstile) en
  `WARN`, sauf Turnstile activé sans secret qui est `CRIT` (bloque silencieusement tout
  login/register web).
- **Sécurité** : détecte les secrets par défaut/placeholder (`CHANGE_ME_NOW`, clés trop
  courtes), les incohérences clés Stripe test/live, et — spécifique à Apple — valide que
  `APPLE_PRIVATE_KEY` a bien un format PEM `.p8` valide (pas juste "la variable existe").
- **Connectivité réelle** : Postgres et Redis testés en vrai (pas juste "la variable est
  définie").
- **Migrations** : `flask db current` vs `flask db heads` — `CRIT` en `--prod` si des
  migrations sont en attente.
- **Docker Compose** : santé des services, espace disque, ping HTTP sur
  `/api/auth/ping`.
- **`--prod` uniquement** : expiration du certificat TLS + présence du cron de
  renouvellement certbot.

À lancer à tout moment pendant ce chantier (pas seulement à la fin) pour voir exactement
ce qui manque encore côté `.env`, local comme prod.

---

## 4. Google Cloud Console — quasi terminé

- [x] Nettoyage `laprod-oauth` (résidu FactureLe supprimé).
- [x] Écran de consentement OAuth basculé **In production**.
- [ ] Optionnel, non bloquant : soumettre à la vérification Google (nécessaire uniquement à
      cause du logo configuré — sans ça, les utilisateurs voient un écran "app non
      vérifiée" avant de continuer). Peut se faire n'importe quand après le lancement,
      via **Verification Center** dans le même projet.

---

## 5. Piste Android — TERMINÉE, en prod ✅

- [x] Uploader les visuels sur la fiche Play Store : icône 512×512, feature graphic
      1024×500, 4 screenshots téléphone — fiche store passée à 11/11 (upload via le
      panneau de gestion d'assets Play Console, déclaration IA « Don't label assets »).
- [x] Bundle `.aab` buildé, release envoyée et **live en production sur le Play Store**.

⚠️ **Action de suivi immédiate, hors périmètre Apple** : des corrections ont été ajoutées
après cette release → il faut refaire `make android-bundle` et uploader le nouveau `.aab`
(nouvelle release Play Console, `versionCode` auto-incrémenté). Le reste de cette section
(CORS, compte `playstore_review`, etc.) reste vrai pour cette prochaine release.
- [ ] **Avant tout test Internal testing sur device réel** : vérifier que `CORS_ORIGINS`
      sur le **serveur de prod** (`ssh deploy@51.77.192.230`, dans `.env`) inclut bien
      l'origine réelle de la WebView Android release, **différente de FactureLe** :
  ```env
  CORS_ORIGINS=https://laprod.net,https://www.laprod.net,https://app.laprod.net,capacitor://app.laprod.net
  ```
  Contrairement à FactureLe, LaProd ne tourne **pas** sous le schéma `capacitor://`
  générique par défaut — `capacitor.config.ts` fixe `hostname: 'app.laprod.net'` et
  `androidScheme: 'https'` en prod. L'origine envoyée par le WebView Android en release
  est donc **`https://app.laprod.net`** (pas `capacitor://app.laprod.net`, qui lui ne sert
  que sur iOS — schéma par défaut `capacitor` non surchargé). Sans cette origine exacte
  dans `CORS_ORIGINS` côté serveur, l'app s'installe et s'ouvre normalement mais **tout
  appel API échoue silencieusement** (login, register, etc. — bloqué par le navigateur,
  pas une erreur serveur visible dans les logs Flask). Cette valeur est déjà correcte
  dans le `.env` **local** (confirmé) — reste à confirmer qu'elle est bien déployée en
  prod, puis relancer `make prod-up` si elle a été modifiée.
  `make doctor-prod` confirme seulement que `CORS_ORIGINS` est *définie*, pas qu'elle
  contient la bonne origine — la valeur ci-dessus doit être vérifiée manuellement.
- [ ] `make android-bundle` (nécessite l'étape 0 — Rust) :
  ```bash
  make android-bundle
  ```
  Produit un `.aab` signé dans `builds/android/v<version>-<code>/`.
- [ ] Play Console > Test and release > Testing > **Internal testing** (ou directement
      Production si tu es confiant) → créer une release → uploader le `.aab` → renseigner
      les notes de version.
- [ ] Vérifier que le compte de test `playstore_review` (créé automatiquement par
      `entrypoint.sh` en prod) est bien listé dans **App content > App access**.
- [ ] Une fois l'app installée sur le device de test : si le login échoue silencieusement
      (bouton qui ne réagit pas, spinner infini), inspecter la console Chrome distante
      (`chrome://inspect` sur le poste de dev, device connecté en USB avec le debugging
      activé) pour confirmer/écarter une erreur CORS avant de chercher ailleurs.
- [ ] Envoyer pour review depuis **Publishing overview**.

---

## 6. Piste iOS — vérifiée en détail le 15/09, prête pour Xcode

État réel du repo vérifié fichier par fichier (pas de suppositions) :

- [x] **Bug bridging header : déjà corrigé.** `SWIFT_OBJC_BRIDGING_HEADER` dans
      `project.pbxproj` vaut `App/App-Bridging-Header.h`, et le fichier existe bien à ce
      chemin relatif à `$(SRCROOT)` (`ios/App/App/App-Bridging-Header.h`). Plus de chemin
      doublé — build Xcode local non bloqué de ce côté.
- [x] `npm install` + `npx cap sync ios` : **déjà fait.** `Package.swift` référence bien
      `CapawesomeCapacitorAppleSignIn` et `CapacitorFirebaseMessaging` comme dépendances
      locales, et `Package.resolved` a résolu `firebase-ios-sdk` et ses dépendances
      transitives. Rien à relancer ici sauf si tu ajoutes une nouvelle dépendance npm.
- [x] `CFBundleURLTypes` (retour du flow Google OAuth via Custom Tab/Safari) : présent dans
      `Info.plist`, schéma `net.laprod.app` déclaré. *(ajouté lors d'une session précédente)*
- [x] **`UIBackgroundModes` (remote-notification) et `aps-environment` (entitlements) :
      je viens de les ajouter directement** dans `Info.plist` / `App.entitlements` — ce
      sont des clés déclaratives pures (pas de logique métier), validées avec
      `plutil`/`plistlib` (XML bien formé). Ça correspond à ce que les cases à cocher
      « Push Notifications » et « Background Modes → Remote notifications » auraient écrit
      dans Xcode — tu n'auras donc **pas besoin de cocher ces deux cases**, juste de
      vérifier qu'elles apparaissent bien cochées à l'ouverture (Xcode les détecte depuis
      les fichiers). Comme l'App ID a déjà la capacité Push Notifications activée côté
      Apple Developer Portal (étape 1), la resignature automatique devrait se faire sans
      accroc à l'ouverture du projet.
- [ ] **La seule chose qui reste réellement à faire à la main dans Xcode** — impossible à
      automatiser depuis ici (nécessite le glisser-déposer natif de l'IDE, pas un simple
      ajout de fichier dans le dossier) : glisser `GoogleService-Info.plist` (déjà présent
      dans `ios/App/App/`, reconstruit depuis la console Firebase) **dans le navigateur de
      projet Xcode** — cible `App`, groupe `App`, cocher « Copy items if needed » +
      membership sur la target `App`. Sans ce glisser-déposer, le fichier n'est pas
      embarqué dans le bundle et `FirebaseApp.configure()` échoue silencieusement au
      lancement (aucun crash, juste aucun push qui n'arrive jamais).
- [ ] `make ios-open` — build mobile + ouvre `ios/App/App.xcodeproj` (pas de
      `.xcworkspace`, SPM pas CocoaPods).
- [ ] Cible `App` → **Signing & Capabilities** : vérifier que **Sign in with Apple**,
      **Push Notifications** et **Background Modes (Remote notifications)** apparaissent
      toutes les trois sans conflit ni bandeau d'erreur de signature (elles devraient être
      déjà cochées, cf. ci-dessus — sinon les rajouter manuellement ici seulement).
- [ ] Une fois `GoogleService-Info.plist` glissé et les capacités vérifiées :
      **Product > Archive** dans Xcode pour produire le build de release (pas
      d'automatisation Makefile pour l'archive elle-même — manuel via Xcode par design).
- [ ] Xcode Organizer → **Distribute App** → App Store Connect → upload.

---

## 7. App Store Connect

- [ ] Créer la fiche app (bundle ID `net.laprod.app`, déjà réservé via l'App ID).
- [ ] Fiche store : description, mots-clés, catégorie, âge (cohérent avec le 18+ retenu sur
      Play Store vu les fonctions financières/contractuelles), captures d'écran.
- [ ] Recommandé (pas obligatoire ici puisque email/mot de passe reste disponible, mais évite
      une question du reviewer) : le bouton **Sign in with Apple** doit apparaître dans au
      moins une capture d'écran.
- [ ] App Privacy (l'équivalent Apple de Data Safety) : déclarer les mêmes catégories de
      données que sur Play Console (nom, email, historique d'achats, photos, fichiers audio,
      interactions dans l'app).
- [ ] Associer le build uploadé (étape 6) à une version, puis **TestFlight** avant
      soumission publique — au minimum un test interne sur device physique (le simulateur ne
      teste pas l'AVAudioEngine temps réel ni le vrai push APNs).
- [ ] Soumettre pour review.

---

## 8. Tests manuels avant d'annoncer le lancement

À faire sur device physique, pas sur simulateur/émulateur (push et audio temps réel s'y
comportent différemment) :

- [ ] **Sign in with Apple, iOS natif** : première autorisation (nom/email fournis),
      connexions suivantes (nom/email absents — vérifier que `apple_sub` suffit), annulation
      (aucune erreur affichée).
- [ ] **Sign in with Apple, Android + web** : même parcours via Custom Tab/navigateur.
- [ ] **Suppression de compte avec un compte lié Apple** : vérifier en base que
      `apple_refresh_token` est vidé ; si possible confirmer côté Apple (Réglages > [Apple
      ID] > Mots de passe et sécurité > Apps utilisant Apple ID) que l'app disparaît de la
      liste.
- [ ] **Push notifications** : activer le toggle dans les réglages du profil → confirmer une
      ligne dans `device_token` → test d'envoi via Firebase Console (« Send test message »)
      ou un shell Flask dans le conteneur `web` (`make prod-logs SERVICE=web` pour vérifier
      qu'il tourne, puis `docker compose -f docker-compose.yml exec web flask shell` →
      `from utils.push_service import send_push; send_push(<user_id>, ...)` — aucune cible
      `make` n'encapsule un shell Flask interactif).
- [ ] **Autotune live (moteur Rust PSOLA)** : test d'écoute manuel (`cargo run --bin
      dump_wav` dans `native/psola-dsp/` — pas de cible `make` pour ce script de dev),
      test sur au moins un appareil Android bas de gamme (API 26+) et un récent, test
      casque Bluetooth (avertissement de latence au bon moment).

---

## Résumé — état au 15/09/2026

- ✅ **Rust, Apple Developer (§1), Firebase (§2), Backend .env local (§3), Google Cloud
  Console (§4), Android/Play Store (§5)** : terminés et vérifiés en direct (console, `.env`
  local, `doctor.sh`). Android est **en production**.
- ⚠️ **Reste avant de considérer le backend « prêt » pour iOS en conditions réelles** :
  répliquer `.env` (Apple + Firebase + CORS) sur le serveur de prod (§3 dernières puces) —
  pas encore vérifié à distance.
- ⚠️ **Reste côté Android** : rebuild + reupload du `.aab` suite aux dernières corrections
  (§5).
- 🔜 **Reste côté iOS (§6)** : une seule action manuelle réelle — glisser
  `GoogleService-Info.plist` dans Xcode — puis vérifier les capacités, archiver, distribuer.
  Tout le reste (bridging header, cap sync, entitlements Push/Background Modes, schéma
  d'URL Google) est déjà en place.
- 🔜 **App Store Connect (§7)** et **tests manuels device physique (§8)** restent à faire
  une fois le build iOS archivé.

Ordre recommandé à partir de maintenant : §3 (répliquer `.env` en prod, si pas déjà fait) →
§5 (rebuild Android) en parallèle de → §6 (Xcode : glisser le plist, vérifier les
capacités, archiver, uploader) → §7 (App Store Connect) → §8 (tests manuels).
