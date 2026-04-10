# Tutorial edit-track — Partie 2 : le Template (.html)

---

## Vue d'ensemble : structure de la page

Le template est organisé en deux grandes parties :

1. **Les états** (loading / erreur / succès) — toujours en dehors du formulaire, toujours en premier
2. **Le contenu principal** — le formulaire proprement dit, affiché seulement quand tout va bien

```
edit-wrapper
 ├── @if loading()         → spinner
 ├── @if error()           → bandeau rouge
 ├── @if success()         → bandeau vert
 └── @if !loading && ...   → form.edit-card
      ├── card-header      (cover + champs principaux)
      ├── card-divider
      ├── card-section     (prix)
      ├── card-divider
      ├── card-section     (tags)
      ├── card-divider
      ├── card-section     (fichiers)
      ├── card-divider
      └── card-footer      (bouton submit)
```

---

## Les états : loading, error, success

```html
@if (loading()) {
  <div class="state-loading">
    <div class="spinner"></div>
    <span>Chargement du beat…</span>
  </div>
}

@if (error() && !loading()) {
  <div class="state-error">
    <i class="bi bi-exclamation-triangle-fill"></i>
    {{ error() }}
  </div>
}

@if (success()) {
  <div class="state-success">
    <i class="bi bi-check-circle-fill"></i>
    Beat mis à jour ! Redirection…
  </div>
}
```

Ces trois blocs sont mutuellement exclusifs dans la pratique (on est soit en chargement, soit en erreur, soit en succès, soit dans le formulaire). La condition `error() && !loading()` évite d'afficher le bandeau d'erreur pendant le chargement initial si un timeout se produit avant même que le spinner disparaisse.

`{{ error() }}` est l'interpolation Angular : on affiche le contenu du signal `error` directement dans le DOM. Si `error()` vaut `'Erreur lors du chargement du track.'`, c'est ce texte qui apparaît.

---

## La condition principale : `@if (!loading() && !error() && !success())`

```html
@if (!loading() && !error() && !success()) {
  <form class="edit-card" (ngSubmit)="onSubmit()">
    ...
  </form>
}
```

Le formulaire ne s'affiche que si : on a fini de charger, il n'y a pas d'erreur, et on n'est pas en état de succès. Si l'une de ces trois conditions est vraie, l'utilisateur voit l'état correspondant à la place du formulaire.

`(ngSubmit)="onSubmit()"` dit à Angular : quand ce formulaire est soumis (via le bouton `type="submit"` ou la touche Entrée), appelle la méthode `onSubmit()` du composant. C'est une directive de `FormsModule` — sans cet import dans le `.ts`, ça ne fonctionnerait pas.

---

## L'en-tête : cover + champs principaux côte à côte

```html
@if (track(); as t) {
  <div class="card-header">
    ...
  </div>
}
```

`@if (track(); as t)` est une directive Angular 17+. Elle fait deux choses en même temps :
- Elle vérifie que `track()` n'est pas `null` (le signal est rempli dans `ngOnInit()` après le GET)
- Elle nomme le résultat `t` pour éviter d'écrire `track()!.title` partout dans ce bloc

Sans le `as t`, on devrait écrire `track()!.title`, `track()!.bpm`... Le `!` ("non-null assertion") dirait à TypeScript "je sais que c'est pas null ici", mais c'est verbeux et potentiellement dangereux. Le `as t` est plus propre et plus expressif.

### La cover avec remplacement intégré

```html
<div class="header-cover">
  <img [src]="getImageUrl(t.image_file)"
       [alt]="t.title"
       onerror="this.src='assets/placeholder-track.png'" />

  <label class="cover-replace-btn" title="Remplacer l'image">
    <i class="bi bi-camera-fill"></i>
    <input type="file" accept="image/*" (change)="onFileSelected($event, 'image')" />
  </label>

  @if (fileImage()) {
    <span class="cover-new-badge">
      <i class="bi bi-check-circle-fill"></i> {{ fileImage()!.name }}
    </span>
  }
</div>
```

`[src]="getImageUrl(t.image_file)"` : le `[...]` indique un binding Angular — la valeur entre guillemets est du TypeScript évalué, pas du texte brut. On appelle `getImageUrl()` avec le chemin stocké en base (`images/tracks/mon_beat.png`) pour obtenir l'URL complète servie par Flask.

`onerror="this.src='assets/placeholder-track.png'"` : c'est du JavaScript natif (pas Angular) déclenché par le navigateur si l'image ne charge pas (404, réseau...). C'est un fallback de dernier recours, différent du cas où `image_file` est `null` (géré dans `getImageUrl()`).

Le `<label>` avec `<input type="file">` caché à l'intérieur est une astuce HTML classique : cliquer sur le label déclenche l'input caché. On peut donc styler le label librement (ici un bouton rond avec une icône caméra) sans se battre avec le rendu natif peu agréable des `<input type="file">`. `accept="image/*"` filtre les fichiers proposés dans la fenêtre système.

