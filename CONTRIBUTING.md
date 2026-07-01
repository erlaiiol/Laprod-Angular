# Contribuer à LaProd

Merci de contribuer à LaProd. Ce document explique comment travailler sur le projet de façon cohérente avec son architecture.

---

## Workflow Git

### Branches

- `master` — branche principale, toujours déployable en production
- `prodbranch` — branche de travail principale (PR → master)
- `feature/xxx` — nouvelles fonctionnalités
- `fix/xxx` — corrections de bugs

### Commits

Utiliser des messages courts et impératifs en français :

```
feat: ajout du système de playlists avec image de couverture
fix: correction du serializer Decimal pour les prix beatmaker
refactor: passage de hex hardcodés aux variables SCSS
```

### Pull Requests

Toujours créer une PR depuis ta branche vers `master`. La PR doit :
- Passer `tsc --noEmit` sans erreur
- Ne pas casser le build Angular (`ng build`)
- Avoir été testée manuellement (golden path + edge cases)

---

## Backend Flask

### Structure des routes

Chaque domaine fonctionnel a son propre Blueprint dans `routes/` :

```python
# routes/mon_blueprint.py
from flask import Blueprint
bp = Blueprint('mon_bp', __name__)

@bp.route('/api/mon-endpoint', methods=['GET'])
def ma_route():
    ...
```

Enregistrement dans `app.py` :
```python
from routes.mon_blueprint import bp as mon_bp
app.register_blueprint(mon_bp)
```

### CRUD helpers

Utiliser les fonctions de `helpers.py` pour les opérations CRUD courantes plutôt que de réimplémenter la logique :

```python
from helpers import get_or_404, paginate_query
```

### Serializers

La sérialisation JSON des entités SQLAlchemy est centralisée dans `serializers.py`. Ne pas sérialiser les modèles inline dans les routes — utiliser ou créer une fonction dans `serializers.py`.

**Attention aux types Decimal** : toujours envelopper les champs monétaires avec `float()` avant de les passer à `jsonify` (SQLAlchemy Numeric → Python Decimal → JSON string sinon).

```python
'price_mp3': float(t.price_mp3) if t.price_mp3 is not None else None,
```

### Tâches asynchrones

