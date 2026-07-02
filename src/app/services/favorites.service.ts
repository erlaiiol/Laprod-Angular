import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, map, tap, shareReplay } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

export interface ToggleFavoriteData {
  action:      'added' | 'removed';
  is_favorite: boolean;
}

@Injectable({ providedIn: 'root' })
export class FavoritesService {

  private http   = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/api/favorites`;

  private cache     = new Map<number, boolean>();
  /** Observable partagé du batch en cours. check() y souscrit si le cache est vide. */
  private prefetch$ : Observable<void> | null = null;

  /**
   * Lance la requête batch check-batch et stocke l'observable partagé.
   * N'a pas besoin d'être attendu : check() se branche dessus automatiquement.
   */
  prefetch(ids: number[]): Observable<void> {
    if (!ids.length) { this.prefetch$ = null; return of(undefined); }
    this.prefetch$ = this.http.get<{ success: boolean; data: Record<string, boolean> }>(
      `${this.apiUrl}/check-batch?ids=${ids.join(',')}`
    ).pipe(
      tap(res => {
        if (res.success) {
          for (const [k, v] of Object.entries(res.data)) {
            this.cache.set(Number(k), v);
          }
        }
        this.prefetch$ = null;
      }),
      map(() => undefined as void),
      shareReplay(1),
    );
    return this.prefetch$;
  }

  /** Remet le cache à zéro (utile si l'utilisateur se déconnecte). */
  clearCache(): void {
    this.cache.clear();
    this.prefetch$ = null;
  }

  toggle(trackId: number): Observable<ApiResponse<ToggleFavoriteData>> {
    return this.http.post<ApiResponse<ToggleFavoriteData>>(
      `${this.apiUrl}/toggle/${trackId}`, {}
    ).pipe(
      tap(res => {
        if (res.success && res.data) {
          this.cache.set(trackId, res.data.is_favorite);
        }
      })
    );
  }

  check(trackId: number): Observable<{ is_favorite: boolean }> {
    if (this.cache.has(trackId)) {
      return of({ is_favorite: this.cache.get(trackId)! });
    }
    // Un prefetch est en cours : se brancher dessus plutôt que de faire N appels individuels.
    if (this.prefetch$) {
      return this.prefetch$.pipe(
        map(() => ({ is_favorite: this.cache.get(trackId) ?? false }))
      );
    }
    return this.http.get<{ is_favorite: boolean }>(
      `${this.apiUrl}/check/${trackId}`
    ).pipe(
      tap(res => this.cache.set(trackId, res.is_favorite))
    );
  }

  recordListening(trackId: number): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/listening/${trackId}`, {}
    );
  }
}
