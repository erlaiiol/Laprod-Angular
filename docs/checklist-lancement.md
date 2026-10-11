# Checklist de lancement — Play Store / App Store / Cloud Console / Firebase / Apple Developer

Ce document recense tout ce qui reste à faire pour publier LaProd sur Android et iOS, dans
l'ordre qui minimise les allers-retours (chaque étape déverrouille la suivante). Le code
(Rust PSOLA, Sign in with Apple, push notifications) est **déjà livré et testé** — tout ce
qui suit est de la configuration externe (comptes, consoles, machine de build) ou des tests
manuels qu'aucun agent ne peut faire à ta place.

Sources : `docs/roadmap.md` (§ 2.11, § 3.9, § Sign in with Apple, § Achats intégrés iOS),
`docs/architecture.md` (§ Paiements sur iOS), `docs/deployment.md` (§ 9),
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
- [x] **Plugins natifs locaux enregistrés** (30/09) : `MainViewController.swift` enregistre
      `PitchMonitorPlugin` et `StoreKitPurchasePlugin`, et `Main.storyboard` pointe dessus.
      `PitchMonitorPlugin` n'était inscrit nulle part jusque-là (absent de
      `packageClassList`, que `cap sync` ne remplit qu'avec les plugins npm) : sur iOS, le
      monitoring vocal aurait échoué avec « not implemented on ios ». **À vérifier sur
      device** au premier lancement (§ 8, Autotune live).
- [ ] `make ios-open` — build mobile + ouvre `ios/App/App.xcodeproj` (pas de
      `.xcworkspace`, SPM pas CocoaPods).
- [ ] Cible `App` → **Signing & Capabilities** : vérifier que **Sign in with Apple**,
      **Push Notifications** et **Background Modes (Remote notifications)** apparaissent
      toutes les trois sans conflit ni bandeau d'erreur de signature (elles devraient être
      déjà cochées, cf. ci-dessus — sinon les rajouter manuellement ici seulement).
      L'achat intégré ne demande **aucune** capacité à cocher (StoreKit 2 est disponible
      par défaut dès que l'App ID a « In-App Purchase », activé d'office).
- [ ] Une fois `GoogleService-Info.plist` glissé et les capacités vérifiées :
      **Product > Archive** dans Xcode pour produire le build de release (pas
      d'automatisation Makefile pour l'archive elle-même — manuel via Xcode par design).
- [ ] Xcode Organizer → **Distribute App** → App Store Connect → upload.

---

## 7. App Store Connect

### 7.1 Achats intégrés — à faire AVANT d'envoyer le premier build en review

Contexte : FactureLe (même architecture : paiements Stripe renvoyés vers le web) a été
refusé par App Review pour vente de produits numériques hors App Store. LaProd avait le
même défaut. Le code est corrigé (`docs/architecture.md` § Paiements sur iOS) ; il reste
ce que seul le titulaire du compte peut faire.

- [ ] **Agreements, Tax, and Banking** : accepter le **Paid Apps Agreement** et renseigner
      coordonnées bancaires + fiscalité. Tant que ce n'est pas « Active », aucun produit
      n'est chargeable, même en Sandbox (`getProducts` renvoie une liste vide et l'app
      affiche des colonnes sans prix ni bouton).
- [ ] **Monetization > In-App Purchases** : créer 3 produits de type
      **Non-Renewing Subscription** (pas « Auto-Renewable » : le modèle LaProd est un
      accès de 30 jours payé une fois, identique au paiement Stripe). Identifiants
      attendus par défaut par `config.py` :

      | Palier | Product ID | Prix de référence (web) |
      |---|---|---|
      | Premium | `net.laprod.app.plus.premium.30d` | 4,99 € |
      | Semi-Pro | `net.laprod.app.plus.semipro.30d` | 12,99 € |
      | Pro Structuré | `net.laprod.app.plus.prostructure.30d` | 49,99 € |

      Pour chacun : nom affiché + description en français, prix (le palier de prix Apple
      le plus proche — il peut différer du web, l'app affiche celui d'Apple), et une
      **capture d'écran pour la review** (la page Premium de l'app). Un Product ID ne se
      réutilise jamais, même après suppression : si tu en choisis d'autres, reporte-les
      dans `.env` (`APPLE_IAP_PRODUCT_*`).
- [ ] Noter l'**Apple ID numérique** de l'app (App Information) → `.env` du serveur :
      `APPLE_APP_ID=<nombre>`, puis `docker compose -f docker-compose.yml up -d web` (recrée le conteneur avec le nouveau `.env`). Vérifier avec
      `./doctor.sh --prod` (ligne « APPLE_APP_ID défini »).
- [ ] **App Information > App Store Server Notifications** : renseigner
      `https://laprod.net/api/apple-iap/notifications` en **Version 2**, pour Production
      **et** Sandbox. Sans ça, un remboursement accordé par Apple ne retire pas
      l'abonnement.
- [ ] **Users and Access > Sandbox > Test Accounts** : créer un testeur Sandbox (adresse
      email jamais utilisée comme compte Apple).
- [ ] Appliquer la migration : elle part toute seule au déploiement (`entrypoint.sh` →
      `flask db upgrade`, révision `c4e8a1f07b52`, table `apple_iap_transaction`).