Les opérations longues (traitement audio, envoi d'emails) se font via RQ Workers dans `tasks/`. Ne jamais bloquer une requête HTTP avec une opération longue.

---

## Frontend Angular

### Architecture

- **Pages** (`src/app/pages/`) — composants intelligents (fetch données, logique métier)
- **Components** (`src/app/components/`) — composants présentationnels réutilisables
- **Services** (`src/app/services/`) — accès API, état partagé (signals)
- **Guards** (`src/app/guards/`) — protection des routes

### Règles Angular

- Toujours utiliser des **standalone components** (pas de NgModules)
- Utiliser les **signals** Angular pour l'état local : `signal()`, `computed()`, `effect()`
- Utiliser le **nouveau control flow** `@if`, `@for`, `@switch` (pas `*ngIf`, `*ngFor`)
- Injecter les services avec `inject()` (pas via le constructor)

```typescript
// ✅ Correct
readonly auth = inject(AuthService);
loading = signal(false);
count   = computed(() => this.items().length);

// ❌ À éviter
constructor(private auth: AuthService) {}
```

### Services

- Chaque endpoint API a son service dédié
- Les URLs d'API utilisent `environment.apiUrl`
- Les erreurs HTTP sont gérées au niveau du composant (toast ou signal `error`)

---

## SCSS — Système de couleurs

### Règle fondamentale

**Ne jamais utiliser de couleurs hex hardcodées** dans les fichiers `.scss` des composants.

Utiliser uniquement les variables SCSS de `src/styles/_variables.scss` :

```scss
@use 'variables' as v;  // en tête de chaque fichier .scss

// ✅ Correct
color: v.$primary;           // rouge CTA
background: v.$bg-surface;
border: 1px solid v.$bg-border;

// ✅ Correct pour rgba
background: rgba(v.$tag-green, 0.12);

// ❌ À éviter
color: #A51929;
background: rgba(16, 185, 129, 0.12);
```

### Variables disponibles

| Variable | Valeur | Usage |
|----------|--------|-------|
| `v.$primary` | `#d52424` | Boutons CTA (acheter, s'inscrire, premium) |
| `v.$primary-dark` | `#bb0000` | Hover CTA |
| `v.$primary-darker` | `#8c0000` | État actif / pressed |
| `v.$gold` | `#eab308` | Badge Pro, indicateurs premium |
| `v.$gold-light` | `#fde047` | Hover gold |
| `v.$bg-base` | `#1c2028` | Fond global |
| `v.$bg-surface` | `#2f3448` | Cards, modals |
| `v.$bg-elevated` | `#363f50` | Inputs, zones surélevées |
| `v.$bg-border` | `#404956` | Bordures |
| `v.$text-primary` | `#f3f4f6` | Texte principal |
| `v.$text-secondary` | `#94a3b8` | Labels, captions |
| `v.$text-muted` | `#64748b` | Hints, placeholders |
| `v.$tag-violet` | `#8b5cf6` | Tags de catégorie (Hip-Hop, Trap…) |
| `v.$tag-blue` | `#2cfff4` | Tags type/format |
| `v.$tag-green` | `#10b981` | Succès, téléchargement gratuit |
| `v.$tag-red` | `#ef4444` | Erreurs, suppression |
| `v.$tag-orange` | `#f97316` | Avertissements |

Les CSS custom properties équivalentes (`var(--primary)`, `var(--gold)`…) sont toutes disponibles globalement sans import.

### Mixins

```scss
@use 'mixins' as m;

// Badge pill (dark bg + vivid border)
@include m.badge(v.$tag-green, v.$tag-green-dark);

// Ghost button : fond noir + liseret blanc (opacity 0.7) → se remplit de $color au hover
// Le texte au repos est toujours blanc. Au hover, $hover-text (défaut: #fff).
// Pour les couleurs très claires (ex. tag-blue/cyan), passer #000 en 2e argument.
@include m.btn-ghost(v.$primary);              // rouge → texte blanc au hover
@include m.btn-ghost(v.$tag-blue, #000);       // cyan → texte noir au hover
@include m.btn-ghost-sm(v.$tag-orange);        // variante compacte
```

### Boutons remplis (CTA primaire)

Quand un bouton doit être rempli par défaut (pas ghost), override le fond après l'include :

```scss
.mon-btn-cta {
  @include m.btn-ghost(v.$primary);
  background:   v.$primary;   // filled par défaut
  color:        v.$white;
  border-color: v.$primary;

  &:hover { background: v.$primary-dark; border-color: v.$primary-dark; }
}
```

---

## Stratégie de tests

### Principe général

Les données de test sont organisées en deux couches :

- **Layer 1 — Factories** : savent *comment construire* un objet (avec des valeurs par défaut sensées)
- **Layer 2 — Scénarios** : définissent *quels cas métiers* tester (objets nommés, stables, documentés)

L'objectif est d'éviter de recréer les mêmes objets dans chaque fichier de test.

---

### Backend Python (pytest + factory-boy)

#### Factories (`tests/factories/`)

Les factories factory-boy fournissent des valeurs par défaut et permettent de surcharger n'importe quel champ :

```python
from tests.factories.user_factory import UserFactory

def test_something(db, bound_factories):
    # Utilisation directe avec surcharge
    user = UserFactory(subscription_plan='pro', is_beatmaker=True)
```

La fixture `bound_factories` (définie dans `tests/factories/__init__.py`) lie les factories à la session SQLAlchemy courante. Elle doit être déclarée comme paramètre du test ou d'une fixture parente.

#### Scénarios nommés (`tests/scenarios/`)

Les scénarios sont des fixtures pytest représentant des cas métiers documentés :

```python
# Dans ton fichier de test :
from tests.scenarios.users import user_mix_engineer_low_min, user_artist

def test_checkout_pricing(client, user_mix_engineer_low_min, artist_headers):
    ...
```

**Catalogue des scénarios disponibles :**

| Module | Fixtures |
|---|---|
| `scenarios.users` | `user_free`, `user_pro`, `user_artist`, `user_pending`, `user_admin`, `user_mix_engineer_low_min`, `user_mix_engineer_high_min`, `user_mix_engineer_autoforce`, `user_mix_engineer_mastering`, `user_mix_engineer_producer`, `user_stripe_ready` |
| `scenarios.tracks` | `track_default_prices`, `track_custom_exclusive`, `track_exclusive_sold`, `track_high_price_mp3` |
| `scenarios.mixmaster_orders` | `order_awaiting`, `order_accepted`, `order_delivered`, `order_revision1`, `order_revision2`, `order_completed`, `order_completed_after_rev1`, `order_rejected`, `order_expired`, `order_all_services` |

#### Quand utiliser un scénario existant vs créer un nouveau ?

- **Scénario existant** : si le cas métier correspond, même partiellement. Créer une fixture locale qui s'appuie dessus via override.
- **Nouveau scénario** : si le cas couvre une branche de logique non encore représentée (nouveau statut, nouveau flag, comportement financier différent).
- **Factory directe** : si l'objet est vraiment unique au test et ne sera pas réutilisé.

#### Montants financiers

**Ne jamais inventer les montants.** Toujours les dériver des formules du modèle :

```
deposit_amount   = total × 30%
remaining_amount = total × 70%
engineer_revenue = total × 90%
final_transfer (0 révision)  = total × 70% × 90% = total × 63%
final_transfer (1 révision)  = (total × 60%) × 90% = total × 54%
revision_transfer = total × 10% × 90%
refund_amount    = remaining_amount = total × 70%
```

#### Ajouter un scénario utilisateur

1. Ajouter la fixture dans le fichier approprié de `tests/scenarios/`
2. Documenter le cas métier dans la docstring (quels champs, quelle branche logique)
3. Utiliser `_teardown_user(db, u)` du module `tests.scenarios` pour le teardown wallet+user

```python
@pytest.fixture()
def user_mon_cas(db, bound_factories):
    """Cas métier : [décrire ce qui est unique ici]."""
    from tests.factories.user_factory import UserFactory
    u = UserFactory(mon_champ='ma_valeur')
    yield u
    _teardown_user(db, u)
```

---

### Frontend Angular (Vitest + Angular TestBed)

#### Données de référence (`src/testing/data/`)

Des objets TypeScript typés pour chaque entité, correspondant exactement à la forme des réponses Flask :

```typescript
import { USER_FREE_BEATMAKER, USER_ADMIN, makeLoginSuccess } from '../../../testing/data';
import { TRACK_STANDARD, TRACK_HIGH_PRICE, makeTrackDetail } from '../../../testing/data';
import { ORDER_AWAITING, ORDER_REVISION1, CHECKOUT_STANDARD } from '../../../testing/data';
import { WALLET_WITH_BALANCE, TXN_PENDING_BEAT_SALE } from '../../../testing/data';
```

Pour créer une variante légère d'un objet existant :

```typescript
const myTrack = { ...TRACK_STANDARD, price_mp3: 50, title: 'Custom Beat' };
```

#### Mocks de services (`src/testing/mocks/`)

Des factories `createMock*()` qui retournent des objets `vi.fn()` avec des retours cohérents :

```typescript
import { createMockAuthService, createMockTrackService } from '../../../testing/mocks';

// Retours par défaut (USER_FREE_BEATMAKER, TRACK_STANDARD)
const authSvc  = createMockAuthService();
const trackSvc = createMockTrackService();

// Surcharger pour un test spécifique
const adminSvc = createMockAuthService(USER_ADMIN);
adminSvc.isAdmin.mockReturnValue(true);

// Dans TestBed
await TestBed.configureTestingModule({
  imports: [MonComposant],
  providers: [
    { provide: AuthService,  useValue: authSvc  },
    { provide: TrackService, useValue: trackSvc },
  ],
}).compileComponents();
```

---

## Checklist PR

- [ ] `tsc --noEmit` sans erreur
- [ ] Pas de `console.log` oubliés en production
- [ ] Pas de hex hardcodés dans les SCSS
- [ ] Types Decimal Flask → `float()` si champs monétaires ajoutés
- [ ] Pas de logique dans les serializers qui devrait être dans les routes (et inversement)
- [ ] Testé manuellement : golden path + cas d'erreur
- [ ] Responsive vérifié (mobile ≤ 600px)
- [ ] Si nouvel objet de test créé : vérifier qu'un scénario existant ne couvrait pas déjà ce cas
