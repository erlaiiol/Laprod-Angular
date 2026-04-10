# Tutorial edit-track — Partie 3 : les Styles (.scss)

---

## Vue d'ensemble : SCSS vs CSS, et pourquoi on utilise les deux

Le fichier SCSS de ce composant utilise deux types de styles :

1. **SCSS** : la syntaxe étendue avec des variables (`$tag-violet`), des règles imbriquées (`&:hover`), et des imports (`@use`)
2. **CSS custom properties** (`--tag-color`) : des variables CSS natives, définies et lues directement dans le navigateur

La distinction est importante :
- Les variables SCSS (`v.$tag-violet`) sont résolues **à la compilation** — elles produisent des valeurs statiques dans le CSS final. On ne peut pas les modifier dynamiquement depuis JavaScript ou Angular.
- Les CSS custom properties (`var(--tag-color)`) sont résolues **au runtime** par le navigateur. On peut les injecter depuis Angular avec `[style.--tag-color]="..."` et chaque élément peut avoir sa propre valeur.

C'est pour ça que les pills de tags utilisent `--tag-color` (couleur dynamique par catégorie venant de l'API) mais les inputs et boutons utilisent `v.$tag-violet` (couleur fixe du design system).

---

## @use 'variables' as v

```scss
@use 'variables' as v;
```

Cela importe le fichier `src/styles/_variables.scss` qui contient toutes les variables de l'application. L'alias `v` permet d'y accéder avec `v.$bg-base`, `v.$tag-violet`, etc.

Grâce à `stylePreprocessorOptions.includePaths: ["src/styles"]` dans `angular.json`, on n'a pas besoin d'écrire le chemin complet — juste `'variables'` suffit.

---

## Layout : une grande carte centrée

```scss
.edit-wrapper {
  min-height: 100vh;
  padding: 2rem 1rem 4rem;
  background: v.$bg-base;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.edit-card {
  width: 100%;
  max-width: 640px;
  background: v.$bg-surface;
  border: 1px solid v.$bg-border;
  border-radius: 12px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
```

`.edit-wrapper` est un conteneur pleine page qui centre horizontalement le contenu. `align-items: center` sur un flexbox en colonne centre les enfants horizontalement (pas verticalement — pour ça il faudrait `justify-content: center`).

`.edit-card` a `max-width: 640px` — au-delà de cette largeur, la carte ne grandit plus. `width: 100%` lui permet quand même d'occuper tout l'espace disponible en dessous de 640px (sur mobile notamment).

`overflow: hidden` est important : il empêche les coins arrondis de `border-radius: 12px` d'être "débordés" par les éléments enfants (comme l'image de cover qui remplirait le coin sans ça).

---

## L'en-tête : grille cover / champs

```scss
.card-header {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 0;
}
```

`display: grid` avec `grid-template-columns: 160px 1fr` crée deux colonnes : la première fait exactement 160px (pour la cover carrée), la seconde prend tout l'espace restant (`1fr` = "1 fraction de l'espace disponible").

`gap: 0` supprime l'espacement entre les deux colonnes — on veut que la cover et les champs soient jointifs pour un effet "carte produit".

---

## La cover : positionnement relatif et overlay

```scss
.header-cover {
  position: relative;
  aspect-ratio: 1;
  background: v.$bg-base;

  img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .cover-replace-btn {
    position: absolute;
    bottom: 8px;
    right: 8px;
    width: 32px;
    height: 32px;
    background: rgba(0, 0, 0, 0.65);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    transition: background 0.15s;
    backdrop-filter: blur(4px);

    &:hover { background: rgba(139, 92, 246, 0.8); }
    input[type="file"] { display: none; }
  }

  .cover-new-badge {
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    background: rgba(25, 135, 84, 0.85);
    ...
  }
}
```

`position: relative` sur `.header-cover` crée un contexte de positionnement pour ses enfants. Ça permet au bouton caméra et au badge d'utiliser `position: absolute` en se référençant à la cover (et non à la page entière).

