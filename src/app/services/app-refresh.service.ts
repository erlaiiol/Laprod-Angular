import { Injectable } from '@angular/core';
import { fromEvent, interval, merge, Observable } from 'rxjs';
import { debounceTime, filter, map, share } from 'rxjs';

// Intervalle entre deux rafraîchissements automatiques (quand l'onglet est visible)
const SOFT_INTERVAL_MS = 90_000;

// Durée minimale d'absence avant de considérer un focus/restore comme significatif.
// Évite le double-fire lors d'un alt-tab rapide ou d'un clic sur un autre onglet pendant < 30s.
const FOCUS_COOLDOWN_MS = 30_000;

/**
 * Service racine qui expose un Observable `soft$` représentant les moments
 * appropriés pour rafraîchir des données légères (notifications, stats dashboard).
 *
 * Émet dans trois cas :
 *   - L'onglet redevient visible après avoir été caché ≥ 30s
 *   - La fenêtre reprend le focus après une absence ≥ 30s
 *   - Un timer de 90s s'écoule, onglet visible uniquement
 *
 * Un seul Observable partagé (share) — N consommateurs = 1 seul timer actif.
 */
@Injectable({ providedIn: 'root' })
export class AppRefreshService {

  readonly soft$: Observable<void>;

  constructor() {
    let lastHiddenAt = 0;

    // Enregistre l'instant où l'onglet passe en arrière-plan
    fromEvent(document, 'visibilitychange').pipe(
      filter(() => document.hidden),
    ).subscribe(() => { lastHiddenAt = Date.now(); });

    // L'onglet redevient visible après une absence longue
    const visibilityRestore$ = fromEvent(document, 'visibilitychange').pipe(
      filter(() => !document.hidden && Date.now() - lastHiddenAt > FOCUS_COOLDOWN_MS),
    );

    // La fenêtre reprend le focus (retour d'une autre app ou d'un autre onglet)
    const focus$ = fromEvent(window, 'focus').pipe(
      filter(() => Date.now() - lastHiddenAt > FOCUS_COOLDOWN_MS),
    );

    // Timer périodique, silencieux quand l'onglet est caché
    const tick$ = interval(SOFT_INTERVAL_MS).pipe(
      filter(() => !document.hidden),
    );

    this.soft$ = merge(visibilityRestore$, focus$, tick$).pipe(
      debounceTime(500),   // déduplique les events simultanés (ex: focus + visibilitychange)
      map(() => void 0),
      share(),             // un seul interval partagé, pas N
    );
  }
}
