import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, shareReplay, tap } from 'rxjs';
import { environment } from '../../environments/environment';

export interface SimilarArtistEntry { id: number; name: string; scene: string; }
export interface SimilarArtistScene { name: string; artists: SimilarArtistEntry[]; }

export interface SimilarArtistsResponse {
  success: boolean;
  data: { scenes: SimilarArtistScene[] };
}

@Injectable({ providedIn: 'root' })
export class SimilarArtistsService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiUrl}/api/filters`;

  // Le service est propriétaire de l'état : les composants lisent ce signal
  // au lieu de garder chacun leur copie de la réponse.
  private _scenes = signal<SimilarArtistScene[]>([]);
  readonly scenes = this._scenes.asReadonly();

  // Données quasi statiques : requête partagée + TTL, même pattern que TagsService.
  private cache$: Observable<SimilarArtistsResponse> | null = null;
  private fetchedAt = 0;
  private static readonly TTL_MS = 5 * 60_000;

  ensureLoaded(): Observable<SimilarArtistsResponse> {
    if (!this.cache$ || Date.now() - this.fetchedAt > SimilarArtistsService.TTL_MS) {
      this.fetchedAt = Date.now();
      this.cache$ = this.http.get<SimilarArtistsResponse>(`${this.baseUrl}/similar-artists`).pipe(
        tap({
          next: res => {
            if (res.success) this._scenes.set(res.data.scenes);
          },
          error: () => { this.cache$ = null; },
        }),
        shareReplay({ bufferSize: 1, refCount: false }),
      );
    }
    return this.cache$;
  }

  invalidate(): void {
    this.cache$ = null;
  }

  /** @deprecated Alias de compatibilité — préférer ensureLoaded(). */
  getSimilarArtists(): Observable<SimilarArtistsResponse> {
    return this.ensureLoaded();
  }
}
