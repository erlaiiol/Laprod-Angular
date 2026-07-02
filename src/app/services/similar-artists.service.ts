import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

export interface SimilarArtistEntry { id: number; name: string; scene: string; }
export interface SimilarArtistScene { name: string; artists: SimilarArtistEntry[]; }

@Injectable({ providedIn: 'root' })
export class SimilarArtistsService {
  private http = inject(HttpClient);
  private baseUrl = `${environment.apiUrl}/api/filters`;

  getSimilarArtists(): Observable<{ success: boolean; data: { scenes: SimilarArtistScene[] } }> {
    return this.http.get<any>(`${this.baseUrl}/similar-artists`);
  }
}
