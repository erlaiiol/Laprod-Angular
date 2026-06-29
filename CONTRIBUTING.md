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

## Checklist PR

- [ ] `tsc --noEmit` sans erreur
- [ ] Pas de `console.log` oubliés en production
- [ ] Pas de hex hardcodés dans les SCSS
- [ ] Types Decimal Flask → `float()` si champs monétaires ajoutés
- [ ] Pas de logique dans les serializers qui devrait être dans les routes (et inversement)
- [ ] Testé manuellement : golden path + cas d'erreur
- [ ] Responsive vérifié (mobile ≤ 600px)
