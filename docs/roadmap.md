# Roadmap

---

## Comment exécuter cette roadmap

Chaque chantier est découpé en **passes**. Une passe = une session de travail = une
branche = une PR. La spécification vit **ici**, pas dans le prompt : le prompt reste
court et référentiel, et la spécification reste relisible, versionnée et amendable.

Prompt type à coller pour lancer une passe :

```
Implémente docs/roadmap.md § Chantier 1 — Passe 1.

Contraintes : docs/development-rules.md, docs/api.md, docs/conventions.md.
Le raisonnement produit est dans docs/positioning.md — s'il contredit la spec,
signale-le avant d'écrire du code.

Relis d'abord : utils/plans.py, utils/money.py, utils/wallet_service.py,
utils/recommendation_service.py, routes/tracks_api.py (get_tracks),
models.py (Wallet, WalletTransaction, TrackView, Track),
src/app/pages/home/home.component.ts.

Livre la passe complète : modèles + migration, service, routes, front, tests
(pytest + Vitest), entrée updates.json. Liste en fin de réponse ce que tu as
volontairement laissé de côté et pourquoi.
```

Règles de découpage qui rendent une passe exécutable en une seule session :

1. Une passe touche **un** domaine métier et livre une valeur utilisable de bout en bout
   (base → API → UI → test). Pas de passe « backend seulement » qui ne se voit nulle part.
2. Les décisions structurantes (nom des tables, forme des réponses, invariants) sont
   **écrites dans la roadmap avant**, pas décidées en cours d'implémentation.
3. Les pièges connus sont listés dans la passe. Un agent qui découvre le piège à
   l'exécution perd la session ; un agent qui le lit avant l'évite.
4. Les critères d'acceptation sont vérifiables mécaniquement.

---

# Chantier 1 — Régie interne (« Mise en avant »)

**Objectif** : couvrir le coût d'infrastructure par un revenu endogène, sans régie tierce,
sans cookie publicitaire, sans modification de la CSP, sans toucher aux pages légales
autrement que pour être plus transparent.

## 1.1 Décision : pourquoi pas une régie tierce

| | Régie tierce (AdSense / programmatique) | Régie interne (mise en avant vendue aux vendeurs) |
|---|---|---|
| Revenu au trafic actuel | RPM 1–3 € en France ⇒ il faut ~30 000 pages vues/mois pour 60 € | 12 mises en avant à 4,99 € = 60 € |
| Annonceur | À conquérir, aucun lien avec LaProd | Déjà inscrit, déjà solvable, **déjà crédité** sur un wallet interne |
| Blocage | 35–45 % de bloqueurs sur une audience jeune et technique | Aucun : c'est du contenu de la plateforme |
| Coût réglementaire | CMP obligatoire, réécriture de `/cookies`, `/privacy` | Une clause de transparence de classement (P2B) à ajouter aux CGU |
| Coût technique | Ouvrir `script-src` / `frame-src` / `connect-src` à des tiers ; SDK séparé pour le WebView Capacitor | Zéro dépendance externe |
| Coût de marque | Contredit mot pour mot la page `/cookies` publiée | Renforce le discours : le vendeur investit dans sa propre visibilité |
| Mesure | Métriques d'un tiers, non reliées aux ventes | Impression → clic → **achat attribué**, dans la même base |

La différence de rendement n'est pas marginale, elle est structurelle : une impression
publicitaire générique vaut ~0,002 €, une impression de beat montrée à quelqu'un qui est
venu acheter un beat vaut deux ordres de grandeur de plus. Le trafic de LaProd est petit
mais **entièrement qualifié** — c'est le seul actif publicitaire qu'elle possède, et une
régie tierce le revend à sa place, au tarif du trafic générique.

Décision : **régie interne**. Régie tierce écartée définitivement (cf. `docs/positioning.md` § 5).

## 1.2 Les trois sources de revenu, par ordre de mise en œuvre

| # | Source | Passe | Revenu attendu | Effort commercial |
|---|---|---|---|---|
| 0 | **Auto-promotion** (house ads) — LaProd promeut Premium / Contract Builder sur son propre inventaire invendu | 1 | Indirect (conversion abonnement) | Nul |
| 1 | **Boost vendeur** — un vendeur paie pour que son beat apparaisse dans les emplacements sponsorisés | 1 | ~5 €/boost, cible 12–20/mois | Nul (auto-service) |
| 2 | **Partenaires B2B** — écoles MAO, marques de plugins, distributeurs, studios : emplacement mensuel forfaitaire ou lien d'affiliation | 2 | 30–80 €/mois par partenaire | Vente directe, quelques emails |

La source 0 est livrée **en premier** volontairement : elle valide le moteur sans aucun
risque de facturation, elle remplit l'inventaire invendu dès le premier jour, et elle
rapporte réellement — un abonnement Premium déclenché vaut 4,99 €/mois récurrents, soit
plus qu'un boost ponctuel.

---

## Passe 1 — Moteur de diffusion + Boost auto-service

### Périmètre

Un vendeur achète depuis son dashboard une **mise en avant de 7 ou 30 jours** sur un de
ses beats, payée par son wallet ou par carte. Le beat apparaît alors, clairement signalé
« Sponsorisé », dans deux emplacements de la grille du catalogue, en rotation avec les
autres mises en avant actives et avec les auto-promotions LaProd. Le vendeur voit ses
impressions et ses clics.

### Modèles (`models.py` + migration Alembic)

```python
class PromotionKind(enum.Enum):
    BOOST = 'boost'    # un vendeur met en avant un de ses beats
    HOUSE = 'house'    # auto-promotion LaProd (owner_id NULL, track_id NULL)

class PromotionPlacement(enum.Enum):
    CATALOG = 'catalog'   # grille home / catalogue — seul emplacement de la passe 1

class PromotionStatus(enum.Enum):
    SCHEDULED = 'scheduled'   # payée, fenêtre de diffusion pas encore ouverte
    ACTIVE    = 'active'
    FINISHED  = 'finished'
    BLOCKED   = 'blocked'     # coupée par un admin (modération)
    REFUNDED  = 'refunded'    # remboursée (beat supprimé / vendu en exclusivité)
```

`Promotion` :

| Colonne | Type | Notes |
|---|---|---|
| `owner_id` | FK `user`, **nullable** | `NULL` ⇒ auto-promotion LaProd |
| `track_id` | FK `track`, nullable, `ondelete='CASCADE'` | `NULL` pour une créative maison |
| `kind`, `placement`, `status` | String + `CheckConstraint` | valeurs des enums ci-dessus |
| `starts_at`, `ends_at` | DateTime, non null | fenêtre de diffusion |
| `price_paid` | `Numeric(10,2)`, nullable | `NULL` pour `HOUSE` |
| `wallet_transaction_id` | FK `wallet_transaction`, nullable | paiement par solde |
| `stripe_payment_intent_id` | String(200), **unique**, nullable | paiement carte |
| `house_title`, `house_body`, `house_target_url`, `house_image` | String/Text, nullable | créative maison uniquement |
| `impressions`, `clicks` | Integer, default 0 | compteurs agrégés, alimentés par le job de flush |
| `created_at` | DateTime | |

Index : `(status, starts_at, ends_at)`, `(owner_id, status)`.
Cascade : `cascade='all, delete-orphan'` sur les backrefs `user.promotions` et
`track.promotions` (cf. R9).

`PromotionDailyStat` : `promotion_id`, `day` (Date), `impressions`, `clicks`,
`UniqueConstraint('promotion_id', 'day')`.

**Pourquoi pas une ligne par impression** : à 2 emplacements par page de catalogue, le
volume d'impressions dépasse celui de `track_view` sans porter la moindre information
individuelle utile. Les impressions sont comptées dans Redis
(`laprod:ads:imp:{promotion_id}:{YYYY-MM-DD}`, INCR) et agrégées toutes les 5 minutes dans
`PromotionDailyStat` par un job. Aucune donnée personnelle n'est stockée pour une
impression — c'est ce qui garde la page `/cookies` vraie.

### Tarification (`utils/ads_pricing.py`, source unique)

```python
BOOST_PACKAGES = {
    '7d':  {'days': 7,  'price': Decimal('4.99'),  'price_premium': Decimal('3.99')},
    '30d': {'days': 30, 'price': Decimal('14.99'), 'price_premium': Decimal('11.99')},
}
```

- Le tarif réduit s'obtient par `plans.plan_rank(user.subscription_plan) >= plans.plan_rank(plans.PREMIUM)` — jamais par comparaison littérale (R1).
- **On vend une durée, pas un nombre d'impressions.** Vendre un volume créerait une
  obligation de résultat impossible à tenir au trafic actuel. Le nombre d'impressions est
  restitué *a posteriori*, jamais promis.
- Tous les paliers, y compris FREE, peuvent acheter. Le palier joue sur le prix, pas sur
  l'accès : LaProd ne bride pas quelqu'un qui veut lui payer quelque chose.

### Moteur de sélection (`utils/ads_service.py`)

```python
SPONSORED_PER_PAGE = 2          # positions 3 et 11 dans une grille de 20
MAX_IMPRESSIONS_PER_VIEWER_DAY = 5   # par promotion et par spectateur
```

`pick_promotions(viewer_id, placement, exclude_track_ids, n) -> list[Promotion]`