`aspect-ratio: 1` force la hauteur à être égale à la largeur, quelle que soit la largeur réelle de la colonne. La cover restera carrée même si la carte est redimensionnée.

`object-fit: cover` sur l'image : si les proportions de l'image ne correspondent pas au carré, elle est rognée plutôt que déformée. C'est le comportement attendu pour une cover de musique.

`backdrop-filter: blur(4px)` sur le bouton caméra et le badge : applique un flou gaussien sur ce qui se trouve derrière l'élément. Ça donne un effet "verre dépoli" qui rend les overlays lisibles quelle que soit l'image en dessous. Pas supporté par tous les vieux navigateurs, mais gracefully degradable (le fond semi-transparent reste lisible sans le flou).

Les règles SCSS imbriquées (`img { ... }`, `.cover-replace-btn { ... }`, `&:hover { ... }`) sont compilées en CSS classique. `&` est le sélecteur parent — `&:hover` devient `.cover-replace-btn:hover`. C'est la principale force de SCSS : éviter la répétition des sélecteurs parents.

---

## Les champs : cohérence visuelle

```scss
.field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;

  label {
    font-size: 0.78rem;
    font-weight: 600;
    color: #adb5bd;
  }

  input, select {
    background: v.$bg-elevated;
    border: 1px solid v.$bg-border-subtle;
    border-radius: 6px;
    color: #f8f9fa;
    font-size: 0.88rem;
    padding: 0.5rem 0.7rem;
    width: 100%;
    font-family: inherit;
    transition: border-color 0.2s;

    &:focus { outline: none; border-color: v.$tag-violet; }
    &::placeholder { color: #495057; }
  }

  select option { background: v.$bg-surface; }
}
```

`font-family: inherit` sur les inputs : les navigateurs appliquent leur propre font aux inputs par défaut, différente de celle du reste de la page. `inherit` force les inputs à utiliser la même font que leur parent.

`outline: none` sur `:focus` : supprime le contour bleu natif du navigateur pour le remplacer par notre propre `border-color: v.$tag-violet`. On ne supprime jamais `outline` sans le remplacer — c'est une accessibilité importante (les utilisateurs clavier doivent voir quel champ est actif).

`select option { background: v.$bg-surface }` : force la couleur de fond des options dans le dropdown. Sans ça, les options héritent de la couleur système (blanc sur Mac, gris sur Windows) — sur un dark theme, c'est illisible.

---

## Les grilles de champs : row-2 et row-3

```scss
.row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.row-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0.75rem;
}
```

Des classes utilitaires simples pour aligner deux ou trois champs côte à côte. Le responsive les passe en colonne unique en dessous de 520px (voir section responsive).

---

## Les tags : pills avec couleur dynamique

```scss
.tag-pill {
  padding: 0.25rem 0.65rem;
  border-radius: 20px;
  border: 1px solid v.$bg-border-subtle;
  background: transparent;
  color: #6c757d;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background 0.15s;

  &:hover {
    border-color: var(--tag-color, v.$tag-violet);
    color: #f8f9fa;
  }

  &.selected {
    border-color: var(--tag-color, v.$tag-violet);
    color: var(--tag-color, v.$tag-violet);
    background: color-mix(in srgb, var(--tag-color, v.$tag-violet) 12%, transparent);
  }
}
```

`var(--tag-color, v.$tag-violet)` : lit la custom property `--tag-color` injectée par Angular (`[style.--tag-color]="tag.category.color"`). Le deuxième argument est le fallback — si `--tag-color` n'est pas définie (pill sans catégorie), on utilise le violet par défaut.

`color-mix(in srgb, var(--tag-color) 12%, transparent)` : fonction CSS native (moderne) qui mélange deux couleurs. Ici : 12% de la couleur du tag + 88% de transparent. Ça produit une teinte très légère de la couleur du tag comme fond de la pill sélectionnée. Le résultat est visuellement cohérent quelle que soit la couleur de catégorie.

