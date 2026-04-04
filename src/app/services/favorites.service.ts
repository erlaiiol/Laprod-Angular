import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

export interface ToggleFavoriteData {
  action:      'added' | 'removed';
  is_favorite: boolean;
}

@Injectable({ providedIn: 'root' })
export class FavoritesService {

  private http   = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/favorites-api`;

  toggle(trackId: number): Observable<ApiResponse<ToggleFavoriteData>> {
    return this.http.post<ApiResponse<ToggleFavoriteData>>(
      `${this.apiUrl}/toggle/${trackId}`, {}
    );
  }

  check(trackId: number): Observable<{ is_favorite: boolean }> {
    return this.http.get<{ is_favorite: boolean }>(
      `${this.apiUrl}/check/${trackId}`
    );
  }

  recordListening(trackId: number): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/listening/${trackId}`, {}
    );
  }
}
