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

# Chantiers suivants (non spécifiés)

À détailler au même format le moment venu.

- **Concours de beats / gamification** — annoncé dans le README, jamais implémenté.
- **Sortie de bêta du module producteur** — retirer les `BetaBadge`, stabiliser les
  contrats de management.
- **Reprise du backlog sécurité** — cookie Capacitor, migration argon2, réinitialisation
  de mot de passe (cf. audit de juillet 2026).
- **Stockage objet pour `db_assets/`** — le système de fichiers local est le point de
  fragilité restant du déploiement mono-VPS.
