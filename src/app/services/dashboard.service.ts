import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

// ── Beatmaker ──────────────────────────────────────────────────────────────────

export interface BeatmakerStats {
  total_revenue:   number;
  sales_count:     number;
  tracks_count:    number;
  tracks_approved: number;
  tracks_pending:  number;
  upload_tokens:   number;
}

export interface BeatmakerTrack {
  id:          number;
  title:       string;
  image_file:  string | null;
  is_approved: boolean;
  created_at:  string;
  bpm:         number | null;
  key:         string | null;
  style:       string | null;
  price_mp3:   number | null;
  price_wav:   number | null;
  price_stems: number | null;
  has_mp3:     boolean;
  has_wav:     boolean;
  has_stems:   boolean;
  sales_count: number;
  stream_url:  string;
}

export interface SaleRecord {
  id:               number;
  track_id:         number;
  track_title:      string | null;
  track_image:      string | null;
  buyer_name:       string;
  format:           string;
  price_paid:       number;
  track_price:      number;
  contract_price:   number;
  platform_fee:     number;
  composer_revenue: number;
  created_at:       string;
}

export interface BeatmakerDashboard {
  stats:  BeatmakerStats;
  tracks: BeatmakerTrack[];
  sales:  SaleRecord[];
}

// ── Artiste ────────────────────────────────────────────────────────────────────

export interface ArtistStats {
  toplines_count:     number;
  toplines_published: number;
  favorites_count:    number;
  topline_tokens:     number;
}

export interface ArtistTopline {
  id:           number;
  track_id:     number;
  track_title:  string | null;
  track_image:  string | null;
  description:  string | null;
  is_published: boolean;
  created_at:   string;
  stream_url:   string;
}

export interface ArtistFavorite {
  id:           number;
  title:        string | null;
  image_file:   string | null;
  composer:     string | null;
  stream_url:   string;
  favorited_at: string;
}

export interface ArtistHistoryItem {
  id:          number;
  title:       string | null;
  image_file:  string | null;
  composer:    string | null;
  stream_url:  string;
  listened_at: string;
}

export interface ArtistDashboard {
  stats:     ArtistStats;
  toplines:  ArtistTopline[];
  favorites: ArtistFavorite[];
  history:   ArtistHistoryItem[];
}

// ── Mix Engineer ───────────────────────────────────────────────────────────────

export interface MixEngineerStats {
  total_revenue:   number;
  completed_count: number;
  active_count:    number;
  pending_count:   number;
  reference_price: number | null;
  price_min:       number | null;
}

export interface MixOrder {
  id:               number;
  title:            string;
  artist_username:  string | null;
  artist_image:     string | null;
  status:           string;
  total_price:      number;
  deposit_amount:   number;
  engineer_revenue: number | null;
  services: {
    cleaning:  boolean;
    effects:   boolean;
    artistic:  boolean;
    mastering: boolean;
  };
  created_at:   string;
  accepted_at:  string | null;
  deadline:     string | null;
  delivered_at: string | null;
  completed_at: string | null;
}

export interface MixEngineerOrders {
  awaiting:  MixOrder[];
  active:    MixOrder[];
  revisions: MixOrder[];
  completed: MixOrder[];
  refused:   MixOrder[];
}

export interface MixEngineerDashboard {
  stats:  MixEngineerStats;
  orders: MixEngineerOrders;
}

// ── Service ────────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class DashboardService {

  private http         = inject(HttpClient);
  private dashboardUrl = `${environment.apiUrl}/dashboard`;

  getBeatmakerDashboard(): Observable<ApiResponse<BeatmakerDashboard>> {
    return this.http.get<ApiResponse<BeatmakerDashboard>>(`${this.dashboardUrl}/beatmaker`);
  }

  getArtistDashboard(): Observable<ApiResponse<ArtistDashboard>> {
    return this.http.get<ApiResponse<ArtistDashboard>>(`${this.dashboardUrl}/artist`);
  }

  getMixEngineerDashboard(): Observable<ApiResponse<MixEngineerDashboard>> {
    return this.http.get<ApiResponse<MixEngineerDashboard>>(`${this.dashboardUrl}/mix-engineer`);
  }
}
