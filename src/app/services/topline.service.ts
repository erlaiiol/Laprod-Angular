import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PublishedTopline } from './track.service';

// ── Format JSON unifié ────────────────────────────────────────────────────────

export interface ApiFeedback {
  level:   'info' | 'warning' | 'error';
  message: string;
}

/** Enveloppe générique pour toutes les réponses CUD de l'API. */
export interface ApiResponse<T = void> {
  success:   boolean;
  feedback?: ApiFeedback;
  data?:     T;
  /** Code optionnel pour que le front distingue les cas (ex. QUOTA_EXCEEDED). */
  code?:     string;
}

// ── Types spécifiques topline ─────────────────────────────────────────────────

export interface UploadToplineData {
  topline:          PublishedTopline;
  tokens_remaining: number;
}

export interface PublishToplineData {
  topline: PublishedTopline;
}

export interface DeleteToplineData {
  track_id: number;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class ToplineService {

  private http    = inject(HttpClient);
  private apiUrl  = `${environment.apiUrl}/toplines`;

  getTrackToplines(trackId: number): Observable<ApiResponse<{ toplines: PublishedTopline[] }>> {
    return this.http.get<ApiResponse<{ toplines: PublishedTopline[] }>>(
      `${this.apiUrl}/track/${trackId}`
    );
  }

  getMyToplines(trackId: number): Observable<ApiResponse<{ toplines: PublishedTopline[] }>> {
    return this.http.get<ApiResponse<{ toplines: PublishedTopline[] }>>(
      `${this.apiUrl}/my/${trackId}`
    );
  }

  uploadTopline(formData: FormData): Observable<ApiResponse<UploadToplineData>> {
    return this.http.post<ApiResponse<UploadToplineData>>(
      `${this.apiUrl}/upload`, formData
    );
  }

  publishTopline(id: number): Observable<ApiResponse<PublishToplineData>> {
    return this.http.post<ApiResponse<PublishToplineData>>(
      `${this.apiUrl}/${id}/publish`, {}
    );
  }

  deleteTopline(id: number): Observable<ApiResponse<DeleteToplineData>> {
    return this.http.delete<ApiResponse<DeleteToplineData>>(
      `${this.apiUrl}/${id}`
    );
  }
}
