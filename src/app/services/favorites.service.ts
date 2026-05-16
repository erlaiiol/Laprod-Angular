import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of, map, tap } from 'rxjs';
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

  /** Cache peuplé par prefetch() avant le rendu des track-cards. */
  private cache = new Map<number, boolean>();

  /**
   * Charge les statuts favoris pour une liste d'IDs en une seule requête.
   * Doit être appelé avant que les FavoriteButtonComponent se rendent.
   */
  prefetch(ids: number[]): Observable<void> {
    if (!ids.length) return of(undefined);
    return this.http.get<{ success: boolean; data: Record<string, boolean> }>(
      `${this.apiUrl}/check-batch?ids=${ids.join(',')}`
    ).pipe(
      tap(res => {
        if (res.success) {
          for (const [k, v] of Object.entries(res.data)) {
            this.cache.set(Number(k), v);
          }
        }
      }),
      map(() => undefined)
    );
  }

  /** Remet le cache à zéro (utile si l'utilisateur se déconnecte). */
  clearCache(): void {
    this.cache.clear();
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