Éligibilité — une promotion est écartée si :
- sa fenêtre n'est pas ouverte, ou `status != ACTIVE` ;
- son beat n'est plus `is_approved`, ou est passé `is_exclusive_sold` ;
- le spectateur en est le propriétaire ;
- le spectateur a déjà acheté ce beat ;
- le beat est déjà présent dans la page courante (`exclude_track_ids`) ;
- le plafond de fréquence est atteint (`laprod:ads:seen:{viewer_key}:{promotion_id}`, TTL 24 h).

Sélection — tirage aléatoire pondéré sans remise, **une seule promotion par vendeur et
par page** :

```
affinity  = score_track(track, user_vector) normalisé sur [0, 1]   # 0.5 si visiteur anonyme
weight    = (0.5 + affinity) / sqrt(1 + impressions_du_jour)
```

Le terme d'affinité réutilise `utils/recommendation_service.py::score_track` et le vecteur
déjà en cache : la mise en avant est **ciblée par le goût, pas subie**. Le dénominateur
est le pacing : une promotion très diffusée aujourd'hui cède la place aux autres, ce qui
lisse la diffusion sur toute la durée achetée sans avoir à gérer un objectif d'impressions.

Si le nombre de promotions éligibles est inférieur à `n`, on complète par des
auto-promotions (`kind=HOUSE`) — l'inventaire n'est jamais vide, et un utilisateur FREE
voit une invitation Premium plutôt qu'un trou.

### API (`routes/ads_api.py`)

