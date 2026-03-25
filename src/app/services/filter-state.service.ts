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
  search:  string;
  bpmMin:  number | null;
  bpmMax:  number | null;
  keys:    string[];   // ex : ['Am', 'Gm']
  styles:  string[];   // ex : ['Trap', 'Drill']
  tags:    string[];   // ex : ['dark', 'melodic']
}

const EMPTY_FILTERS: ActiveFilters = {
  search: '',
  bpmMin: null,
  bpmMax: null,
  keys:   [],
  styles: [],
  tags:   [],
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


  // ── Méthodes ──────────────────────────────────────────────────────────────

  apply(filters: ActiveFilters): void {
    this.filters.set(filters);
    this.applied.update(n => n + 1);
    // signal.update(fn) : lit la valeur actuelle, applique fn, écrit le résultat.
  }

  reset(): void {
    this.filters.set({ ...EMPTY_FILTERS });
    this.applied.update(n => n + 1);
  }
}
