import { Injectable } from '@angular/core';
import { PreloadingStrategy, Route } from '@angular/router';
import { Observable, of } from 'rxjs';

/**
 * Précharge les chunks des routes marquées `data: { preload: true }` quand le
 * navigateur est idle après le premier rendu — la navigation vers ces pages
 * devient instantanée sans concurrencer le chargement initial.
 *
 * Seules les routes « chaudes » du parcours principal (home ↔ track-detail)
 * doivent porter le flag : précharger tout annulerait le bénéfice du lazy
 * loading. WebView-safe : fallback setTimeout si requestIdleCallback manque.
 */
@Injectable({ providedIn: 'root' })
export class IdlePreloadStrategy implements PreloadingStrategy {

  preload(route: Route, load: () => Observable<unknown>): Observable<unknown> {
    if (!route.data?.['preload']) return of(null);

    return new Observable(subscriber => {
      const scheduleWhenIdle = 'requestIdleCallback' in window
        ? (cb: () => void) => (window as Window).requestIdleCallback(cb, { timeout: 6000 })
        : (cb: () => void) => setTimeout(cb, 3000);
      scheduleWhenIdle(() => load().subscribe(subscriber));
    });
  }
}
