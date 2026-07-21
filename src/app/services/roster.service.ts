import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

// ── Types ─────────────────────────────────────────────────────────────────────

export type RosterLinkStatus = 'invited' | 'active' | 'declined' | 'revoked' | 'ended';

export interface RosterLinkDTO {
  id:                       number;
  status:                   RosterLinkStatus;
  /** Rôle du user connecté dans CE lien : 'producer' ou 'artist'. */
  role:                     'producer' | 'artist';
  /** L'autre partie du lien, vue depuis l'utilisateur connecté. */
  counterpart:              { id: number; username: string; profile_image: string | null };
  invited_by:               { id: number; username: string; profile_image: string | null };
  created_at:                string;
  responded_at:              string | null;
  ended_at:                  string | null;
  has_management_contract:   boolean;
}

export interface RosterSearchResult {
  id:              number;
  username:        string;
  already_linked:  boolean;
}

type ApiResponse<T = unknown> = {
  success:  boolean;
  feedback?: { level: string; message: string };
  data?:    T;
};

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class RosterService {

  private base = `${environment.apiUrl}/api/roster`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  invite(identifier: string): Observable<ApiResponse<{ link: RosterLinkDTO }>> {
    return this.http.post<any>(`${this.base}/invite`, { identifier }, { headers: this.headers });
  }

  mine(): Observable<ApiResponse<{ as_producer: RosterLinkDTO[]; as_artist: RosterLinkDTO[] }>> {
    return this.http.get<any>(`${this.base}/mine`, { headers: this.headers });
  }

  accept(linkId: number): Observable<ApiResponse<{ link: RosterLinkDTO }>> {
    return this.http.post<any>(`${this.base}/${linkId}/accept`, {}, { headers: this.headers });
  }

  decline(linkId: number): Observable<ApiResponse<{ link: RosterLinkDTO }>> {
    return this.http.post<any>(`${this.base}/${linkId}/decline`, {}, { headers: this.headers });
  }

  revoke(linkId: number): Observable<ApiResponse<{ link: RosterLinkDTO }>> {
    return this.http.post<any>(`${this.base}/${linkId}/revoke`, {}, { headers: this.headers });
  }

  searchArtist(q: string): Observable<ApiResponse<{ users: RosterSearchResult[] }>> {
    return this.http.get<any>(`${this.base}/search-artist`, { headers: this.headers, params: { q } });
  }

  attachContract(linkId: number, contractId: number): Observable<ApiResponse<{ link: RosterLinkDTO }>> {
    return this.http.post<any>(`${this.base}/${linkId}/attach-contract`, { contract_id: contractId }, { headers: this.headers });
  }
}