`transition: border-color 0.15s, color 0.15s, background 0.15s` : on anime les trois propriétés qui changent au hover et à la sélection. `transition: all 0.15s` serait plus court mais moins performant — le navigateur n'animera que ce qui est nécessaire.

---

## Les fichiers audio : label stylisé

```scss
.file-label {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: v.$bg-elevated;
  border: 1px solid v.$bg-border-subtle;
  border-radius: 6px;
  padding: 0.6rem 0.9rem;
  cursor: pointer;
  transition: border-color 0.15s;

  &:hover { border-color: v.$tag-violet; }

  > i { ... }
  > span { ... }

  input[type="file"] { display: none; }
}
```

`> i` et `> span` : le `>` est le sélecteur d'enfant direct en CSS. Ça cible uniquement les `<i>` et `<span>` qui sont des enfants immédiats de `.file-label`, pas les éventuels descendants plus profonds.

`input[type="file"] { display: none; }` : cache complètement l'input natif. Le clic sur le label suffit à déclencher la sélection de fichier (comportement natif HTML — un `<label>` cliqué déclenche l'`<input>` associé ou l'input contenu à l'intérieur du label).

---

## Le bouton submit

```scss
.btn-submit {
  width: 100%;
  padding: 0.7rem;
  background: v.$tag-violet;
  border: none;
  border-radius: 7px;
  color: #fff;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  transition: filter 0.15s;

  &:hover:not(:disabled) { filter: brightness(1.15); }
  &:disabled { opacity: 0.4; cursor: not-allowed; }
}
```

`filter: brightness(1.15)` au hover : une technique simple pour éclaircir un bouton sans avoir à définir une couleur de hover spécifique. `1.0` = couleur d'origine, `1.15` = 15% plus clair. Ça fonctionne avec n'importe quelle couleur de fond.

`:hover:not(:disabled)` : on n'applique l'effet hover que si le bouton n'est pas désactivé. Sans le `:not(:disabled)`, un bouton disabled afficherait quand même l'effet hover, ce qui serait trompeur.

`cursor: not-allowed` sur disabled : feedback visuel immédiat que l'action n'est pas disponible.

---

## Les spinners : animation CSS pure

```scss
.spinner, .spinner-sm {
  border-radius: 50%;
  border-top-color: transparent;
  animation: spin 0.7s linear infinite;
}
.spinner    { width: 20px; height: 20px; border: 2px solid #6c757d; border-top-color: transparent; }
.spinner-sm { width: 13px; height: 13px; border: 2px solid currentColor; border-top-color: transparent; }

@keyframes spin { to { transform: rotate(360deg); } }
```

Le spinner est un cercle (`border-radius: 50%`) avec une bordure complète sauf un côté (`border-top-color: transparent`). L'animation `spin` le fait tourner à 360°. C'est la technique CSS la plus légère pour un spinner — aucun JS, aucune image, juste de la géométrie.

`.spinner-sm` utilise `currentColor` pour sa bordure : ça prend la couleur de texte du parent. Donc sur un bouton blanc, le spinner sera blanc. On n'a pas besoin de définir une couleur spécifique.

---

## Responsive : mobile < 520px

```scss
@media (max-width: 520px) {
  .card-header {
    grid-template-columns: 1fr;
  }

  .header-cover {
    aspect-ratio: 16 / 7;
  }

  .row-2, .row-3 { grid-template-columns: 1fr; }
}
```

En dessous de 520px (téléphone portrait), la grille cover / champs passe en colonne : la cover prend toute la largeur en haut, les champs se déploient en dessous. `aspect-ratio: 16 / 7` remplace le `1:1` (carré) pour que la cover en mode "bandeau" ne prenne pas trop de hauteur sur mobile.

Les `.row-2` et `.row-3` passent en colonne unique — les champs BPM/Gamme et les trois prix se superposent plutôt que d'être côte à côte. Sur un écran de 360px de large, des colonnes de 120px seraient trop étroites pour être utilisables.
