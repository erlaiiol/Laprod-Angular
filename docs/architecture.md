# Architecture

Vue d'ensemble destinée à quelqu'un (humain ou agent) qui doit ajouter une
fonctionnalité sans casser l'existant. Le `README.md` décrit le *quoi* ; ce document
décrit le *où* et surtout le *pourquoi c'est découpé comme ça*.

---

## 1. Vue macro

```
Navigateur / WebView Capacitor
        │
        ▼
   nginx (TLS, CSP, cache statique, /api → Flask)
        │
   ┌────┴────────────────────────────┐
   ▼                                 ▼
frontend (build Angular statique)   web (Flask + gunicorn)
                                     │
                        ┌────────────┼─────────────┐
                        ▼            ▼             ▼
                  PostgreSQL 15   Redis 7      db_assets/
                                     │        (audio, images,
                                     ▼         contrats PDF)
                              worker RQ + APScheduler
```

Services `docker-compose.yml` : `db`, `redis`, `web`, `worker`, `frontend`, `certbot`.

**Règle de séparation** : la requête HTTP ne fait jamais de travail long. Traitement
audio, envoi d'emails, calcul de recommandations, dispatch de campagnes → RQ (`tasks/`,
`utils/*_jobs.py`). Les jobs récurrents passent par APScheduler (`extensions.py::init_scheduler`,
`utils/scheduled_tasks.py`).

---

## 2. Backend Flask — les couches

| Couche | Répertoire | Responsabilité | Interdit |
|---|---|---|---|
| Routes | `routes/*_api.py` | HTTP : parsing, autorisation, codes de retour | Contenir la logique métier, sérialiser à la main |
| Services métier | `utils/*_service.py` | Règles du domaine, calculs, quotas | Toucher à `request` / `jsonify` |
| Sérialisation | `serializers.py` | Modèle SQLAlchemy → dict JSON | Contenir des règles d'autorisation |
| Modèles | `models.py` | Schéma, contraintes, propriétés dérivées | Faire des I/O réseau |
| Jobs | `tasks/`, `utils/*_jobs.py` | Exécution asynchrone | Supposer un contexte de requête |

36 blueprints sont enregistrés dans `app.py` (voir `routes/__init__.py` pour la liste).
Un domaine fonctionnel = un blueprint = un service = une entrée dans `docs/api.md`.

### Sources uniques de vérité

Ce projet a une allergie documentée aux règles recopiées. Quand une règle existe à deux
endroits, elle finit par diverger — et une divergence sur une règle d'autorisation, c'est
une faille. Les modules suivants sont **la** référence, et rien ne les court-circuite :

| Module | Détient | Symptôme d'un contournement |
|---|---|---|
| `utils/plans.py` | Paliers, prix, quotas, capacités | Un `== 'pro'` littéral dans le code métier |
| `utils/money.py` | Tout calcul monétaire, arrondi, centimes Stripe | Un `float`, un `/ 100`, un `int(x * 100)` |
| `serializers.py` | Forme JSON de chaque entité | Un `jsonify({...})` construit dans une route |
| `utils/crud_helpers.py` | `get_or_404`, `require_ownership`, `commit_or_rollback` | Un `try/except/rollback` recopié |
| `utils/auth_helpers.py` | `require_user`, `require_admin` | Un `db.session.get(User, get_jwt_identity())` inline |

`serializers.capabilities_dict()` est le pont : il expose au front exactement les mêmes
`can_*` que ceux qui protègent l'API. Une case cochée dans l'UI correspond toujours à un
droit réellement accordé par le serveur.

---

## 3. Redis — trois usages qu'il ne faut pas confondre

1. **File de jobs** (RQ) — `Queue(connection=redis_client).enqueue(...)`.
2. **Cache de calcul dérivé** — TTL court, invalidation explicite par le module
   propriétaire (`invalidate_*_cache`). Exemple : `utils/recommendation_service.py`
   (vecteur de goût, TTL 600 s).
3. **État de session court** — snapshots de pagination, compteurs anti-abus, verrous
   souples.

**Le piège n°1 du projet**, déjà rencontré en production : un calcul asynchrone qui se
termine *entre* deux requêtes de pagination du même utilisateur change l'ordre de la
liste, et la page 2 ne suit plus la page 1. La parade est en place dans
`routes/tracks_api.py::get_tracks` — un snapshot `laprod:reco:fallback:{user_id}` (TTL 300 s)
fige l'ordre pour toute la session de pagination, et les recommandations fraîches ne
s'appliquent qu'au chargement suivant. **Tout classement paginé calculé en fond doit
reproduire ce schéma.**

