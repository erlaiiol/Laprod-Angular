# Tutorial edit-track — Partie 1 : le TypeScript (.ts)

---

## Vue d'ensemble : ce que fait ce composant

Ce composant a deux responsabilités :
1. **Lire** les données d'un track existant via `getTrackDetail()` (Flask → Angular) et les afficher dans un formulaire pré-rempli.
2. **Écrire** les modifications de l'utilisateur via `putTrack()` (Angular → Flask) quand le formulaire est soumis.

C'est le pattern classique d'un formulaire d'édition : GET pour afficher, PUT pour sauvegarder.

---

## Les imports

```typescript
import { Component, inject, signal } from '@angular/core';
import { OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { MUSICAL_KEYS, TrackDetail, TrackService } from '../../services/track.service';
import { CudTrackService } from '../../services/cud-track.service';
import { Tag, TagsService } from '../../services/tags.service';
import { CommonModule } from '@angular/common';
```

À noter : `OnInit` aurait pu être importé sur la même ligne que `Component` et `inject`. L'importer séparément fonctionne mais c'est moins propre. Dans Angular moderne, tous les imports `@angular/core` se regroupent sur une seule ligne.

`FormsModule` est indispensable dès qu'on utilise `[ngModel]` ou `(ngModelChange)` dans le template. Sans lui, Angular ne reconnaît pas ces directives et le formulaire ne fait rien.

`MUSICAL_KEYS` est une constante exportée depuis `track.service.ts` — c'est simplement un tableau de strings comme `['A minor', 'A major', ...]`. Elle est partagée avec `upload-track.component.ts` ; c'est pour ça qu'elle vit dans le service plutôt que répétée dans chaque composant.

---

## Les signals : variables réactives

```typescript
// UI — état de la page
loading = signal(true);
error   = signal<string | null>(null);
success = signal(false);

// Route
trackId : number = 0;

// Formulaire — un signal par champ
track       = signal<TrackDetail | null>(null);
title       = signal('');
bpm         = signal<number | null>(null);
key         = signal('');
style       = signal('');
priceMp3    = signal(0);
priceWav    = signal(0);
priceStems  = signal(0);
selectedTagIds = signal<number[]>([]);
fileImage   = signal<File | null>(null);
fileMp3     = signal<File | null>(null);
fileWav     = signal<File | null>(null);
fileStems   = signal<File | null>(null);
```

Un signal Angular est une variable dont Angular "surveille" les changements. Quand un signal change, chaque endroit du template qui l'utilise se met à jour automatiquement — sans qu'on ait besoin d'appeler manuellement une fonction de re-rendu.

