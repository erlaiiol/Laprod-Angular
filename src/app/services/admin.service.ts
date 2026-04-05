import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

// ── Interfaces ────────────────────────────────────────────────────────────────

export interface AdminStats {
  tracks:    { pending: number; approved: number; total: number };
  users:     { total: number; premium: number; beatmakers: number; artists: number; engineers: number };
  contracts: { total: number; exclusive: number; revenue: number };
  mixmaster: { in_progress: number; completed: number; revenue: number };
  recent_tracks: AdminTrackSummary[];
  recent_users:  AdminUserSummary[];
}

export interface AdminTrackSummary {
  id:          number;
  title:       string;
  image_file:  string;
  approved_at: string | null;
  composer:    { username: string } | null;
}

export interface AdminUserSummary {
  id:            number;
  username:      string;
  profile_image: string;
  created_at:    string | null;
}

export interface AdminTrack {
  id:             number;
  title:          string;
  bpm:            number;
  key:            string;
  style:          string | null;
  image_file:     string;
  stream_url:     string;
  price_mp3:      number | null;
  price_wav:      number | null;
  price_stems:    number | null;
  is_approved:    boolean;
  purchase_count: number;
  created_at:     string | null;
  approved_at:    string | null;
  composer:       { id: number; username: string; profile_image: string } | null;
  tags:           { id: number; name: string; category: string | null }[];
}

export interface AdminUser {
  id:              number;
  username:        string;
  email:           string;
  profile_image:   string;
  account_status:  string;
  is_admin:        boolean;
  is_beatmaker:    boolean;
  is_artist:       boolean;
  is_mix_engineer: boolean;
  is_mixmaster_engineer: boolean;
  is_certified_producer_arranger: boolean;
  producer_arranger_request_submitted: boolean;
  is_premium:      boolean;
  upload_track_tokens: number;
  topline_tokens:  number;
  created_at:      string | null;
  tracks_count:    number;
  contracts_count: number;
  mm_count:        number;
}



export interface PriceRequest {
  id:                      number;
  engineer_id:             number;
  engineer_username:       string | null;
  current_reference_price: number | null;
  current_price_min:       number | null;
  new_reference_price:     number;
  new_price_min:           number;
  created_at:              string | null;
}

export interface AdminContract {
  id:           number;
  price:        number;
  is_exclusive: boolean;
  format:       string | null;
  created_at:   string | null;
  track:   { id: number; title: string } | null;
  client:  { id: number; username: string } | null;
  composer: { id: number; username: string } | null;
}

export interface AdminTransaction {
  id:           number;
  status:       string;
  total_price:  number;
  created_at:   string | null;
  completed_at: string | null;
  artist:   { id: number; username: string } | null;
  engineer: { id: number; username: string } | null;
}

export interface AdminCategory {
  id:    number;
  name:  string;
  color: string;
  tags:  { id: number; name: string }[];
}

export interface AdminMixEngineer {
  id:              number;
  username:        string;
  email:           string;
  profile_image:   string;
  is_mixmaster_engineer: boolean;
  is_certified_producer_arranger: boolean;
  mixmaster_reference_price: number | null;
  mixmaster_price_min:       number | null;
  mixmaster_bio:             string | null;
  mixmaster_sample_raw:      string | null;
  mixmaster_sample_processed: string | null;
}

export interface UserSearchResult {
  id:       number;
  username: string;
  email:    string;
}

export interface TrackSearchResult {
  id:                 number;
  title:              string;
  composer_username:  string | null;
  composer_id:        number | null;
  price_mp3:          number | null;
  price_wav:          number | null;
  price_stems:        number | null;
}

export type ApiFeedback = { level: 'info' | 'warning' | 'error'; message: string };

