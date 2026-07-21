import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

// ── Types ─────────────────────────────────────────────────────────────────────

export type TrackSplitRole = 'topliner' | 'beatmaker' | 'mix_engineer' | 'label' | 'producer' | 'other';
export type TrackSplitStatus = 'declared' | 'confirmed';

export const TRACK_SPLIT_ROLE_LABELS: Record<TrackSplitRole, string> = {
  topliner:     'Topliner',
  beatmaker:    'Beatmaker',
  mix_engineer: 'Ingénieur mix/master',
  label:        'Label',
  producer:     'Producteur',
  other:        'Autre',
};

export interface TrackSplitDTO {
  id:            number;
  track_id:      number;
  user:          { id: number; username: string; profile_image: string | null } | null;
  external_name: string;
  role:          TrackSplitRole;
  percentage:    number;
  status:        TrackSplitStatus;
  added_by:      { id: number; username: string; profile_image: string | null } | null;
  created_at:    string;
  updated_at:    string | null;
}

export interface AddTrackSplitPayload {
  role:           TrackSplitRole;
  percentage:     number;
  external_name?: string;
  user_id?:       number;
}

type ApiResponse<T = unknown> = {
  success:  boolean;
  feedback?: { level: string; message: string };
  data?:    T;
};

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class RoyaltiesService {

  private base = `${environment.apiUrl}/api/royalties`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  list(trackId: number): Observable<ApiResponse<{ splits: TrackSplitDTO[]; total_percentage: number; can_manage: boolean }>> {
    return this.http.get<any>(`${this.base}/tracks/${trackId}/splits`, { headers: this.headers });
  }

  add(trackId: number, payload: AddTrackSplitPayload): Observable<ApiResponse<{ split: TrackSplitDTO }>> {
    return this.http.post<any>(`${this.base}/tracks/${trackId}/splits`, payload, { headers: this.headers });
  }

  update(splitId: number, payload: Partial<AddTrackSplitPayload>): Observable<ApiResponse<{ split: TrackSplitDTO }>> {
    return this.http.put<any>(`${this.base}/splits/${splitId}`, payload, { headers: this.headers });
  }

  confirm(splitId: number): Observable<ApiResponse<{ split: TrackSplitDTO }>> {
    return this.http.post<any>(`${this.base}/splits/${splitId}/confirm`, {}, { headers: this.headers });
  }

  remove(splitId: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.base}/splits/${splitId}`, { headers: this.headers });
  }

  /** Relevé PDF de la cap-table — même règle d'accès que list() (lecture libre
   *  pour toute partie prenante légitime, pas de garde Premium). */
  downloadPdf(trackId: number): Observable<Blob> {
    return this.http.get(`${this.base}/tracks/${trackId}/splits/pdf`, {
      headers: this.headers,
      responseType: 'blob',
    });
  }
}