Corollaire : un filtre ne doit jamais désactiver la personnalisation. On restreint la
liste triée au sous-ensemble filtré **en conservant son ordre** (le rang dans le cache
fait office de score), on ne repart pas sur un tri par date.

---

## 4. Frontend Angular

```
src/app/
├── pages/        composants « intelligents » — fetch, logique de page, routing
├── components/   composants présentationnels réutilisables
├── services/     accès API + état partagé (signals)
├── guards/       authGuard, adminGuard, …
├── directives/   RevealOnScroll, ImgFallback, TourAnchor
└── layout/       navbar, footer, player
```

Standalone components uniquement, `inject()`, signals (`signal` / `computed` / `effect`),
nouveau control flow (`@if` / `@for`), `ChangeDetectionStrategy.OnPush` partout.

### Pièges avérés (chacun a coûté une session de débogage)

- **`effect()` et dépendances conditionnelles** — une branche qui lit un signal l'ajoute
  aux dépendances de l'effect, l'autre non. Le comportement diffère alors entre le premier
  et le deuxième déclenchement. Lecture « pour information » → `untracked()`. Cas réel
  commenté dans `src/app/pages/home/home.component.ts`.
- **État chargé une seule fois au démarrage** — un `afterNextRender` one-shot ne se rejoue
  pas à la connexion : les compteurs restent périmés. Utiliser un `effect()` sur
  `isLoggedIn()`.
- **Bootstrap sans Popper** — `bootstrap.bundle.js` n'est plus dans le projet ; un
  `.dropdown-menu.show` n'a aucun positionnement par défaut, il faut le poser en SCSS.
- **Vitest + `[disabled]` sur un `[ngModel]`** — `nativeElement.disabled` ne reflète pas
  la liaison en TestBed alors que le comportement est correct en réel. Tester la
  propriété du composant, pas le DOM.

### Mobile (Capacitor)

Même build Angular dans un WebView natif. Deux plugins natifs (Kotlin / Swift) exposent
la détection de hauteur temps réel pour le topline ; le reste du pipeline audio est en
TypeScript côté client (`MobileAudioProcessorService`). Détails et prérequis : `README.md`.

Conséquence sur toute nouvelle fonctionnalité web : elle doit fonctionner dans un WebView
`capacitor://` / `https://app.laprod.net` (CORS), sans dépendre d'un domaine tiers, et sans
supposer que les cookies se comportent comme sur le web.

---

## 5. Flux argent

```
Acheteur ──Stripe Checkout──▶ LaProd encaisse 100 %
                                   │
                    split_platform_fee (10 % sur le NET encaissé)
                                   │
                                   ▼
                     WalletTransaction (status='pending')
                                   │  +7 jours
                                   ▼
                            status='available'
                                   │  retrait ≥ 10 €
                                   ▼
                   stripe.Transfer ──▶ compte Connect du vendeur
```

Points structurants pour tout code qui touche au wallet :

- `Wallet.balance_available >= 0` et `WalletTransaction.amount > 0` sont des
  `CheckConstraint` en base. **Un débit se modélise donc comme une transaction de montant
  positif avec un `type` de débit**, jamais comme un montant négatif.
- Toute écriture concurrente sur un solde passe par un verrou de ligne
  (`select(Wallet).with_for_update()`), comme dans `utils/wallet_service.py::perform_withdrawal`.
- Les services wallet ne committent pas : le commit appartient à la route appelante
  (`@commit_or_rollback`).

---

## 6. Où se branche une nouvelle fonctionnalité

Checklist de localisation, dans l'ordre :

1. **Modèle** → `models.py` (+ migration Alembic, + `cascade='all, delete-orphan'` côté
   collection quand la FK est `NOT NULL` — jamais `passive_deletes`, SQLite ne force pas
   les FK en test).
2. **Règles métier** → `utils/<domaine>_service.py`, avec les constantes en tête de module.
3. **Sérialisation** → `serializers.py`.
4. **Routes** → `routes/<domaine>_api.py` + enregistrement dans `routes/__init__.py` et `app.py`.
5. **Asynchrone** → `tasks/` ou `utils/<domaine>_jobs.py`.
6. **Service Angular** → `src/app/services/<domaine>.service.ts`.
7. **UI** → `pages/` si c'est une page, `components/` si c'est réutilisable.
8. **Tests** → `tests/` (pytest, factories + scénarios) et `*.spec.ts` (Vitest).
9. **Communication** → une entrée dans `updates.json` si l'utilisateur le remarque.