| Route | Auth | Description |
|---|---|---|
| `GET /api/ads/slots?placement=catalog&exclude=1,2,3` | optionnelle | Renvoie ≤ 2 emplacements, chacun avec `promotion_id`, un `track_card(...)` (ou la créative maison), le libellé `Sponsorisé` et un **`token`** signé |
| `POST /api/ads/impressions` | optionnelle, `limiter` | Corps : `{"tokens": ["…"]}`. INCR Redis. Rien d'autre |
| `POST /api/ads/click` | optionnelle, `limiter` | Corps : `{"token": "…"}`. INCR Redis, 204 |
| `GET /api/ads/pricing` | JWT | Grille tarifaire pour l'utilisateur courant (tarif réduit appliqué) |
| `POST /api/ads/boost` | JWT | `{track_id, package}` → débit wallet, ou `{"checkout_url": …}` si le solde est insuffisant |
| `GET /api/ads/mine` | JWT | Mes mises en avant, avec impressions / clics |
| `POST /api/ads/<id>/cancel` | JWT | Arrêt anticipé, sans remboursement (à annoncer clairement dans l'UI) |

Le `token` est signé avec `itsdangerous` (même approche que l'invitation de signature de
contrat), TTL 30 min, et contient `promotion_id` + un identifiant de rendu. **Sans lui,
n'importe qui peut gonfler les compteurs d'une promotion par une boucle `curl`** et les
statistiques vendues au vendeur ne valent plus rien.

**Endpoint séparé, et non injection dans `GET /api/tracks`** : `get_tracks` porte la
logique délicate de snapshot de pagination des recommandations (R5), et un tableau paginé
ne doit contenir que ce qui est compté dans `total` (R6). Un appel distinct coûte un
aller-retour et supprime les deux risques.

### Paiement

Ordre de priorité : **wallet d'abord**, carte en repli.

```python
# Débit wallet — rappel des contraintes en base (R3)
wallet = db.session.execute(
    select(Wallet).where(Wallet.user_id == user.id).with_for_update()
).scalar_one_or_none()
# amount > 0 obligatoire, type = 'debit_ad_spend', status = 'spent'
# balance_available >= 0 est une CheckConstraint : attraper IntegrityError
# et répondre err('Solde insuffisant', code='INSUFFICIENT_BALANCE')
```

Seul le solde `available` est dépensable, jamais le `pending`. Si le solde est
insuffisant, on renvoie une `checkout_url` Stripe construite comme dans
`routes/premium_api.py::subscribe`, et la promotion n'est créée qu'à la confirmation.

Le wallet-first est l'atout décisif de ce chantier : le vendeur dépense de l'argent qu'il
n'a pas encore retiré, la friction est nulle, et la somme ne quitte jamais LaProd.

### Front

| Fichier | Rôle |
|---|---|
| `src/app/services/ads.service.ts` | `getSlots()`, `reportImpressions()`, `reportClick()`, `getPricing()`, `buyBoost()`, `getMine()` |
| `src/app/components/sponsored-card/` | Enveloppe `TrackCardComponent` + pastille « Sponsorisé » |
| `src/app/pages/home/home.component.ts` | Appel `getSlots()` après le chargement des tracks ; injection aux positions 3 et 11 |
| `src/app/pages/dashboard/dashboard-beatmaker/` | Onglet « Mise en avant » : acheter, suivre, arrêter |

- Comptage d'impression : `IntersectionObserver`, seuil 50 % visible pendant 1 s, mis en
  file et envoyé en lot (`navigator.sendBeacon` sur `visibilitychange`). Une carte
  sponsorisée jamais vue à l'écran ne compte pas — c'est la définition qu'on affichera au
  vendeur.
- La pastille « Sponsorisé » est **non masquable**, en `v.$gold`, avec une infobulle :
  « Mise en avant payée par le vendeur. Elle n'affecte ni le prix, ni les autres résultats. »
  (obligation d'identification, cf. `docs/positioning.md` § 4.3).
- Aucune carte sponsorisée en position 1, aucune sur une page de résultats vide, jamais
  deux du même vendeur sur la même page.

### Jobs

- `utils/ads_jobs.py::flush_ad_counters()` — toutes les 5 min (APScheduler) : Redis →
  `PromotionDailyStat` + compteurs agrégés de `Promotion`.
- `utils/ads_jobs.py::sync_promotion_statuses()` — toutes les heures :
  `SCHEDULED → ACTIVE → FINISHED`, et bascule en `REFUNDED` (avec recrédit wallet au
  prorata) toute promotion dont le beat a été supprimé ou vendu en exclusivité.

### Conformité — inclus dans la passe, pas après

- `/cgu` : clause de transparence de classement — « le catalogue peut comporter des
  emplacements de mise en avant payés par les vendeurs, toujours signalés ; le paiement
  n'influence ni le classement des autres résultats, ni les prix » (règlement UE 2019/1150, art. 5).
- `/cookies` : reste **vrai sans modification** — aucune donnée personnelle n'est stockée
  pour une impression. Le vérifier explicitement en relisant la page.
- `/privacy` : mentionner la mesure agrégée des mises en avant.
- `updates.json` : une entrée `feature`, audience `beatmakers`.

### Critères d'acceptation

- [ ] Un vendeur achète un boost 7 j depuis son dashboard, payé par son wallet ; le solde
      décroît du montant exact, une `WalletTransaction` positive de type `debit_ad_spend` existe.
- [ ] Solde insuffisant ⇒ `checkout_url` Stripe, aucune promotion créée avant confirmation.
- [ ] La grille du catalogue affiche au plus 2 cartes sponsorisées, en positions 3 et 11,
      chacune portant la pastille « Sponsorisé ».
- [ ] Le propriétaire d'un beat ne voit jamais sa propre mise en avant.
- [ ] Un acheteur ne revoit pas en sponsorisé un beat qu'il a déjà acheté.
- [ ] Aucun doublon entre le tableau `tracks` et les emplacements sponsorisés d'une même page.
- [ ] `pagination.total` est identique avec et sans mises en avant actives.
- [ ] Inventaire payant vide ⇒ auto-promotion affichée ; jamais d'emplacement vide.
- [ ] Un `POST /api/ads/impressions` avec un token forgé ou expiré est rejeté sans incrémenter.
- [ ] Un beat vendu en exclusivité pendant sa mise en avant cesse d'être diffusé dans l'heure.
- [ ] Tarif réduit appliqué à partir de PREMIUM, obtenu via `plan_rank`.
- [ ] Tests pytest : éligibilité, pondération, plafond de fréquence, débit wallet
      (dont solde insuffisant), validité du token. Tests Vitest : injection aux bonnes
      positions, présence de la pastille, envoi groupé des impressions.

### Pièges de cette passe

1. `WalletTransaction.amount > 0` en base : un débit **n'est pas** un montant négatif (R3).
2. `Wallet.balance_available >= 0` : la contrainte lève une `IntegrityError`, elle ne
   renvoie pas un solde négatif. L'attraper et répondre proprement.
3. Ne pas injecter les mises en avant dans le tableau `tracks` (R5, R6).
4. Ne pas stocker d'`user_id` sur une impression — c'est ce qui ferait basculer la page
   `/cookies` dans le faux.
5. Enum PostgreSQL : créer le type dans la migration avant la colonne (R15).
6. `home.component.ts` : l'appel aux emplacements ne doit pas entrer dans les dépendances
   de l'`effect()` de filtres — `untracked()` (R11).
7. Pastille « Sponsorisé » sur toutes les tailles de carte (`list`, `gallery`, `compact`)
   et dans les deux thèmes.

---

## Passe 2 — Mesure, attribution, régie partenaires

### Périmètre

Rendre le boost *démontrable* (donc rachetable), et ouvrir l'inventaire à des annonceurs
extérieurs sans introduire la moindre dépendance tierce.

### Attribution

- `PromotionClick` : `promotion_id`, `user_id` (nullable), `created_at`. Contrairement à
  l'impression, le clic est rare et porte une intention — il mérite une ligne.
- Un achat du beat mis en avant par un utilisateur ayant cliqué dans les **7 jours**
  précédents est attribué à la promotion. Même philosophie que l'attribution des campagnes
  par code promo (`utils/campaign_service.py`) : on mesure une conversion réelle, pas un
  taux d'affichage décoratif.
- Restitution vendeur : « 1 240 impressions · 38 clics · **3 ventes attribuées · 34,80 € »**,
  avec le coût du boost en regard. C'est cette ligne qui déclenche le rachat.
- `/privacy` : la conservation du clic (90 jours) doit y être décrite.

### Régie partenaires

- `PromotionKind.PARTNER` : créative maison uniquement — image téléversée dans
  `db_assets/`, titre, corps, URL cible. **Aucun script tiers, aucune iframe** : la CSP
  reste inchangée (R10).
- Liens sortants en `rel="sponsored nofollow"`, `target="_blank"`, domaine visible sur la carte.
- Facturation mensuelle via `utils/invoice_generator.py`.
- Prospects naturels : écoles de MAO, marques de plugins, distributeurs (programmes
  d'affiliation), magasins d'instruments, studios locaux. Un partenaire à 50 €/mois couvre
  l'infrastructure à lui seul.
- Modération obligatoire : toute créative partenaire est validée par un admin avant
  diffusion (`status=SCHEDULED` tant qu'elle ne l'est pas).

### Enchère légère — **seulement si l'inventaire sature**

Tant que le taux de remplissage payant reste sous ~70 %, le forfait à la durée est le bon
outil : lisible, sans surprise, sans comptabilité au clic. Au-delà, passer à un CPM au
second prix avec budget quotidien et pacing. **Ne pas construire l'enchère avant que la
métrique de remplissage la justifie** — c'est la sur-ingénierie classique de ce type de
système.

### Admin — onglet « Régie »

Taux de remplissage, chiffre d'affaires du mois, top promotions, modération des créatives,
coupure d'urgence d'une promotion (`status=BLOCKED`), et **interrupteur global** de la
régie (feature flag) permettant de tout éteindre sans déploiement.

### Confort utilisateur

- Plafond de fréquence global, tous annonceurs confondus, par spectateur et par jour —
  dans l'esprit du plafond de fréquence subie des campagnes.
- Lien « Pourquoi cette mise en avant ? » sur chaque carte sponsorisée, expliquant en une
  phrase la raison (affinité de style) et renvoyant à la clause CGU.

### Critères d'acceptation

- [ ] Un clic suivi d'un achat sous 7 jours apparaît en « vente attribuée » côté vendeur.
- [ ] Une créative partenaire non modérée n'est jamais diffusée.
- [ ] Aucun domaine ajouté à `$csp` par rapport à l'état actuel.
- [ ] L'interrupteur global éteint toute la régie sans redéploiement.
- [ ] L'onglet admin affiche un taux de remplissage cohérent avec les stats journalières.

---

## 1.3 Décisions actées

| Décision | Motif |
|---|---|
| Régie interne, jamais tierce | `docs/positioning.md` § 2.1, § 2.2 |
| On vend une **durée**, pas des impressions | Pas d'obligation de résultat au trafic actuel |
| Emplacement séparé du tableau paginé | R5, R6 |
| Paiement wallet en priorité | Friction nulle, l'argent reste sur la plateforme |
| Accessible à tous les paliers, prix réduit dès Premium | Cohérent avec « fidélité, pas agressivité » |
| Auto-promotion en remplissage de l'invendu | Aucun emplacement vide, conversion Premium |
| Pas de suppression de publicité vendue comme avantage Premium | Créerait une incitation à dégrader le gratuit |
| Enchère reportée tant que le remplissage < 70 % | Sur-ingénierie |

---

# Chantier 2 — Notifications push de réactivation

**Objectif** : relancer, via une notification push mobile, un utilisateur qui n'a pas
rouvert l'application depuis longtemps — sur le fond éditorial déjà validé par les emails
de re-engagement (`utils/email_service.py::send_reengagement_*_email`), sur un canal que
l'email ne couvre pas.

## 2.1 Décision : mobile natif uniquement, jamais de push web

Le test de cohérence de `docs/positioning.md` § 4 s'applique ici avec une tension réelle
sur sa question 4 (« survit sans dépendance tierce ? ») : Firebase Cloud Messaging **est**
un service tiers. La différence avec une régie publicitaire tierce (écartée en
`docs/positioning.md` § 5) est structurelle, pas cosmétique, et elle fixe le périmètre :

| | Push web (Firebase JS SDK + Service Worker) | Push mobile (Capacitor natif) |
|---|---|---|
| Ce qui transite par Firebase | Payload de notification **et** un script JS chargé dans le navigateur | Un jeton d'appareil + le payload, côté OS, hors du contexte web |
| Impact CSP | `script-src`/`connect-src` à rouvrir vers des domaines Google (`docs/positioning.md` § 2.2) | Aucun — le WebView Capacitor n'est pas concerné par la CSP nginx |
| Impact `/cookies` | Un Service Worker + `Notification.requestPermission()` sont un mécanisme de tracking web au sens où la page le décrit | Aucun cookie, aucun script web : c'est le canal natif Android/iOS de mise en relation appareil↔app, au même titre que le fait qu'iMessage ou Gmail envoient des push sans que ça constitue un cookie tiers |
| Donnée envoyée à Google | Comportement de navigation associable à un profil web | Un jeton opaque, sans donnée personnelle, généré et révocable par l'OS |

Décision : **`@capacitor-firebase/messaging` sur Android et iOS uniquement. Aucun push
web, aucun Service Worker, aucun SDK Firebase chargé dans le navigateur.** C'est la même
logique que Stripe.js (déjà en liste blanche CSP) : une dépendance tierce strictement
nécessaire à une fonction que rien de « self » ne peut fournir, pas une dépendance de
tracking. `/cookies` reste vrai sans modification — vérifié explicitement (R17).

**Correction en cours de passe** : la spec initiale prévoyait `@capacitor/push-notifications`
(déjà en dépendance, jamais câblé). Ce plugin core ne renvoie qu'un **jeton APNs brut**
sur iOS — pas un jeton FCM — ce qui aurait forcé le backend à gérer deux chemins d'envoi
distincts (FCM pour Android, APNs HTTP/2 direct pour iOS). `@capacitor-firebase/messaging`
(capawesome-team, compatible Capacitor 8) renvoie un vrai jeton FCM sur les deux
plateformes : un seul `utils/push_service.py::send_push()` suffit. `@capacitor/push-notifications`
a été retiré de `package.json` au profit de ce plugin ; le SDK JS `firebase` qu'il embarque
comme peer dependency n'est **jamais importé statiquement** côté web — import dynamique
gardé par `Capacitor.isNativePlatform()`, pour ne pas peser sur le budget verrouillé à
850 kB de la configuration `production` (`angular.json`). Vérifié par build : le chunk
contenant `firebase` n'apparaît que dans les *lazy chunks*, jamais dans l'initial.

## 2.2 Décision : le signal d'inactivité est la connexion, pas l'activité de rôle

Les emails de re-engagement (`utils/scheduled_tasks.py::run_reengagement_emails`,
mercredi 10h) déclenchent sur une inactivité **de contenu** par rôle : pas d'upload
(beatmaker), pas d'écoute (artiste), pas de demande reçue (ingénieur) depuis 7 jours,
dédupliqué par semaine ISO via `UserNotificationLog`.

La demande ici est différente : « quand l'utilisateur ne se connecte plus », c'est-à-dire
un signal de **connexion**, pas de contenu. Le modèle `LoginEvent` existe déjà exactement
pour ça (`models.py:1333`, dédupliqué par jour calendaire, alimenté à `password`, `oauth`
et `refresh` — donc y compris les sessions « se souvenir de moi » qui ne repassent jamais
par `/login`). Utiliser `MAX(LoginEvent.login_date)` par utilisateur comme date de
dernière connexion, plutôt que dupliquer un signal d'activité par rôle : c'est la table
qui porte déjà cette information (`utils/behavior_stats.py` l'agrège pour l'admin), et le
push et l'email mesurent alors deux choses volontairement différentes — l'un « vous ne
créez plus », l'autre « vous n'êtes même plus venu ».

Seuil retenu : **14 jours sans connexion**, plus long que le seuil email (7 jours). Un
push est plus intrusif qu'un email (notification système, pas une ligne dans une boîte de
réception) : il justifie un seuil plus tardif, cohérent avec `docs/positioning.md` § 2.4
(pas d'urgence fabriquée, pas de sursollicitation).

## 2.3 Modèles (`models.py` + migration Alembic)

```python
class DeviceToken(db.Model):
    """Un jeton FCM par appareil enregistré. Un utilisateur peut en avoir plusieurs
    (téléphone + tablette). Le jeton change quand l'app est réinstallée ou que l'OS
    le fait tourner — c'est normal, l'ancien est simplement désactivé (R4-like : ne
    jamais supposer qu'un jeton reste valide indéfiniment)."""
    __tablename__ = 'device_token'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token      = db.Column(db.String(255), nullable=False, unique=True)
    platform   = db.Column(db.String(10), nullable=False)   # 'android' | 'ios'
    is_active  = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    __table_args__ = (
        db.Index('idx_device_token_user_active', 'user_id', 'is_active'),
    )
```

Cascade : `cascade='all, delete-orphan'` sur le backref `user.device_tokens` (R9 — FK
`NOT NULL` vers `user`).

`User` (`models.py`, à côté de `marketing_opt_in` / `marketing_opt_in_at`, même forme) :

```python
push_opt_in    = db.Column(db.Boolean, default=False, nullable=False)
push_opt_in_at = db.Column(db.DateTime, nullable=True)
```

**Opt-in non rétroactif**, même principe que `marketing_opt_in`
(cf. mémoire campagnes juillet 2026) : `push_opt_in` démarre à `False` pour tout le monde,
y compris les comptes existants. Un utilisateur qui accorde la permission OS
(`PushNotifications.requestPermissions()`) sans avoir explicitement activé le réglage
côté app ne doit **pas** recevoir de push de réactivation — la permission OS autorise
techniquement l'envoi, elle ne vaut pas consentement produit. Les deux sont vérifiés
avant tout envoi.

Dédup : réutiliser `UserNotificationLog` (`models.py:2096`) avec
`notification_type='push_reengagement'` et `period_key` mensuel (`'%Y-%m'`) — plus long
que la clé hebdomadaire des emails, cohérent avec le seuil de 14 jours.

## 2.4 Service (`utils/push_service.py`)

```python
MAX_PUSH_PER_USER_PER_30_DAYS = 1   # un seul push de réactivation par mois glissant, tous rôles confondus
REENGAGEMENT_INACTIVITY_DAYS  = 14
```

`send_push(user_id, title, body, link=None) -> bool` :
- Ne fait rien si `not user.push_opt_in` ou aucun `DeviceToken` actif — retour silencieux,
  jamais d'exception remontée à l'appelant (même discipline que R4 pour Redis : l'envoi
  push est un best-effort, jamais un chemin bloquant).
- Envoie via `firebase_admin.messaging.send_multicast` (paquet `firebase-admin`, à ajouter
  à `pyproject.toml`) sur tous les jetons actifs de l'utilisateur.
- Un jeton qui répond `UNREGISTERED` ou `INVALID_ARGUMENT` est marqué `is_active=False` —
  **ne pas le supprimer** : Firebase ne renouvelle pas toujours immédiatement, une
  suppression prématurée reperd un appareil valide plus tard.
- `title` ≤ 50 caractères pour rester cohérent avec la contrainte existante de
  `Notification.title` (`models.py:1435`) si le contenu est dupliqué en notification
  in-app (facultatif cette passe, cf. critères d'acceptation).

Identifiants Firebase : `FIREBASE_CREDENTIALS_JSON` (contenu du service account, pas un
chemin de fichier — cohérent avec le fait que `db_assets/` et le dépôt ne portent aucun
secret) dans `.env`, jamais committé. `google-services.json` (Android) et
`GoogleService-Info.plist` (iOS) sont des identifiants de **projet**, pas des secrets :
ils peuvent être committés dans `android/app/` et `ios/App/App/`.

## 2.5 Job (`utils/scheduled_tasks.py::run_reengagement_push`)

Nouvelle fonction, **pas une extension de `run_reengagement_emails`** : les deux canaux
ont des seuils, une cadence de dédup et une audience (opt-in) différents ; les fusionner
forcerait l'un des deux seuils à céder. Enregistrée dans `extensions.py::init_scheduler`
à côté des jobs existants — proposition : chaque vendredi 11h (après le job email du
mercredi, pour ne jamais superposer les deux canaux le même jour).

```
Pour chaque user avec push_opt_in=True et au moins un DeviceToken actif :
    last_login = MAX(LoginEvent.login_date) pour ce user  (None si jamais de LoginEvent après migration)
    si last_login existe et last_login > aujourd'hui - 14j : passer
    si déjà notifié ce mois (UserNotificationLog, 'push_reengagement') : passer
    choisir le texte selon le rôle principal (is_beatmaker / is_artist / is_mix_engineer),
      repris des tips de utils/email_service.py::_TIPS_BEATMAKER etc., condensés
    send_push(...) ; logger dans UserNotificationLog
```

Requête `MAX(login_date)` par utilisateur : agréger en une seule requête groupée
(`db.session.query(LoginEvent.user_id, func.max(LoginEvent.login_date)).group_by(...)`)
plutôt qu'une requête par utilisateur dans la boucle — le job email actuel interroge par
utilisateur parce que les tables concernées sont différentes par rôle, mais `LoginEvent`
est unique et se prête à un pré-calcul en dictionnaire avant la boucle (variante de R8 :
pas de requête individuelle évitable dans une boucle, même hors relation ORM).

## 2.6 API (`routes/push_api.py`, nouveau blueprint `push_api_bp`)

| Route | Auth | Description |
|---|---|---|
| `POST /api/push/register` | JWT | `{token, platform}` → upsert `DeviceToken` (même jeton réenregistré = `last_seen_at` mis à jour, pas de doublon grâce à `token` unique) |
| `POST /api/push/unregister` | JWT | `{token}` → `is_active=False`. Appelé au logout et à la désactivation du réglage |
| `POST /api/push/preference` | JWT | `{enabled: bool}` → `push_opt_in` + `push_opt_in_at` si passage à `True` (preuve horodatée, même principe que `marketing_opt_in_at`). Si passage à `False`, désactiver aussi tous les `DeviceToken` de l'utilisateur |

Décorateurs dans l'ordre imposé (`@csrf.exempt` en premier, R7 / `docs/api.md` § 2).

## 2.7 Front

| Fichier | Rôle |
|---|---|
| `src/app/services/push.service.ts` | Enveloppe `@capacitor/push-notifications` : `register()`, écoute `registration` (récupère le jeton, appelle `/api/push/register`), `registrationError`, `pushNotificationActionPerformed` (deep-link via `Router` sur le `link` du payload) |
| `src/app/pages/dashboard/*/settings` (ou page de réglages existante) | Toggle « Notifications push », miroir du toggle email marketing déjà existant |

- Tout le service est gardé par `Capacitor.getPlatform() !== 'web'` — sur le web, le
  service ne s'initialise même pas, ce qui rend la décision § 2.1 vérifiable par lecture :
  aucune tentative de solliciter une permission navigateur.
- La demande de permission OS (`PushNotifications.requestPermissions()`) n'est déclenchée
  qu'après activation explicite du toggle par l'utilisateur — jamais au premier lancement
  de l'app. C'est la fois technique de la décision § 2.3 (opt-in produit avant permission
  OS) et une meilleure pratique reconnue (une demande de permission au premier écran a un
  taux de refus largement plus élevé qu'une demande contextuelle).
- Standalone, `OnPush`, `inject()` — R11.

## 2.8 Conformité — inclus dans la passe, pas après

- `/privacy` : décrire la collecte du jeton d'appareil (finalité unique : envoi de
  notifications, durée de conservation, désactivation via le toggle).
- `/cookies` : relu explicitement pour confirmer qu'il reste vrai sans modification
  (§ 2.1 — aucun cookie, aucun script web tiers).
- `updates.json` : une entrée `feature`, audience large (tous rôles), ton bénéfice
  (« reste informé même sans ouvrir tes mails »), pas de mention technique de Firebase.

## 2.9 Critères d'acceptation

**Statut** : implémenté et testé (backend + front) à l'exception du projet Firebase
réel — voir § 2.11 pour la partie qui reste à faire à la main (console Firebase,
`google-services.json`, `GoogleService-Info.plist`, secret `.env`). Sans ça, `send_push`
renvoie toujours `False` (Firebase non configuré) et le toggle mobile échoue à obtenir
un jeton — comportement attendu, pas une régression.

- [x] `push_opt_in` démarre à `False` pour tous les comptes existants après migration
      (`server_default='false'`, testé upgrade **et** downgrade sur DB réelle).
- [x] Aucune tentative d'enregistrement push n'a lieu tant que l'utilisateur n'a pas
      explicitement activé le toggle (`requestPermissions()` uniquement dans `enablePush()`).
- [x] Un utilisateur avec `push_opt_in=True` mais zéro `DeviceToken` actif ne fait planter
      ni le job, ni `send_push` (retour silencieux) — testé.
- [x] Un utilisateur qui s'est connecté il y a 10 jours ne reçoit rien ; un utilisateur
      inactif depuis 20 jours reçoit un push, une seule fois sur le mois glissant — testé.
- [x] Désactiver le toggle désactive tous les `DeviceToken` de l'utilisateur — testé.
- [ ] Aucun domaine ajouté à `$csp` par rapport à l'état actuel ; `/cookies` reste vrai.
      *(Code vérifié — aucune modification de `nginx/nginx.conf` ni de la page `/cookies`.
      La mise à jour de texte légal `/privacy` prévue en § 2.8 reste à rédiger.)*
- [x] Le build web (`ng build --configuration production`) ne charge aucun SDK Firebase :
      vérifié par build réel — `firebase` n'apparaît que dans un *lazy chunk*, jamais dans
      l'initial (784,99 kB, sous le budget 850 kB). Confirmé aussi en configuration `mobile`.
- [x] Tests pytest (26, tous verts) : opt-in requis, dédup mensuelle, jeton invalide
      désactivé (pas supprimé), agrégation `MAX(login_date)` correcte, compte sans
      `LoginEvent` traité comme inactif. Tests Vitest (9, tous verts) : service push
      inactif sur le web, toggle appelle bien `/api/push/preference`, deep-link au tap.
      Suite complète (pytest 1207 + Vitest 707) verte après la passe.

## 2.10 Pièges de cette passe

1. Permission OS accordée ≠ consentement produit : toujours vérifier `push_opt_in` en
   plus de l'existence d'un `DeviceToken` avant d'envoyer (§ 2.3).
2. Ne pas fusionner ce job avec `run_reengagement_emails` : seuils et cadences de dédup
   différents (§ 2.5).
3. `LoginEvent` n'existe que depuis son introduction (cf. `git log` sur `models.py`) — un
   compte ancien peut n'avoir aucune ligne. Traiter `last_login is None` comme « jamais vu
   depuis l'instrumentation », pas comme « jamais inactif » : sinon aucun vieux compte
   inactif n'est jamais relancé.
4. Jeton invalide ⇒ `is_active=False`, jamais de suppression immédiate de la ligne
   `DeviceToken` (§ 2.4).
5. Le service Angular ne doit strictement rien exécuter sur `platform === 'web'` — c'est
   la garantie technique qui rend la décision § 2.1 vraie, pas juste une intention.
6. `google-services.json` / `GoogleService-Info.plist` sont à committer ; le service
   account JSON (`FIREBASE_CREDENTIALS_JSON`) ne l'est jamais.
7. Cascade `DeviceToken` : `cascade='all, delete-orphan'` sur la collection, jamais
   `passive_deletes` (R9).

## 2.11 Mise en place Firebase — étapes manuelles restantes

Tout ce qui est code est livré et testé (§ 2.9). Ce qui suit ne peut pas être fait par un
agent : ça exige un compte Firebase/Apple Developer et l'exécution locale sur ta machine.
Vérifié pendant cette passe (`npx cap sync android`, `npx cap sync ios`,
`xcodebuild -resolvePackageDependencies`) : les deux plateformes utilisent déjà
`net.laprod.app` comme identifiant (`capacitor.config.ts`, `android/app/build.gradle`,
`PRODUCT_BUNDLE_IDENTIFIER`), et iOS résout ses dépendances via **Swift Package Manager**
(`ios/App/CapApp-SPM/`), pas CocoaPods — pas de `Podfile` à toucher.

### A. Console Firebase

1. [console.firebase.google.com](https://console.firebase.google.com) → nouveau projet
   (ex. « LaProd » — un projet **distinct** de celui de FactureLeBat, comptes/quotas séparés).
   Google Analytics n'est pas nécessaire, tu peux le décocher.
2. Ajouter une app **Android** : package name `net.laprod.app`. Télécharge
   `google-services.json` → dépose-le dans `android/app/google-services.json`.
   **Rien d'autre à modifier côté Gradle** : `android/build.gradle` et
   `android/app/build.gradle` contiennent déjà la logique conditionnelle
   (`if (file('google-services.json').exists()) apply plugin: 'com.google.gms.google-services'`)
   posée par le template Capacitor — elle s'active dès que le fichier existe.
3. Ajouter une app **iOS** : bundle ID `net.laprod.app`. Télécharge
   `GoogleService-Info.plist`. Ne le dépose pas juste dans le dossier — il doit être
   **glissé dans Xcode** (`ios/App/App.xcodeproj`, cible `App`, dans le groupe `App`,
   coché « Copy items if needed » + membership sur la target `App`), sinon il n'est pas
   embarqué dans le bundle et `FirebaseApp.configure()` échoue silencieusement au démarrage.
4. Project Settings → onglet **Cloud Messaging** → section « Apple app configuration » →
   **APNs Authentication Key** : uploader une clé `.p8`.
   - Se génère sur [developer.apple.com](https://developer.apple.com) → Certificates,
     Identifiers & Profiles → Keys → nouvelle clé, cocher « Apple Push Notifications
     service (APNs) ». **Téléchargeable une seule fois** — la sauvegarder immédiatement.
   - Renseigner aussi le Key ID (visible à côté de la clé) et le Team ID (en haut à
     droite du portail développeur Apple).
   - Sans cette clé, Android reçoit les push normalement mais iOS échoue silencieusement :
     c'est l'étape la plus fréquemment oubliée sur ce type d'intégration.

### B. Xcode (iOS)

1. Ouvrir `ios/App/App.xcodeproj` (pas de `.xcworkspace` — SPM, pas CocoaPods).
2. Cible `App` → onglet **Signing & Capabilities** → `+ Capability` :
   - **Push Notifications**
   - **Background Modes**, avec « Remote notifications » coché
3. `AppDelegate.swift` est déjà modifié (`FirebaseApp.configure()` posé dans cette passe) —
   rien à ajouter à la main. `@capacitor-firebase/messaging` s'appuie sur le swizzling par
   défaut de Firebase pour capter le jeton APNs ; si un jour le jeton n'arrive jamais côté
   JS, vérifier qu'aucun `FirebaseAppDelegateProxyEnabled = NO` n'a été ajouté à `Info.plist`.
4. **Note indépendante de ce chantier, repérée pendant la validation** : un build Debug
   iOS pour `iphonesimulator` échoue aujourd'hui sur
   `SWIFT_OBJC_BRIDGING_HEADER = "App/App/App-Bridging-Header.h"` (chemin doublé — le
   fichier réel est à `App/App-Bridging-Header.h` relatif à `$(SRCROOT)`). Préexistant,
   sans lien avec cette passe (`project.pbxproj` non modifié ici) — à corriger séparément
   avant de pouvoir builder iOS en local.

### C. Android

1. `google-services.json` déposé (étape A.2) suffit — pas de capacité à ajouter.
2. Optionnel mais recommandé : une icône de notification monochrome (silhouette blanche
   sur transparent — sinon Android affiche un carré blanc dans la barre de statut) +
   `<meta-data android:name="com.google.firebase.messaging.default_notification_icon" .../>`
   dans `android/app/src/main/AndroidManifest.xml`.
3. Android 13+ : la permission runtime `POST_NOTIFICATIONS` est gérée par
   `requestPermissions()` du plugin — rien à ajouter manuellement.

### D. Backend (`.env`, serveur OVH)

1. Firebase Console → Project Settings → **Service accounts** → « Generate new private
   key » → télécharge un JSON.
2. Coller le **contenu entier** de ce JSON (pas un chemin de fichier) dans `.env`,
   variable `FIREBASE_CREDENTIALS_JSON` — cohérent avec le fait qu'aucun secret n'est
   déposé sur le système de fichiers du conteneur. Sur une seule ligne :
   `FIREBASE_CREDENTIALS_JSON='{"type":"service_account",...}'`
3. En local : ajouter la même variable au `.env` de dev, puis relancer `web`/`worker`.
4. En prod (`ssh deploy@51.77.192.230`) : ajouter la variable à `.env` sur le serveur,
   puis `docker compose -f docker-compose.yml up -d --build web worker` — l'image `web`
   doit être reconstruite pour récupérer `firebase-admin` (ajouté à `pyproject.toml`
   dans cette passe). La migration `device_token_and_push_opt_in` s'applique
   automatiquement au démarrage (`entrypoint.sh`, cf. `docs/deployment.md`).
5. Ne jamais committer ce JSON ni le fichier téléchargé — `.env` est déjà hors git.

### E. Sync et build mobile

Après A–C, depuis la racine du projet :

```bash
npx cap sync android
npx cap sync ios
```

(Déjà exécuté une fois pendant cette passe pour valider le câblage du plugin — à
refaire après avoir déposé les deux fichiers de config Firebase.)

### F. Tester avant de compter sur le job planifié

Le job `run_reengagement_push` ne tourne que le vendredi à 11h (§ 2.5) — pour vérifier le
circuit complet sans attendre :

1. Build l'app sur un **appareil physique** (le push fonctionne mal ou pas du tout sur
   simulateur iOS / émulateur Android sans Google Play Services).
2. Activer le toggle « Notifications push » dans les réglages du profil → confirmer
   qu'une ligne apparaît dans `device_token` (`SELECT * FROM device_token;`).
3. Deux façons de déclencher un envoi sans attendre le job :
   - Firebase Console → Cloud Messaging → « Send test message », coller le `token` de
     la table `device_token`.
   - `flask shell` puis `from utils.push_service import send_push; send_push(<user_id>, 'Titre', 'Corps')`.
4. Pour tester `run_reengagement_push` lui-même : poser manuellement une `LoginEvent`
   vieille de 20 jours pour un utilisateur de test, puis en `flask shell` :
   `from utils.scheduled_tasks import run_reengagement_push; run_reengagement_push(app)`.

---

# Chantier 3 — Moteur de pitch-shift maison (remplace Rubber Band + TarsosDSP)

**Objectif** : éliminer les deux dépendances copyleft fortes (Rubber Band Library
GPL-3.0/commerciale, TarsosDSP GPL-3.0) du monitoring vocal temps réel avec autotune, sans
dégrader la fonctionnalité, et avec la **latence perçue comme priorité absolue** — pas la
qualité audio, contrainte produit explicite pour cette passe.

## 3.1 Décision : zéro dépendance copyleft, code 100% maison

Aucune des deux libs n'était vendorée dans le repo (`android/app/src/main/cpp/rubberband/` et
`ios/App/App/rubberband/` ne contenaient qu'un `COPYING`, jamais le vrai source GPL) — les
builds natifs ne compilaient donc pas tels quels sans téléchargement manuel avant cette passe.
Alternative envisagée et écartée : une lib permissive existante (ex. Oboe, Apache-2.0, pour la
partie AAudio) — décision produit explicite de repartir de zéro plutôt que d'accepter une
dépendance tierce supplémentaire, même permissive.

## 3.2 Décision : LPC-PSOLA, pas du PSOLA nu

Rubber Band était utilisé avec `OptionFormantPreserved` — comportement produit établi, pas une
amélioration optionnelle : l'utilisateur entend sa propre voix pitchée en temps réel dans un
casque, un décalage de formants y est particulièrement perceptible. Le moteur ajoute donc une
couche LPC (Levinson-Durbin, ordre 24, fenêtre 1024/hop 512) autour du cœur TD-PSOLA :
blanchiment du signal source avant décalage de pitch, recoloration avec les coefficients de la
trame d'analyse la plus proche après décalage.

## 3.3 Décision : latence > qualité (contrainte produit explicite)

> « La latence est bien plus importante que la qualité. Il ne faut pas sacrifier entièrement
> la qualité, mais le plus important est que l'utilisateur s'entende instantanément ou
> quasiment. » — 20ms déjà perçu comme beaucoup pour s'écouter chanter dans un micro.

Conséquences concrètes actées dans le code, pas seulement dans l'intention :

- **Plancher de détection PSOLA remonté de 70Hz à 100Hz** (`FLOOR_HZ` dans
  `native/psola-dsp/src/consts.rs`) : la latence structurelle du moteur (~1.5× la période la
  plus longue à suivre) est dominée par la voix la plus grave. Couvrir jusqu'à 70Hz gonflait la
  latence pire-cas pour **toutes** les voix. Compromis explicite, documenté en commentaire dans
  `consts.rs` : les voix très graves (<100Hz) ont un suivi PSOLA dégradé (période clampée),
  accepté en échange d'une latence bien plus basse pour tout le monde. La détection YIN
  applicative reste, elle, découplée et continue de détecter jusqu'à 80Hz pour l'affichage de
  la note à l'utilisateur — seul le pitch-shifting lui-même est borné.
- **AAudio, chemin bas niveau, 100% maison (pas Oboe)** côté Android (API 26+, `aaudio_engine.c`
  + `aaudio_shim.h` chargés via `dlopen` pour dégrader proprement sur API 24-25) : capture,
  détection YIN et correction PSOLA tournent entièrement dans les callbacks natifs AAudio, sans
  traversée JNI par bloc — un aller-retour JNI par bloc aurait réintroduit exactement la gigue
  que ce chemin cherche à éliminer.
- **Bluetooth : avertir, ne jamais bloquer.** Le monitoring live reste physiquement en retard
  d'~100-200ms en A2DP/SBC (limitation matérielle, pas un bug) — décision produit : laisser
  l'utilisateur l'utiliser quand même plutôt que de le lui interdire, avec un avertissement
  clair plutôt qu'un blocage silencieux (voir § 3.6, un système de calibration BT préexistant
  au chantier a été corrigé dans cette passe pour que ce choix soit réellement appliqué).
- **Latence structurelle vérifiée sous le plafond utilisateur (20ms) aux deux fréquences
  d'échantillonnage réellement utilisées par l'app** (44.1kHz chemin de repli, 48kHz — fréquence
  typique négociée par AAudio sur de nombreux appareils Android récents) — voir
  `structural_latency_stays_under_user_specified_ceiling_at_both_sample_rates` dans
  `native/psola-dsp/tests/sample_rate_and_latency_sweep.rs` : ~16.3ms @ 44.1kHz, ~15ms @ 48kHz.

## 3.4 Architecture

```
native/                              ← workspace Rust, racine du repo, partagé Android+iOS
  psola-dsp/                         ← cœur algorithmique, #![forbid(unsafe_code)]
    src/{levinson,period_tracker,lpc,psola,yin,consts}.rs
    tests/{rubberband_parity,property_based,soak,antares_grade_quality,
           formant_preservation,sample_rate_and_latency_sweep}.rs
  psola-ffi/                         ← tout le `unsafe` du workspace, ici et nulle part ailleurs
    src/lib.rs                       ← extern "C", catch_unwind systématique
    include/psola_ffi.h              ← en-tête C écrit à la main, SEULE source de vérité
    tests/ffi_contract.rs

android/app/src/main/cpp/
  jni_shim.c                         ← pont JNI vers psola-ffi (chemin AudioCaptureLoop)
  aaudio_engine.c + aaudio_shim.h    ← moteur bas niveau AAudio (chemin rapide, API 26+)
  aaudio_jni.c                       ← pont JNI vers aaudio_engine.c
  spsc_ring.h                        ← anneau lock-free SPSC (pont callbacks entrée/sortie)
  tests/spsc_ring_test.c             ← harnais autonome (voir § 3.5), PAS construit par CMake
  CMakeLists.txt                     ← invoque `cargo build` à chaque build Gradle

android/app/src/main/java/net/laprod/app/
  PsolaProcessor.kt, PsolaAudioEngine.kt, YinPitchDetector.kt, AudioCaptureLoop.kt
  PitchMonitorPlugin.kt              ← AudioRecordingSession : chemin rapide AAudio d'abord,
                                        repli AudioCaptureLoop si PsolaAudioEngine.create()
                                        retourne null (jamais de retry en boucle)

ios/App/App/
  RubberBandWrapper.h/.mm            ← noms conservés (project.pbxproj les référence), contenu
                                        réécrit pour appeler psola_ffi.h au lieu de
                                        RubberBandStretcher ; ring buffer SPSC et interface ObjC
                                        publique inchangés
  App.xcodeproj/project.pbxproj      ← phase "Run Script" (cargo build + lipo) sur le target App
```

Workspace à deux crates (pas un seul) : tout le `unsafe` (frontière FFI, pointeurs bruts venant
de Kotlin/ObjC++) vit exclusivement dans `psola-ffi`, jamais mélangé au cœur algorithmique
100% sûr — `cargo miri test`/`cargo fuzz` peuvent cibler `psola-dsp` seul. `include/psola_ffi.h`
est référencé directement par les deux plateformes (`target_include_directories` CMake,
`HEADER_SEARCH_PATHS` Xcode) — jamais copié, une seule source de vérité.

Aucun binaire Rust n'est committé : `cargo build` est invoqué à chaque build, sur les deux
plateformes (CMake `execute_process` côté Android, phase "Run Script" Xcode côté iOS) — voir
`docs/deployment.md` § 9 pour les prérequis (`rustup` + cibles croisées).

## 3.5 Tests — inventaire et ce qu'ils couvrent

**`native/` (cargo test, workspace complet, 50 tests)** :
- `rubberband_parity.rs` (8) : portage 1:1 des assertions de l'ancien
  `RubberBandWrapperTests.swift` (latence bornée, silence avant input, reset→silence...).
- `property_based.rs` : sweep aléatoire (LCG maison, graine fixe, 300 itérations) de
  fréquences/ratios/amplitudes, à 44.1kHz, blocs fixes de 256 échantillons.
- `sample_rate_and_latency_sweep.rs` (5, nouveau cette passe) : le même sweep répété aux
  **deux fréquences réellement utilisées par l'app** (44.1k et 48k, pas seulement 44.1k) ;
  latence structurelle en ms sous le plafond utilisateur (§ 3.3) ; plancher de détection réel
  jamais pire que documenté ; et surtout — **preuve que la sortie est bit-identique quel que
  soit le découpage de l'entrée en appels `process()` successifs** (1 à 1024 échantillons par
  appel, aléatoire), propriété directement pertinente puisqu'AAudio ne garantit AUCUNE taille
  de callback fixe (contrairement aux blocs fixes de `property_based.rs`).
- `antares_grade_quality.rs` (4) : transparence à ratio unité, absence de clic sur saut abrupt
  (équivalent Retune Speed "robot"), préservation du vibrato (Retune Speed "naturel"), formants
  à la transposition max réelle de l'app (±2.5 demi-tons) — critères calibrés sur la
  documentation publique Antares (Auto-Tune) après recherche dédiée.
- `formant_preservation.rs`, `soak.rs` (30s, dérive numérique), tests unitaires colocalisés
  (`levinson`, `period_tracker`, `lpc`, `yin` — 22 au total).
- `psola-ffi/tests/ffi_contract.rs` (8) : frontière FFI, y compris `SendPtr` pour tester la
  contention multi-thread et les appels sur handle NULL (`calls_on_null_handle_do_not_crash...`).
- Gates obligatoires, pas optionnelles : `cargo clippy --all-targets -- -D warnings`,
  `cargo fmt --check`, `cargo miri test` (composant officiel du toolchain).

**`android/app/src/main/cpp/tests/spsc_ring_test.c` (nouveau cette passe, 6 tests)** — le ring
lock-free qui pontait les callbacks AAudio entrée/sortie n'avait **aucun** test avant cette
passe. Header-only et portable (pas de dépendance Android) : compilable et exécutable
nativement, hors NDK/device. Vérifié propre sous trois configurations : exécution normale,
**AddressSanitizer+UBSan** (a trouvé un bug — dans le test lui-même, un buffer source
sous-dimensionné ; corrigé, le header lui-même n'avait pas de bug), et
**ThreadSanitizer** (stress producteur/consommateur réel, 2 millions d'échantillons, tailles de
bloc aléatoires 1-256 — zéro data race détectée).

**Android JVM** (`./gradlew test`) : `YinPitchDetectorTest.kt` (13, miroir de
`YINDetectorTests.swift`), `AudioCaptureLoopTest.kt` (10, fonctions pures PCM/RMS).

**Ce qui reste hors de portée sans matériel réel** : comportement du callback audio sous charge
CPU réelle (xruns), négociation MMAP effective par appareil, latence *perçue* (vs. structurelle)
sur device physique, expérience subjective du monitoring Bluetooth.

## 3.6 Bugs trouvés et corrigés pendant cette passe

1. **Normalisation d'énergie et octave errors du tracker de période** (tôt dans la passe) —
   corrigé (`period_tracker.rs` : normalisation par segment, recherche du premier maximum local
   plutôt que le maximum global).
2. **Recoloration LPC pendant le parcours d'un grain** — cassait entièrement la préservation
   des formants (le filtre IIR visitait un même échantillon plusieurs fois, dans le désordre).
   Corrigé : recoloration appliquée une seule fois, en ordre chronologique de sortie
   (`psola.rs::emit_grain`, voir son commentaire pour le détail).
3. **`aaudio_engine_create` ne vérifiait jamais le sample rate réellement négocié par AAudio**
   — trouvé en écrivant `sample_rate_and_latency_sweep.rs` (constat : l'app tourne à 44.1kHz
   *ou* 48kHz selon le chemin actif, jamais testé aux deux avant cette passe). AAudio ne
   garantit PAS d'honorer exactement le taux demandé, même en mode `EXCLUSIVE`. Un désaccord
   silencieux aurait pu viser la mauvaise fréquence en autotune ou mal étiqueter
   l'enregistrement. Corrigé : `AAudioStream_getSampleRate()` vérifié sur les deux flux
   (entrée ET sortie) après ouverture, échec propre (repli `AudioCaptureLoop`) sinon.
4. **Le monitoring Bluetooth n'était en réalité jamais activé**, même après calibration —
   trouvé en cherchant où câbler l'avertissement Bluetooth décidé en § 3.3. Le système de
   calibration (préexistant, tap-to-measure) n'alignait que l'export, jamais le monitoring live
   (`monitorAutotune.set(true)` n'était appelé que pour le filaire). Le texte affiché
   (« Export et monitoring alignés ») était trompeur. Corrigé : `onCalibrationDone` active
   désormais le monitoring, avec un avertissement correct sur le délai perçu
   (`mobile-studio.component.ts`/`.html`).
5. **`SWIFT_OBJC_BRIDGING_HEADER` avec un segment de chemin dupliqué** et **`PitchMonitorPlugin.
   swift` appelant `renderInto(_:frameCount:)` au lieu de `render(into:frameCount:)`** (nom
   Swift réellement généré par le pont Clang) — deux bugs préexistants, sans rapport avec ce
   chantier, jamais détectés faute d'un `xcodebuild` réel avant cette passe. Corrigés au passage
   (bloquaient toute vérification du portage iOS).

## 3.7 Critères d'acceptation

**Statut** : implémenté et vérifié par build/test réel sur les deux plateformes — voir le détail
ci-dessous pour ce qui distingue « vérifié ici » de « nécessite un appareil physique ».

- [x] `cargo test --workspace` (50 tests), `cargo clippy -D warnings`, `cargo fmt --check`,
      `cargo miri test` : propres.
- [x] Compilation croisée réelle (pas seulement host) pour les 4 ABI Android
      (`aarch64/armv7/i686/x86_64-linux-android`) et les 3 cibles iOS
      (`aarch64-apple-ios`, `aarch64-apple-ios-sim`, `x86_64-apple-ios`).
- [x] Android : `./gradlew :app:assembleDebug` réussi de bout en bout (Kotlin + CMake→cargo→
      jni_shim.c/aaudio_engine.c→`libpsola_processor.so`), 14 symboles JNI confirmés exportés
      (`llvm-nm`), `libaaudio.so` confirmé **absent** des `NEEDED` (`llvm-readelf -d`) — la
      dégradation API 24-25 reste propre.
- [x] iOS : **build réel via `xcodebuild`** (pas seulement cross-compilation) pour les 4
      combinaisons Debug/Release × device/simulateur, y compris Release/device (config utilisée
      pour l'App Store) — toutes réussies. Symboles `psola_*` confirmés liés (`nm`), zéro
      symbole `RubberBandStretcher` restant.
- [x] `./gradlew test` (JVM, 23 tests) et suite Angular complète (707 tests, 57 fichiers) vertes.
- [x] `spsc_ring_test.c` propre sous exécution normale, ASan+UBSan, ThreadSanitizer.
- [x] Latence structurelle < 20ms (plafond utilisateur) aux deux fréquences réelles de l'app.
- [x] Sortie du moteur PSOLA prouvée indépendante du découpage en callbacks (pertinent pour
      AAudio, qui ne garantit aucune taille de bloc fixe).
- [ ] Écoute réelle sur device physique (latence perçue, artefacts formants sur voix réelle,
      comportement AudioFocus/casque en conditions réelles) — hors de portée de ce sandbox,
      voir § 3.9.
- [ ] Négociation MMAP AAudio effective par modèle d'appareil — le code vérifie et refuse
      proprement un désaccord (§ 3.6.3), mais quels appareils obtiennent réellement le chemin
      MMAP exclusif reste à observer en usage réel.

## 3.8 Pièges de cette passe

1. **COLA (Constant OverLap-Add)** : la somme des fenêtres de Hann qui se chevauchent doit
   rester quasi-constante, sinon modulation d'amplitude audible.
2. **Reset des filtres LPC** : un filtre IIR garde de l'énergie interne — `reset()` doit vider
   l'état LPC en plus du ring PSOLA, sinon `testResetClearsOutput`-équivalent échoue en silence.
3. **Un seul thread « chaud »** mute tout l'état interne (tracker, coefficients LPC compris) ;
   seul le ratio de pitch cible (`PitchTarget`) reste atomique. Ne jamais introduire de mutex
   ou d'état partagé non-atomique.
4. **`onError` AAudio ne doit JAMAIS stop/close le flux** depuis le callback lui-même (interdit
   par la doc AAudio) — se contenter de positionner un flag atomique, laisser un thread normal
   (polling Kotlin) réagir.
5. **Ne jamais faire confiance au sample rate demandé** pour un flux AAudio — toujours vérifier
   `AAudioStream_getSampleRate()` après ouverture (§ 3.6.3). Vaut aussi pour le flux de SORTIE :
   il doit matcher le flux d'ENTRÉE, pas seulement la valeur nominale demandée.
6. **arm64 device ≠ arm64 simulateur pour `lipo`** : les deux rapportent la même architecture
   CPU, `lipo -create` ne peut pas les combiner dans un seul `.a` universel malgré ce que
   suggérait la formulation initiale du plan. Le Run Script Xcode compile la bonne cible selon
   `$PLATFORM_NAME` (`aarch64-apple-ios` vs `aarch64-apple-ios-sim` + `x86_64-apple-ios` combinés
   par `lipo` uniquement entre eux, pour le simulateur).
7. **Calibration de latence Bluetooth ≠ correction de la latence de monitoring live** — la
   calibration existante aligne l'export sur le beat, elle ne réduit en rien le délai que
   l'utilisateur entend en se monitorant lui-même en direct (§ 3.6.4). Ne pas confondre les deux
   dans une future évolution de cette fonctionnalité.

## 3.9 Étapes manuelles restantes

Tout ce qui est code est livré, testé et vérifié par build réel (§ 3.7). Ce qui suit exige un
appareil physique ou un compte développeur, pas seulement ce sandbox :

1. **Prérequis machine de build** : `rustup` + cibles croisées — voir `docs/deployment.md` § 9
   (nouvelle section ajoutée cette passe). Sans ça, `make android-bundle`/`android-apk` et tout
   build Xcode échouent avec un message explicite (`cargo introuvable...`), jamais une erreur
   de link cryptique.
2. **Test d'écoute manuel** : `cargo run --bin dump_wav` (dans `native/psola-dsp/`) écrit des
   fichiers WAV pour validation à l'oreille avant/après décalage de pitch — pas encore fait sur
   cette passe, recommandé avant une release large.
3. **Test sur appareil Android physique** : confirmer que le chemin AAudio rapide s'active
   réellement (niveau de log/latence observée) sur au moins un appareil bas de gamme (API 26+
   minimal) et un appareil récent — le repli `AudioCaptureLoop` doit rester silencieux (pas de
   log d'erreur) sur les appareils où AAudio échoue, par design.
4. **Test sur appareil iOS physique + TestFlight** : le simulateur ne teste jamais l'AVAudioEngine
   temps réel dans des conditions représentatives (latence, AudioSession réelle).
5. **Test casque Bluetooth réel** : vérifier que l'avertissement de latence (§ 3.3, § 3.6.4)
   s'affiche au bon moment et que le monitoring s'active effectivement après calibration.
6. **Écoute croisée avec l'ancien moteur Rubber Band** (si une build antérieure est encore
   disponible) pour une comparaison subjective de qualité — non bloquant, mais utile avant
   d'annoncer le chantier terminé aux utilisateurs.

---

# Chantier — Sign in with Apple

**Objectif** : rendre l'app éligible à l'App Store. La guideline 4.8 impose Sign in with
Apple comme option **équivalente** à tout autre login social dès qu'il y en a un — l'app
propose déjà Google, donc son absence est un motif de rejet certain en review. Deux autres
exigences Apple, indépendantes de 4.8 mais vérifiées par le même reviewer, sont couvertes
par la même passe : suppression de compte en un tap (guideline 5.1.1(v) — déjà en place,
`routes/main_api.py::delete_own_account`) et révocation des tokens Apple à cette suppression
(recommandation de la doc Sign in with Apple REST API).

## Ce qui est livré

**Backend** (`utils/apple_signin.py`, `routes/auth_api.py`, `models.py`) :

- Vérification cryptographique réelle des identity tokens Apple (JWKS RS256, cache Redis
  24h en best-effort — R4) via `authlib.jose`, pas de dépendance ajoutée.
- `client_secret` Apple (JWT ES256, régénéré à chaque appel — Apple interdit un secret
  statique, contrairement à `GOOGLE_CLIENT_SECRET`).
- Trois cas de connexion (`_apple_login_or_create_user`), miroir exact de la logique
  `google_callback()` : `apple_sub` connu → connexion, email connu sans provider → liaison,
  sinon → création (`account_status='pending_completion'`, même flow `complete-profile`
  que Google).
- Deux entrées selon la plateforme (voir § architecture ci-dessous) :
  `GET /apple/login` + `POST /apple/callback` (web + Android, redirection) et
  `POST /apple/native` (iOS, réponse directe).
- Colonnes `apple_sub` (unique, indexé), `apple_refresh_token`,
  `apple_refresh_token_client_id` sur `User` (migration `a1c9f2e7d4b3`).
- Révocation best-effort du refresh token Apple à la suppression de compte
  (`routes/main_api.py::delete_own_account` et `routes/admin_api.py::delete_user`) — un
  échec de révocation ne bloque jamais la suppression.
- Message générique "Cet email utilise Google/Apple. Ajouter un mot de passe ?"
  (`login()`), qui était hardcodé "Google" avant cette passe.

**Frontend** (`auth.service.ts`, pages `login`/`register`, `oauth-callback`) :

- `navigateAfterOauth()` déplacé de `OauthCallbackComponent` vers `AuthService` : logique
  partagée entre le retour web (Google + Apple, via `/oauth-callback?code=`) et le flow
  natif Apple (réponse directe, pas de redirection à intercepter).
- Bouton Apple noir/blanc conforme aux Human Interface Guidelines (exception documentée
  à R12 — ce n'est pas une couleur produit), sur `login` et `register`.
- iOS natif → `@capawesome/capacitor-apple-sign-in` (AuthenticationServices), POST direct
  vers `/apple/native`. Android + web → même mécanique Custom Tab que Google
  (`startAppleWebLogin`), vers `/apple/login`.

**iOS** (`ios/App/`) :

- `App.entitlements` (capacité `com.apple.developer.applesignin`), câblé dans
  `project.pbxproj` (Debug + Release) et référencé dans le groupe `App`.
- `CapApp-SPM/Package.swift` : dépendance `CapawesomeCapacitorAppleSignIn` ajoutée (sera
  régénérée à l'identique par `npx cap sync ios`, le fichier est marqué "managed by
  Capacitor CLI").
- `package.json` : `@capawesome/capacitor-apple-sign-in` (choisi plutôt que
  `@capacitor-community/apple-sign-in`, qui plafonne à Capacitor 5 — ce projet est en
  Capacitor 8 ; capawesome annonce le support de la dernière version majeure).

**Android** : aucun changement natif. Sign in with Apple n'a pas de SDK Android officiel —
le flow web (`/apple/login?platform=mobile`, Custom Tab, retour par `net.laprod.app://`)
réutilise l'infrastructure Google existante à l'identique (`AndroidManifest.xml`,
`NativeShellService.appUrlOpen`, `OauthCallbackComponent`).

## Pourquoi deux flows plutôt qu'un seul plugin cross-plateforme

`@capawesome/capacitor-apple-sign-in` sait en théorie piloter les trois plateformes
(natif iOS, redirection Android/web via `initialize()` + `redirectUrl`). Décision : ne
l'utiliser que pour iOS, et garder le flow web maison pour Android — celui-ci est déjà
prouvé en production pour Google (Custom Tab, retour par schéma `net.laprod.app://`,
`OauthCallbackComponent`), alors que le chemin Android du plugin n'a pas été audité ni
testé dans ce sandbox (pas d'environnement Android pour le vérifier). Réutiliser
l'infrastructure existante plutôt qu'un chemin plugin non vérifié est le choix qui expose
le moins de surface neuve côté mobile.

## Étapes manuelles restantes (hors de portée de ce sandbox)

Tout ce qui est code est livré et testé (1234 tests pytest, 722 tests Vitest, `ng build`,
`tsc --noEmit` verts). Ce qui suit exige un compte Apple Developer, Xcode, ou un appareil
physique :

1. **Apple Developer Portal** — un seul compte pour toute l'organisation :
   - Certificates, Identifiers & Profiles > Identifiers > App ID `net.laprod.app` : cocher
     la capacité **Sign In with Apple**.
   - Identifiers > créer un **Services ID** (ex. `net.laprod.app.web`) pour le flow
     web/Android, avec le domaine `laprod.net` et l'URL de retour
     `https://laprod.net/api/auth/apple/callback` renseignés dans sa config Sign In with
     Apple.
   - Keys > créer une clé **Sign in with Apple** (une seule pour tout le compte,
     réutilisable par plusieurs apps/Services ID) → télécharger le `.p8` (téléchargement
     **unique**, à sauvegarder immédiatement) et noter le Key ID.
   - Noter le Team ID (visible en haut à droite du portail).
2. **Variables d'environnement production** (`.env`, cf. `docs/deployment.md` § 6) :
   `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` (contenu du `.p8`, `\n` littéraux),
   `APPLE_SERVICES_ID`, `APPLE_BUNDLE_ID` (`net.laprod.app`, déjà la valeur par défaut).
   `./scripts/apple-p8-to-env.sh <fichier.p8> --write` convertit le `.p8` téléchargé et
   écrit `APPLE_PRIVATE_KEY`/`APPLE_KEY_ID` directement dans `.env` (sans jamais afficher
   la clé). `./doctor.sh` vérifie ensuite que les quatre premières sont soit toutes
   présentes, soit toutes absentes (une config partielle transforme un bouton absent en
   bouton qui répond 500).
3. **Xcode** : ouvrir le projet, `Signing & Capabilities` doit déjà afficher **Sign in with
   Apple** (câblé via `App.entitlements` par cette passe) — vérifier qu'aucun conflit de
   capacité n'apparaît selon le compte développeur utilisé pour signer.
4. **`npm install && npx cap sync ios`** pour matérialiser `@capawesome/capacitor-apple-sign-in`
   dans `node_modules` et régénérer `Package.swift`/`Podfile.lock` (déjà fait dans ce
   sandbox le temps de la passe, mais `node_modules` n'est jamais committé).
5. **Test réel sur device/simulateur iOS** : bouton Apple natif, première autorisation
   (nom/email fournis), autorisations suivantes (nom/email absents — vérifier que la
   connexion fonctionne quand même via `apple_sub`), annulation (le bouton ne doit
   afficher aucune erreur).
6. **Test réel Android + web** : bouton Apple → Custom Tab / navigateur → retour app,
   même parcours (première autorisation avec formulaire Apple de partage/masquage
   d'email, connexions suivantes).
7. **Test de suppression de compte** avec un compte lié Apple : vérifier en base que
   `apple_refresh_token` est vidé, et si possible confirmer côté Apple (Réglages >
   [Apple ID] > Mots de passe et sécurité > Apps utilisant Apple ID) que l'app disparaît
   de la liste après révocation.
8. **Screenshot App Store Connect** : Apple exige que le bouton Sign in with Apple soit
   visible dans au moins une capture d'écran de la fiche si l'app en dépend pour l'auth
   (pas obligatoire ici puisque l'email/mot de passe reste disponible, mais recommandé
   pour éviter une question du reviewer).
9. **Relire `/privacy`** (R17) : mentionner que Sign in with Apple peut transmettre un
   email de relais privé (`@privaterelay.appleid.com`) et que LaProd le traite comme un
   email normal (mails transactionnels délivrés via ce relais tant que l'utilisateur ne
   révoque pas l'accès côté Apple).

---

# Chantiers suivants (non spécifiés)

À détailler au même format le moment venu.

- **Concours de beats / gamification** — annoncé dans le README, jamais implémenté.
- **Sortie de bêta du module producteur** — retirer les `BetaBadge`, stabiliser les
  contrats de management.
- **Reprise du backlog sécurité** — cookie Capacitor, migration argon2, réinitialisation
  de mot de passe (cf. audit de juillet 2026).
- **Stockage objet pour `db_assets/`** — le système de fichiers local est le point de
  fragilité restant du déploiement mono-VPS.