- [ ] Sur la fiche de la **version** soumise, section « In-App Purchases and
      Subscriptions » : **joindre les 3 produits** à la version. Un premier achat intégré
      doit être soumis *avec* un build ; oublié, il reste en « Ready to Submit » et la
      review échoue faute de produit chargeable.

### 7.2 Notes pour App Review — à coller dans « App Review Information > Notes »

Le reviewer doit trouver sans chercher : un compte de test, où est l'achat intégré, et
pourquoi le reste passe par un autre moyen de paiement. Texte proposé (en anglais, c'est
la langue de la review) :

```
TEST ACCOUNT
Email: <compte de démo>   Password: <mot de passe>

IN-APP PURCHASE
LaProd+ (Premium / Semi-Pro / Pro Structuré) is sold exclusively through In-App
Purchase in this app: Profile > LaProd+ (or any "Premium" prompt). These are
non-renewing subscriptions (30 days). "Restaurer mes achats" restores them, and
they are also tied to the user's LaProd account, so they follow the user across
devices. The app contains no link or reference to any other way of buying LaProd+.

OTHER PAYMENTS (guideline 3.1.3(e))
LaProd is a marketplace between independent music producers, artists and sound
engineers. Two kinds of transactions between users are paid by card:
1. Beat licences: a signed licence contract granting the buyer the right to
   commercially exploit a third-party producer's instrumental OUTSIDE the app
   (recording, streaming platforms, live shows). The buyer downloads the audio
   files and the contract to use them in their own production software. Nothing
   is unlocked inside the app.
2. Mixing / mastering orders: a service performed by a human sound engineer on
   the customer's own recording and delivered as files.
The seller receives the funds; LaProd only takes a marketplace commission.
```

- [ ] Compléter le compte de démo (un compte **gratuit**, pour que le reviewer voie les
      boutons d'achat) et coller le texte.
- [ ] **Si App Review conteste les licences ou le mix/master** : ne pas argumenter en
      boucle. Passer la catégorie à `unavailable` dans `.env`
      (`IOS_POLICY_BEAT_LICENSE=unavailable` et/ou `IOS_POLICY_MIX_ORDER=unavailable`),
      `docker compose -f docker-compose.yml up -d web` (recrée le conteneur avec le nouveau `.env`), et répondre dans le Resolution Center que ces achats ne
      sont plus proposés dans l'app — **aucun nouveau build n'est nécessaire**. L'app
      affiche alors une mention neutre à la place du bouton de paiement.
- [ ] **Ne jamais faire l'inverse** : repasser une catégorie à `stripe` après validation
      activerait un paiement qu'Apple n'a pas vu, motif de retrait de l'app (2.3.1).
      Tout assouplissement repasse par une review, avec des notes qui l'annoncent.

### 7.3 Fiche et soumission

- [ ] **Description, texte promotionnel, captures d'écran** : aucune mention de prix
      « sur le site », de Stripe, ni d'invitation à s'abonner ailleurs que dans l'app.
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
- [ ] **Achat intégré LaProd+, iOS** (compte Sandbox, build TestFlight ou Xcode) :
      - la page Premium affiche les prix **Apple** et « / 30 jours », aucun mot « Stripe » ;
      - achat d'un palier → feuille Apple → palier actif immédiatement, expiration à J+30
        (`apple_iap_transaction` : une ligne, `environment = Sandbox`) ;
      - second achat avant expiration → expiration repoussée de 30 jours, pas remise à J+30 ;
      - fermer la feuille d'achat → aucun message d'erreur ;
      - « Restaurer mes achats » sur un compte déjà crédité → « Aucun achat à restaurer »,
        expiration inchangée ;
      - se connecter avec un **autre** compte LaProd sur le même iPhone puis restaurer →
        rien n'est crédité sur ce second compte ;
      - couper le réseau juste après le paiement, relancer l'app, rouvrir la page Premium →
        l'abonnement est rattrapé tout seul.
- [ ] **Aucune fuite vers Stripe pour l'abonnement, iOS** : parcourir les écrans qui
      poussent vers le Premium (contract builder, codes promo, campagnes, statistiques de
      vues, studio mobile) → tous mènent à la page Premium de l'app, jamais au navigateur.
- [ ] **Campagnes, iOS** : l'option « diffusion payante » n'affiche ni prix ni bouton de
      paiement.
- [ ] **Web et Android** : parcours d'abonnement Stripe inchangé (non-régression).
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
- ✅ **Conformité paiements iOS (30/09/2026)** : l'abonnement LaProd+ passe par l'achat
  intégré Apple dans l'app iOS, plus aucun chemin vers Stripe pour un abonnement
  (code + tests livrés). ⚠️ Reste manuel : Paid Apps Agreement, création des 3 produits,
  `APPLE_APP_ID` en prod, URL de notifications, notes de review (§7.1–7.2), et un vrai
  achat Sandbox sur device (§8) — le code Swift compile mais n'a jamais affiché une
  feuille d'achat.

Ordre recommandé à partir de maintenant : §3 (répliquer `.env` en prod, si pas déjà fait) →
§5 (rebuild Android) en parallèle de → §6 (Xcode : glisser le plist, vérifier les
capacités, archiver, uploader) → §7 (App Store Connect) → §8 (tests manuels).
