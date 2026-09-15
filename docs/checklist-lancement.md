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
`google-services.json` déjà dans le repo. Reste :

- [ ] [console.firebase.google.com](https://console.firebase.google.com/project/laprod-e1e4c/settings/cloudmessaging)
      → Cloud Messaging → Apple app configuration → **Upload** le `.p8` obtenu à l'étape 1,
      avec son Key ID et le Team ID.
- [ ] Project Settings → **Service accounts** → « Generate new private key » → télécharge
      le JSON (clé du compte de service `firebase-adminsdk-fbsvc@laprod-e1e4c...`, utilisée
      par le backend pour *envoyer* les push, différente de la clé APNs qui sert à Firebase
      pour les *transmettre* à Apple).

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

- [ ] Ajouter ces variables au `.env` local → `make dev` pour relancer la stack (rebuild
      les images, donc prend en compte la nouvelle dépendance `firebase-admin`).
- [ ] `make doctor` en local : vérifier que les checks Apple/Firebase passent en `OK`
      (pas de `WARN`/`CRIT`).
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

## 5. Piste Android — la plus rapide à finaliser (indépendante d'Apple)

- [ ] Uploader manuellement les visuels sur la fiche Play Store (bloqué côté automatisation
      navigateur, à faire toi-même) : icône 512×512, feature graphic 1024×500, 2 à 8
      screenshots téléphone. Fichiers déjà préparés et présentés précédemment.
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
- [ ] Envoyer pour review depuis **Publishing overview**.

---

## 6. Piste iOS — après l'étape 1 (Apple Developer)

- [ ] **Corriger un bug préexistant, indépendant de ce chantier**, qui bloque tout build
      Xcode local : `SWIFT_OBJC_BRIDGING_HEADER` dans `project.pbxproj` pointe vers
      `App/App/App-Bridging-Header.h` (chemin doublé) alors que le fichier réel est à
      `App/App-Bridging-Header.h` relatif à `$(SRCROOT)`. À corriger avant de pouvoir
      builder iOS en local (Debug ou Release).
- [ ] `make install` — installe/mets à jour les dépendances npm (matérialise
      `@capawesome/capacitor-apple-sign-in` et `@capacitor-firebase/messaging` dans
      `node_modules`).
- [ ] `make ios-open` — build mobile + `cap sync ios` (régénère `Package.swift`,
      matérialise les plugins côté Xcode) + ouvre `ios/App/App.xcodeproj` automatiquement
      (pas de `.xcworkspace`, SPM pas CocoaPods — rien à faire de plus ici).
- [ ] Glisser `GoogleService-Info.plist` (déjà présent dans `ios/App/App/`, reconstruit
      depuis la console Firebase) **dans Xcode** — cible `App`, groupe `App`, cocher
      « Copy items if needed » + membership sur la target `App`. Sans ce glisser-déposer
      explicite dans Xcode (juste poser le fichier dans le dossier ne suffit pas), il n'est
      pas embarqué dans le bundle et `FirebaseApp.configure()` échoue silencieusement.
- [ ] Cible `App` → **Signing & Capabilities** :
  - Vérifier que **Sign in with Apple** apparaît déjà (câblé via `App.entitlements`) sans
    conflit selon le compte développeur utilisé pour signer.
  - `+ Capability` → **Push Notifications**.
  - `+ Capability` → **Background Modes** → cocher « Remote notifications ».
- [ ] Si du code a changé depuis l'ouverture de Xcode : relancer `make ios-open` pour
      resynchroniser, puis **Product > Archive** dans Xcode pour produire le build de
      release (pas d'automatisation Makefile pour l'archive elle-même — manuel via Xcode
      par design).
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

## Résumé — ordre d'exécution recommandé

1. **Rust** (§0) — débloque tous les builds mobiles.
2. **Apple Developer** (§1) — débloque Firebase APNs, les variables backend, et Xcode.
3. **Firebase** (§2) + **Backend .env** (§3) — push notifications opérationnelles de bout en
   bout.
4. **Android/Play Store** (§5) — piste la plus rapide, ne dépend d'aucune étape Apple.
5. **iOS** (§6 puis §7) — la plus longue (bug bridging header, capacités Xcode, TestFlight,
   review Apple généralement plus lente que Google).
6. **Tests manuels** (§8) — avant toute communication publique de lancement.