type ApiResponse<T = void> = {
  success: boolean;
  feedback: ApiFeedback;
  data?: T;
};

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class AdminService {

  private base = `${environment.apiUrl.replace('/api', '')}/admin-api`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  // ── GET ────────────────────────────────────────────────────────────────────

  getStats(): Observable<ApiResponse<AdminStats>> {
    return this.http.get<any>(`${this.base}/stats`, { headers: this.headers });
  }

  getTracks(status: 'pending' | 'approved' | 'all' = 'pending'): Observable<ApiResponse<{ tracks: AdminTrack[]; pending_count: number; approved_count: number }>> {
    return this.http.get<any>(`${this.base}/tracks`, { headers: this.headers, params: { status } });
  }

  getUsers(userType: 'all' | 'beatmakers' | 'artists' | 'engineers' = 'all'): Observable<ApiResponse<{ users: AdminUser[]; counts: Record<string, number> }>> {
    return this.http.get<any>(`${this.base}/users`, { headers: this.headers, params: { user_type: userType } });
  }

  getEngineers(): Observable<ApiResponse<{ certified: AdminMixEngineer[]; pending: AdminMixEngineer[]; pa_requests: AdminMixEngineer[]; price_requests: PriceRequest[] }>> {
    return this.http.get<any>(`${this.base}/engineers`, { headers: this.headers });
  }

  getContracts(): Observable<ApiResponse<{ contracts: AdminContract[]; exclusive_count: number; non_exclusive_count: number; total_revenue: number }>> {
    return this.http.get<any>(`${this.base}/contracts`, { headers: this.headers });
  }

  getTransactions(status: 'all' | 'awaiting' | 'in_progress' | 'completed' = 'all'): Observable<ApiResponse<{ transactions: AdminTransaction[]; counts: Record<string, number>; total_revenue: number }>> {
    return this.http.get<any>(`${this.base}/transactions`, { headers: this.headers, params: { status } });
  }

  getCategories(): Observable<ApiResponse<{ categories: AdminCategory[] }>> {
    return this.http.get<any>(`${this.base}/categories`, { headers: this.headers });
  }

  // ── Tracks CUD ─────────────────────────────────────────────────────────────

  approveTrack(trackId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/tracks/${trackId}/approve`, {}, { headers: this.headers });
  }

  rejectTrack(trackId: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.base}/tracks/${trackId}`, { headers: this.headers });
  }

  editTrack(trackId: number, data: Partial<AdminTrack>): Observable<ApiResponse> {
    return this.http.put<any>(`${this.base}/tracks/${trackId}`, data, { headers: this.headers });
  }

  // ── Users CUD ──────────────────────────────────────────────────────────────

  toggleUserStatus(userId: number): Observable<ApiResponse<{ account_status: string }>> {
    return this.http.post<any>(`${this.base}/users/${userId}/toggle-status`, {}, { headers: this.headers });
  }

  toggleUserRole(userId: number, role: string): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/users/${userId}/toggle-role/${role}`, {}, { headers: this.headers });
  }

  addTrackTokens(userId: number, tokens: number): Observable<ApiResponse<{ upload_track_tokens: number }>> {
    return this.http.post<any>(`${this.base}/users/${userId}/add-track-tokens`, { tokens }, { headers: this.headers });
  }

  addToplineTokens(userId: number, tokens: number): Observable<ApiResponse<{ topline_tokens: number }>> {
    return this.http.post<any>(`${this.base}/users/${userId}/add-topline-tokens`, { tokens }, { headers: this.headers });
  }

  togglePremium(userId: number): Observable<ApiResponse<{ is_premium: boolean }>> {
    return this.http.post<any>(`${this.base}/users/${userId}/toggle-premium`, {}, { headers: this.headers });
  }

  // ── Engineers CUD ──────────────────────────────────────────────────────────

  certifyEngineer(userId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/engineers/${userId}/certify`, {}, { headers: this.headers });
  }

  revokeEngineer(userId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/engineers/${userId}/revoke`, {}, { headers: this.headers });
  }

  rejectEngineerSample(userId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/engineers/${userId}/reject-sample`, {}, { headers: this.headers });
  }

  updateEngineerPrices(userId: number, priceMin: number, referencePrice: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/engineers/${userId}/update-prices`, { price_min: priceMin, reference_price: referencePrice }, { headers: this.headers });
  }

  approvePriceRequest(requestId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/price-requests/${requestId}/approve`, {}, { headers: this.headers });
  }

  rejectPriceRequest(requestId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/price-requests/${requestId}/reject`, {}, { headers: this.headers });
  }

  approveProducerArranger(userId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/producer-arranger/${userId}/approve`, {}, { headers: this.headers });
  }

  revokeProducerArranger(userId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/producer-arranger/${userId}/revoke`, {}, { headers: this.headers });
  }

  rejectProducerArranger(userId: number): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/producer-arranger/${userId}/reject`, {}, { headers: this.headers });
  }

  // ── Engineer direct certification ──────────────────────────────────────────

  getAllMixEngineers(): Observable<ApiResponse<{ engineers: AdminMixEngineer[] }>> {
    return this.http.get<any>(`${this.base}/engineers/all-mix`, { headers: this.headers });
  }

  uploadEngineerSample(userId: number, fd: FormData): Observable<ApiResponse<{ sample_raw: string; sample_processed: string }>> {
    return this.http.post<any>(`${this.base}/engineers/${userId}/upload-sample`, fd, { headers: this.headers });
  }

  setEngineerInfo(userId: number, data: { reference_price?: number; price_min?: number; bio?: string }): Observable<ApiResponse> {
    return this.http.post<any>(`${this.base}/engineers/${userId}/set-info`, data, { headers: this.headers });
  }

  // ── Search ─────────────────────────────────────────────────────────────────

  searchUsers(q: string): Observable<ApiResponse<{ users: UserSearchResult[] }>> {
    return this.http.get<any>(`${this.base}/users/search`, { headers: this.headers, params: { q } });
  }

  searchTracks(q: string): Observable<ApiResponse<{ tracks: TrackSearchResult[] }>> {
    return this.http.get<any>(`${this.base}/tracks/search`, { headers: this.headers, params: { q } });
  }

  // ── Manual contract ────────────────────────────────────────────────────────

  createContract(payload: {
    track_id: number;
    client_id: number;
    price: number;
    is_exclusive: boolean;
    territory: string;
    duration: string;
  }): Observable<ApiResponse<{ contract_id: number }>> {
    return this.http.post<any>(`${this.base}/contracts/create`, payload, { headers: this.headers });
  }

  // ── Categories & Tags CUD ──────────────────────────────────────────────────

  createCategory(name: string, color: string): Observable<ApiResponse<{ category: AdminCategory }>> {
    return this.http.post<any>(`${this.base}/categories`, { name, color }, { headers: this.headers });
  }

  editCategory(catId: number, name: string, color: string): Observable<ApiResponse> {
    return this.http.put<any>(`${this.base}/categories/${catId}`, { name, color }, { headers: this.headers });
  }

  deleteCategory(catId: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.base}/categories/${catId}`, { headers: this.headers });
  }

  createTag(name: string, categoryId: number): Observable<ApiResponse<{ tag: { id: number; name: string } }>> {
    return this.http.post<any>(`${this.base}/tags`, { name, category_id: categoryId }, { headers: this.headers });
  }

  editTag(tagId: number, name: string, categoryId?: number): Observable<ApiResponse> {
    return this.http.put<any>(`${this.base}/tags/${tagId}`, { name, category_id: categoryId }, { headers: this.headers });
  }

  deleteTag(tagId: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.base}/tags/${tagId}`, { headers: this.headers });
  }
}