On note que `trackId` n'est pas un signal : c'est une variable TypeScript ordinaire. C'est intentionnel — l'ID ne change jamais pendant la vie du composant (on est sur `/edit-track/42`, l'ID reste 42), donc il n'y a aucune raison de le rendre réactif. Un signal a un coût ; on ne le crée que quand c'est utile.

`track` (signal du TrackDetail complet) sert uniquement à alimenter la section aperçu du HTML (`@if (track(); as t)`). Les autres signals (title, bpm, etc.) servent eux au formulaire. Les deux familles coexistent.

---

## Les injections de services

```typescript
private route           = inject(ActivatedRoute);
private router          = inject(Router);
private trackService    = inject(TrackService);
private cudTrackService = inject(CudTrackService);
private tagsService     = inject(TagsService);
```

`inject()` est la manière moderne de récupérer un service dans un composant Angular (depuis Angular 14). C'est l'équivalent de déclarer le service dans le `constructor()`, mais au niveau de la classe directement — plus lisible, et fonctionnel hors constructeur.

La séparation entre `TrackService` (lecture) et `CudTrackService` (écriture) est volontaire. `TrackService` est utilisé partout dans l'app (home, track-detail, player...) ; `CudTrackService` n'intervient que sur les pages d'écriture. Si on devait modifier la logique d'upload, on ne touche pas au service de lecture.

---

## ngOnInit() : initialisation du composant

```typescript
ngOnInit(): void {

  this.tagsService.loadTags();

  this.trackId = Number(this.route.snapshot.paramMap.get('id'));

  if (!this.trackId) {
    this.error.set('ID du track manquant. Erreur de navigation.');
    this.loading.set(false);
    return;
  }

  this.trackService.getTrackDetail(this.trackId).subscribe({
    next: (res) => {
      const track = res.data.track;
      this.title.set(track.title);
      this.bpm.set(track.bpm);
      this.key.set(track.key);
      this.style.set(track.style);
      this.priceMp3.set(track.price_mp3);
      this.priceWav.set(track.price_wav ?? 0);
      this.priceStems.set(track.price_stems ?? 0);
      this.selectedTagIds.set(track.tags.map(tag => tag.id));
      this.track.set(track);
      this.loading.set(false);
    },
    error: () => {
      this.error.set('Erreur lors du chargement du track.');
      this.loading.set(false);
    }
  });
}
```

`ngOnInit()` est une méthode du cycle de vie Angular. Elle est appelée une seule fois, juste après que le composant a été créé et que ses inputs ont été injectés. C'est l'endroit standard pour lancer les requêtes HTTP d'initialisation.

**Ordre des opérations :**
1. On charge les tags depuis l'API (nécessaire pour les pills de tags)
2. On lit l'ID dans l'URL (`/edit-track/42` → `42`)
3. On vérifie que l'ID est valide — si on arrive là sans ID (navigation directe ou bug), on affiche une erreur et on arrête avec `return`
4. On appelle `getTrackDetail(id)` et on attend la réponse via `.subscribe()`

**Pourquoi `this.route.snapshot.paramMap.get('id')` ?**
`snapshot` est la photo instantanée de la route au moment où le composant s'initialise. On utilise `.get('id')` pour lire le paramètre `:id` défini dans `app.routes.ts`. Il renvoie toujours une `string | null`, d'où le `Number()` pour convertir en nombre.

**Le subscribe et ses deux cas :**
- `next:` est appelé quand la requête HTTP réussit (200). La réponse JSON de Flask a la forme `{ success: true, data: { track: { ... } } }`, d'où `res.data.track`.
- `error:` est appelé si la requête échoue (404, 500, réseau coupé...). On n'a pas les détails dans ce cas simple, mais on informe l'utilisateur.

**Le `?? 0` sur les prix :**
Flask peut retourner `null` pour `price_wav` et `price_stems` si le track n'a pas de WAV ou de stems. L'opérateur `??` ("nullish coalescing") dit : "si la valeur est `null` ou `undefined`, utilise `0` à la place". C'est plus précis que `||` qui traiterait aussi `0` comme falsy.

**Le `map` sur selectedTagIds :**
`track.tags` reçu de l'API est un tableau d'objets : `[{ id: 3, name: 'Trap', category: {...} }, { id: 7, name: 'Dark', ... }]`. Mais notre signal `selectedTagIds` ne stocke que des IDs numériques (`number[]`), parce que c'est tout ce dont Flask a besoin pour sauvegarder les associations tag-track. `.map(tag => tag.id)` transforme ce tableau d'objets en tableau d'IDs : `[3, 7]`. C'est une transformation courante : on reçoit des données riches, on n'en garde que la clé utile.

---

## getImageUrl() : accéder à l'image du track

```typescript
getImageUrl(path: string | null | undefined): string {
  if (!path) return 'assets/placeholder-track.png';
  return this.trackService.getStaticFileUrl(path);
}
```

Flask stocke les images dans `static/images/tracks/`. Le chemin sauvegardé en base est `images/tracks/mon_beat_abc123.png`. Pour afficher cette image dans le navigateur il faut construire l'URL complète : `http://localhost:5000/static/images/tracks/mon_beat_abc123.png`.

Cette construction est déléguée à `trackService.getStaticFileUrl(path)` qui préfixe simplement `environment.apiUrl + '/static/'`. On ne le fait pas dans le composant directement parce que cette logique est aussi utilisée dans `TrackDetailComponent`, `TrackCardComponent`, etc. La centraliser dans le service évite de la dupliquer.

Le `if (!path)` couvre le cas où l'image est `null` ou `undefined` (track sans image, erreur API...). Dans ce cas on affiche un placeholder générique contenu dans les assets Angular — une erreur non critique, l'utilisateur voit quand même la page.

---

## toggleTag() et isTagSelected() : système de checkbox sans `<input type="checkbox">`

```typescript
toggleTag(id: number): void {
  const current = this.selectedTagIds();
  this.selectedTagIds.set(
    current.includes(id) ? current.filter(x => x !== id) : [...current, id]
  );
}

isTagSelected(id: number): boolean {
  return this.selectedTagIds().includes(id);
}
```

Les tags sont affichés comme des "pills" (boutons arrondis cliquables) plutôt que des checkboxes HTML classiques — c'est plus agréable visuellement. Mais le comportement reste celui d'une checkbox : clic = on ajoute, clic à nouveau = on retire.

`toggleTag(id)` lit l'état actuel du signal (`current`), puis :
- Si l'ID est déjà dans le tableau (`current.includes(id)`) → on le **retire** avec `.filter(x => x !== id)` qui retourne un nouveau tableau sans cet ID
- Sinon → on l'**ajoute** avec `[...current, id]` (spread : copie du tableau existant + nouvel élément à la fin)

**Pourquoi ne pas faire `.push()` directement ?**
Un signal Angular ne se met à jour que si on appelle `.set()` avec une nouvelle valeur. Modifier le tableau en place avec `.push()` ne déclencherait pas la réactivité — Angular ne "verrait" pas le changement. On crée donc toujours un nouveau tableau.

`isTagSelected(id)` est utilisée dans le template pour appliquer la classe CSS `selected` sur la pill correspondante. C'est simplement une vérification : est-ce que cet ID est dans notre tableau de sélection ?

---

## onFileSelected() : remplacement optionnel de fichiers

```typescript
onFileSelected(event: Event, field: 'image' | 'wav' | 'stems' | 'mp3'): void {
  const file = (event.target as HTMLInputElement).files?.[0] ?? null;
  if (field === 'image') this.fileImage.set(file);
  if (field === 'wav')   this.fileWav.set(file);
  if (field === 'stems') this.fileStems.set(file);
  if (field === 'mp3')   this.fileMp3.set(file);
}
```

`event` est l'événement déclenché quand l'utilisateur sélectionne un fichier. `event.target` est l'élément `<input type="file">` du DOM. `.files` est la liste des fichiers sélectionnés (toujours un tableau, même si un seul fichier). `[0]` prend le premier. `?.[0]` est une "optional chaining" — si `.files` est `null` ou `undefined`, ça retourne `undefined` au lieu de crasher. `?? null` ramène ça à `null` si rien n'a été sélectionné.

Le paramètre `field` est une union de strings littérales TypeScript (`'image' | 'wav' | 'stems' | 'mp3'`). C'est comme un enum mais plus léger. Il permet d'avoir une seule fonction pour quatre types de fichiers plutôt que `onImageSelected()`, `onWavSelected()`... TypeScript garantit qu'on ne peut pas appeler `onFileSelected(e, 'video')` par erreur — ça ne compilerait pas.

Si l'utilisateur ne sélectionne pas de fichier pour un champ donné, le signal reste à `null`. Dans `onSubmit()`, on envoie `undefined` à la place de `null` pour les fichiers non remplis — ce qui fait que `CudTrackService` ne les ajoute pas au `FormData`, et Flask ne les reçoit pas, donc les fichiers existants sont conservés tels quels.

---

## onSubmit() : construire et envoyer le payload

```typescript
onSubmit(): void {
  this.cudTrackService.putTrack(this.trackId, {
    title:       this.title(),
    bpm:         this.bpm()!,
    key:         this.key(),
    style:       this.style(),
    price_mp3:   this.priceMp3(),
    price_wav:   this.priceWav() ?? 0,
    price_stems: this.priceStems() ?? 0,
    tag_ids:     this.selectedTagIds().join(','),
    file_mp3:    this.fileMp3()  ?? undefined,
    file_image:  this.fileImage() ?? undefined,
    file_wav:    this.fileWav()  ?? undefined,
    file_stems:  this.fileStems() ?? undefined,
  }).subscribe({
    next: res => {
      if (res.success) {
        this.success.set(true);
        setTimeout(() => this.router.navigate(['/track', this.trackId]), 2000);
      } else {
        this.error.set(res.error || 'Erreur inconnue.');
      }
    },
    error: () => {
      this.error.set('Erreur lors de la mise à jour du track.');
    }
  });
}
```

`onSubmit()` est liée au template via `(ngSubmit)="onSubmit()"` sur la balise `<form>`. Elle est déclenchée quand l'utilisateur clique sur le bouton submit.

**`this.bpm()!`** : le `!` est l'opérateur "non-null assertion" de TypeScript. `bpm` est `signal<number | null>` mais Flask attend un `number`. On dit à TypeScript : "je sais qu'ici ce ne sera jamais null" (grâce à la validation du formulaire). En production, on ajouterait une garde explicite.

**`selectedTagIds().join(',')`** : l'inverse du `map` vu dans `ngOnInit`. On avait transformé `[{id:3,...}, {id:7,...}]` en `[3, 7]`. Ici on transforme `[3, 7]` en `"3,7"` — c'est ce que Flask attend en `request.form.get('tag_ids')` pour recréer les associations.

**`?? undefined` sur les fichiers** : les signals de fichiers sont `File | null`. On passe `undefined` plutôt que `null` parce que `CudTrackService` vérifie `if (trackData.file_wav)` — `null` est falsy comme `undefined`, mais certaines APIs TypeScript distinguent les deux. C'est une convention de cohérence.

**Le `setTimeout` après succès** : on laisse 2 secondes à l'utilisateur pour voir le message de confirmation avant de le rediriger vers la page du track. C'est un UX simple mais efficace. `router.navigate(['/track', this.trackId])` construit l'URL `/track/42`.
