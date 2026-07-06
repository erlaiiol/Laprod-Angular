// ─────────────────────────────────────────────────────────────────────────────
// SERVICE PARTAGÉ : FilterStateService
//
// Problème : Navbar et HomeComponent sont des composants "frères" —
// ils sont rendus côte à côte dans app.html, pas l'un dans l'autre.
// @Output() ne fonctionne qu'entre parent et enfant direct.
//
// Solution Angular : un service singleton injecté dans les deux.
// La navbar ÉCRIT les filtres → Home les LIT et recharge les tracks.
//
//    app.html
//      ├── <app-navbar>      ← injecte FilterStateService, écrit
//      └── <router-outlet>
//            └── HomeComponent  ← injecte FilterStateService, lit
//
// ─────────────────────────────────────────────────────────────────────────────

import { Injectable, signal } from '@angular/core';


// Représente l'état complet des filtres sélectionnés dans le popover.
// Correspond aux champs que Flask attend dans get_tracks() (tracks_api.py).
export interface ActiveFilters {
  search:         string;
  bpmMin:         number | null;
  bpmMax:         number | null;
  keys:           string[];   // ex : ['Am', 'Gm']
  styles:         string[];   // ex : ['Trap', 'Drill']
  tags:           string[];   // ex : ['dark', 'melodic']
  similarArtists: string[];   // ex : ['Drake', 'Travis Scott']
}

const EMPTY_FILTERS: ActiveFilters = {
  search:         '',
  bpmMin:         null,
  bpmMax:         null,
  keys:           [],
  styles:         [],
  tags:           [],
  similarArtists: [],
};


@Injectable({ providedIn: 'root' })
export class FilterStateService {

  // ── Filtres actifs (écrits par Navbar, lus par Home) ──────────────────────

  readonly filters = signal<ActiveFilters>({ ...EMPTY_FILTERS });

  // ── Compteur d'application ────────────────────────────────────────────────
  // À chaque "Appliquer" ou "Réinitialiser", ce compteur s'incrémente.
  // HomeComponent l'observe via effect() : quand il change → rechargement.
  //
  // Pourquoi un compteur et pas juste "filters" ?
  // Un signal ne se déclenche que si la valeur CHANGE.
  // Si l'utilisateur clique "Appliquer" deux fois avec les mêmes filtres,
  // le compteur change toujours → Home recharge quand même (comportement voulu).

  readonly applied = signal(0);

  // ── Page active ───────────────────────────────────────────────────────────
  // Persistée pour que le retour depuis track-detail retrouve la bonne page.
  // Remise à 1 automatiquement quand des filtres sont appliqués/réinitialisés.

  readonly savedPage = signal(1);


  // ── Méthodes ──────────────────────────────────────────────────────────────

  apply(filters: ActiveFilters): void {
    this.filters.set(filters);
    this.savedPage.set(1);
    this.applied.update(n => n + 1);
  }

  reset(): void {
    this.filters.set({ ...EMPTY_FILTERS });
    this.savedPage.set(1);
    this.applied.update(n => n + 1);
  }

  // Ajoute un tag à la sélection sans effacer les autres filtres.
  // Retourne false si le tag était déjà présent (pas de doublon, pas de rechargement).
  addTag(tag: string): boolean {
    const f = this.filters();
    if (f.tags.includes(tag)) return false;
    this.apply({ ...f, tags: [...f.tags, tag] });
    return true;
  }

  addStyle(style: string): boolean {
    const f = this.filters();
    if (f.styles.includes(style)) return false;
    this.apply({ ...f, styles: [...f.styles, style] });
    return true;
  }

  addSimilarArtist(name: string): boolean {
    const f = this.filters();
    if (f.similarArtists.includes(name)) return false;
    this.apply({ ...f, similarArtists: [...f.similarArtists, name] });
    return true;
  }
}