`(change)="onFileSelected($event, 'image')"` : le `(...)` indique un event binding Angular. `$event` est l'objet événement natif du navigateur (qui contient les fichiers sélectionnés). `'image'` est le discriminant qu'on passe à la fonction pour qu'elle sache quel signal mettre à jour.

`@if (fileImage()) { ... }` : si l'utilisateur a sélectionné une image, on affiche un badge vert avec le nom du fichier. `fileImage()!.name` accède au nom du fichier (`File.name` est une propriété native JavaScript). Le `!` dit à TypeScript "ici fileImage() n'est pas null" — la condition `@if (fileImage())` le garantit.

### Les champs principaux dans header-meta

```html
<div class="header-meta">
  <div class="header-nav">
    <a [routerLink]="['/track', trackId]" class="btn-back">
      <i class="bi bi-arrow-left"></i> Retour
    </a>
    <span class="page-label"><i class="bi bi-pencil-fill"></i> Modifier le beat</span>
  </div>

  <div class="field">
    <label for="title">Titre *</label>
    <input type="text" id="title" name="title"
           placeholder="Nom de votre beat"
           [ngModel]="title()" (ngModelChange)="title.set($event)"
           required />
  </div>

  <div class="row-2">
    <div class="field">
      <label for="bpm">BPM *</label>
      <input type="number" id="bpm" name="bpm"
             min="60" max="220" placeholder="ex. 140"
             [ngModel]="bpm()" (ngModelChange)="bpm.set($event ? +$event : null)"
             required />
    </div>
    <div class="field">
      <label for="key">Gamme *</label>
      <select id="key" name="key"
              [ngModel]="key()" (ngModelChange)="key.set($event)" required>
        <option value="">Choisir</option>
        @for (k of availableKeys; track k) {
          <option [value]="k">{{ k }}</option>
        }
      </select>
    </div>
  </div>

  <div class="field">
    <label for="style">Style</label>
    <input type="text" id="style" name="style"
           placeholder="Ex: Trap, R&B, Afrobeats…"
           [ngModel]="style()" (ngModelChange)="style.set($event)" />
  </div>
</div>
```

`[routerLink]="['/track', trackId]"` : Angular Router construit l'URL `/track/42` depuis le tableau. On préfère cette syntaxe à `href="/track/42"` car `routerLink` fait une navigation SPA (sans rechargement de page) et peut recevoir des variables dynamiques.

**Le pattern `[ngModel]` + `(ngModelChange)` :**
C'est le binding bidirectionnel manuel avec les signals.
- `[ngModel]="title()"` lit le signal et affiche sa valeur dans le champ (sens signal → DOM)
- `(ngModelChange)="title.set($event)"` met à jour le signal quand l'utilisateur tape (sens DOM → signal)

On aurait pu écrire `[(ngModel)]="..." ` (banana-in-a-box) mais ça ne fonctionne pas directement avec les signals — seulement avec les variables classiques. Séparer les deux directions est donc obligatoire ici.

**`+$event` sur le BPM :**
`(ngModelChange)="bpm.set($event ? +$event : null)"` — `$event` est une string (les inputs HTML renvoient toujours des strings). `+$event` est un cast JavaScript vers number (équivalent de `Number($event)`). `$event ? +$event : null` dit : si la valeur n'est pas vide, convertis-la en nombre ; sinon, mets `null` (champ vide = pas de valeur).

**Le `@for` sur availableKeys :**
```html
@for (k of availableKeys; track k) {
  <option [value]="k">{{ k }}</option>
}
```
`@for` est la directive de boucle Angular 17+. `track k` est la clé de suivi pour les performances — Angular l'utilise pour savoir quels éléments ont changé lors d'une mise à jour. Pour une liste de strings immuables comme les gammes musicales, `track k` (la valeur elle-même) suffit.

---

## Section Prix

```html
<div class="card-section">
  <h3 class="section-title">Prix</h3>
  <div class="row-3">
    <div class="field">
      <label for="price_mp3">MP3 (€)</label>
      <input type="number" id="price_mp3" name="priceMp3"
             step="0.01" min="0"
             [ngModel]="priceMp3()" (ngModelChange)="priceMp3.set(+$event)" />
    </div>
    <div class="field">
      <label for="price_wav">WAV (€)</label>
      <input type="number" id="price_wav" name="priceWav"
             step="0.01" min="0"
             [ngModel]="priceWav()" (ngModelChange)="priceWav.set(+$event)" />
    </div>
    <div class="field">
      <label for="price_stems">Stems (€)</label>
      <input type="number" id="price_stems" name="priceStems"
             step="0.01" min="0"
             [ngModel]="priceStems()" (ngModelChange)="priceStems.set(+$event)" />
    </div>
  </div>
</div>
```

