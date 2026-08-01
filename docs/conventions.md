# Conventions

Conventions de nommage, de style et de rédaction. Le *comment contribuer* (workflow git,
PR, stratégie de tests détaillée) reste dans `CONTRIBUTING.md` ; ce document rassemble ce
qu'il faut connaître pour que du code écrit aujourd'hui ressemble au code déjà là.

---

## 1. Langue

| Où | Langue |
|---|---|
| Noms de variables, fonctions, classes, tables | anglais |
| Commentaires et docstrings | français |
| Messages d'erreur et textes d'interface | français |
| Messages de commit | français, impératif |

Les commentaires expliquent **pourquoi**, pas quoi. Le style du projet est d'écrire un
bloc en tête de module ou de fonction quand une décision n'est pas évidente, avec le
symptôme qui a motivé la décision. Un commentaire qui paraphrase la ligne suivante est
du bruit ; un commentaire qui dit « ne pas augmenter cette constante : au-delà de 3 ms
le fondu s'entend » évite une régression.

---

## 2. Python

- Fichiers : `snake_case.py`. Blueprints : `routes/<domaine>_api.py`, variable
  `<domaine>_api_bp`. Services : `utils/<domaine>_service.py`. Jobs : `utils/<domaine>_jobs.py`.
- Constantes métier en **tête de module**, en majuscules, commentées. Pas de nombre magique
  dans le corps d'une fonction.
- Fonctions privées d'un module préfixées `_`.
- Enums pour tout champ à valeurs fermées, doublées d'un `CheckConstraint` en base.
- Import des helpers de sérialisation en tête : `from serializers import ok, err, ...`.

### Argent

Tout passe par `utils/money.py`. Aucune exception.

```python
from utils.money import to_money, to_cents, from_cents, split_platform_fee

total = to_money(request.json['amount'])       # Decimal, 2 décimales, ROUND_HALF_UP
stripe_amount = to_cents(total)                # int centimes
received = from_cents(session.amount_total)    # jamais `amount_total / 100`
fee, seller_revenue = split_platform_fee(total)  # commission sur le NET encaissé
```

Interdits : `float` sur un montant, `int(x * 100)`, `x / 100`, un second arrondi sur un
montant déjà arrondi. `remise + net == brut` et `commission + revenu == total` sont des
identités exactes, garanties par construction — ne pas les recalculer autrement.

### Paliers

```python
from utils import plans

if plans.plan_rank(user.subscription_plan) >= plans.plan_rank(plans.PREMIUM):
    ...
# ou, préférable :
if user.can_offer_exclusive:
    ...
```

Jamais `if user.subscription_plan == 'pro'`. `LEGACY_ALIASES` doit rester en place : des
JWT et des métadonnées Stripe portent encore les anciens identifiants, et l'app Capacitor
déployée aussi.

### SQLAlchemy

- Relation lue dans une boucle → `selectinload` en amont, systématiquement.
- FK `NOT NULL` vers `user` → `cascade='all, delete-orphan'` **sur la collection du
  backref**, jamais `passive_deletes=True` (SQLite ne force pas les FK en test : le bug
  n'apparaîtrait qu'en production).
- Index explicite sur toute colonne servant de filtre ou de tri fréquent.
- Contraintes d'intégrité en base (`CheckConstraint`, `UniqueConstraint`) en plus des
  validations applicatives — la base est la dernière ligne de défense.

### Cache Redis

Pattern imposé (échec silencieux, jamais de 500 parce que Redis est indisponible) :

```python
CACHE_TTL = 600

def build_something(user_id: int) -> dict:
    key = f'laprod:<domaine>:{user_id}'
    if redis_client:
        try:
            cached = redis_client.get(key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    result = _compute(user_id)

    if redis_client:
        try:
            redis_client.setex(key, CACHE_TTL, json.dumps(result))
        except Exception:
            pass
    return result
```

Nommage des clés : `laprod:<domaine>:<sous-clé>`. Le module qui écrit le cache exporte
son `invalidate_*_cache(...)`, et les routes qui modifient les données sources l'appellent.

---

## 3. TypeScript / Angular

- Composants : `nom-du-composant.component.ts`, sélecteur `app-nom-du-composant`,
  répertoire du même nom.
- Services : `nom.service.ts`, classe `NomService`.
- Toujours : `standalone: true`, `changeDetection: ChangeDetectionStrategy.OnPush`,
  `inject()`, signals, `@if` / `@for`.
- État local en `signal()`, dérivé en `computed()`. Un `effect()` ne sert qu'aux effets
  de bord — et toute lecture « pour information » à l'intérieur passe par `untracked()`.
- Un service par domaine d'API, URLs construites depuis `environment.apiUrl`.
- Erreurs HTTP traitées au niveau du composant (toast ou signal `error`).
- Partage de lien → `ShareButtonComponent` / `ShareService`, jamais réimplémenté.
- Images de liste → `loading="lazy"` ; image hero above-the-fold → sans lazy.
- Aucun `onerror=` / `onload=` inline dans un template : la CSP les bloque en production.
  Utiliser `ImgFallbackDirective`.

---

## 4. SCSS

Règle unique et non négociable : **aucune couleur hex en dur** dans un `.scss` de composant.

```scss
@use 'variables' as v;
@use 'mixins' as m;

.cta { @include m.btn-ghost(v.$primary); }
.badge-ok { background: rgba(v.$tag-green, 0.12); }
```

Le thème clair/sombre repose sur `data-theme` posé sur `<html>` par `ThemeService` ;
les variables de fond et de texte sont exposées en custom properties (`var(--bg-surface)`,
`var(--text-primary)`). Un hex en dur casse le thème clair silencieusement.

Tableau des variables et des mixins disponibles : `CONTRIBUTING.md` § SCSS.

---

## 5. Tests

Deux couches, des deux côtés :

- **Backend** : factories `factory-boy` (`tests/factories/`) pour *construire*, scénarios
  nommés (`tests/scenarios/`) pour *représenter un cas métier*. Avant de créer un objet,
  vérifier qu'un scénario ne couvre pas déjà le cas. Les montants ne s'inventent pas :
  ils se dérivent des formules du modèle.
- **Frontend** : données de référence typées (`src/testing/data/`) reproduisant exactement
  la forme des réponses Flask, et mocks `createMock*()` (`src/testing/mocks/`).

Toute règle d'autorisation nouvelle exige **deux** tests : le cas autorisé et le cas refusé.

---

## 6. Communication utilisateur — `updates.json`

Toute fonctionnalité visible par un utilisateur donne lieu à une entrée dans `updates.json`
(racine du projet), source des emails envoyés depuis le module Support de l'admin. Format,
catégories et règles de rédaction : `CONTRIBUTING.md` § updates.json.

En résumé : français, ton direct, `short` = une phrase utilisable comme objet d'email,
`detail` = 2–3 phrases orientées bénéfice, aucun terme technique, `sent_at: null`.
Les refactorisations internes et les changements d'infrastructure ne s'y écrivent pas.