`step="0.01"` permet à l'input d'accepter des nombres décimaux avec deux chiffres après la virgule (9.99€ par exemple). Sans `step`, les inputs `number` n'acceptent que des entiers dans certains navigateurs.

`(ngModelChange)="priceMp3.set(+$event)"` : le `+` convertit la string de l'input en nombre. Ici pas de `? ... : null` comme pour le BPM car un prix vide peut légitimement valoir 0, et c'est la valeur par défaut du signal.

---

## Section Tags : les pills interactives

```html
@if (availableTags().length > 0) {
  <div class="card-section">
    <h3 class="section-title">Tags <span class="optional">(optionnel)</span></h3>
    <div class="tag-pills">
      @for (tag of availableTags(); track tag.id) {
        <button type="button" class="tag-pill"
                [class.selected]="isTagSelected(tag.id)"
                [style.--tag-color]="tag.category.color"
                (click)="toggleTag(tag.id)">
          {{ tag.name }}
        </button>
      }
    </div>
  </div>
}
```

`@if (availableTags().length > 0)` : on n'affiche la section que si des tags ont été chargés depuis l'API. Si `tagsService.loadTags()` n'a pas encore terminé ou a échoué silencieusement, cette section reste invisible plutôt que de montrer un bloc vide.

`track tag.id` dans le `@for` : ici on utilise l'`id` du tag comme clé plutôt que la valeur entière. C'est une bonne pratique pour les listes d'objets — l'ID est unique et stable.

`[class.selected]="isTagSelected(tag.id)"` : binding conditionnel de classe CSS. Si `isTagSelected(tag.id)` retourne `true`, la classe `selected` est ajoutée à ce bouton. C'est ainsi que les pills se colorent quand on les sélectionne — la logique CSS de la couleur active est dans le SCSS.

`[style.--tag-color]="tag.category.color"` : on injecte une CSS custom property directement depuis Angular. Dans le SCSS, `.tag-pill.selected` utilise `var(--tag-color)` pour sa couleur de bordure et de texte. Chaque pill a donc sa propre couleur de catégorie, définie par les données de l'API.

`type="button"` sur les boutons de pills : **important**. Dans un `<form>`, tout bouton sans attribut `type` a `type="submit"` par défaut. Sans `type="button"`, cliquer sur un tag soumettrait le formulaire — comportement indésirable.

---

## Section Fichiers : remplacement optionnel

```html
<div class="card-section">
  <h3 class="section-title">Remplacer les fichiers <span class="optional">(optionnel)</span></h3>

  <div class="files-grid">
    <label class="file-label">
      <i class="bi bi-file-earmark-music-fill"></i>
      <span>
        <strong>MP3</strong>
        @if (fileMp3()) {
          <em class="file-name">{{ fileMp3()!.name }}</em>
        } @else {
          <em>Remplacer (.mp3)</em>
        }
      </span>
      <input type="file" accept=".mp3" (change)="onFileSelected($event, 'mp3')" />
    </label>

    <!-- Même pattern pour WAV et Stems -->
  </div>
</div>
```

Le pattern `<label>` avec `<input type="file">` caché à l'intérieur est le même que pour la cover. La différence : ici les labels sont des éléments de liste (`.file-label`) et non un overlay positionné sur une image.

Le `@if (fileMp3()) / @else` donne un feedback immédiat à l'utilisateur : soit il voit le nom du fichier sélectionné (en violet), soit l'invite "Remplacer (.mp3)". L'utilisateur sait ainsi exactement ce qui sera envoyé lors de la soumission.

**MP3 dans les fichiers :** on peut remplacer le MP3 en édition — Flask va régénérer la preview watermarquée depuis ce nouveau fichier. C'est différent d'une création (`post_track`) où le MP3 est obligatoire. Ici, si on ne sélectionne rien, le fichier existant reste intact.

---

## Le bouton submit

```html
<div class="card-footer">
  <button type="submit" class="btn-submit" [disabled]="loading()">
    @if (loading()) {
      <span class="spinner-sm"></span> Mise à jour…
    } @else {
      <i class="bi bi-floppy-fill"></i> Enregistrer les modifications
    }
  </button>
</div>
```

`[disabled]="loading()"` désactive le bouton pendant que la requête PUT est en cours. Ça évite les doubles soumissions : si l'utilisateur clique deux fois rapidement, le deuxième clic n'a aucun effet.

Le `@if (loading())` à l'intérieur du bouton change son contenu : soit un spinner + texte "Mise à jour…", soit l'icône disquette + "Enregistrer". L'utilisateur a toujours un retour visuel sur l'état de la requête.

À noter : `loading` est initialisé à `true` mais il est remis à `false` à la fin du `ngOnInit()`. Il n'est pas remis à `true` dans `onSubmit()` — dans une version plus robuste, on le ferait pour désactiver le bouton pendant la requête PUT. C'est un point d'amélioration.
