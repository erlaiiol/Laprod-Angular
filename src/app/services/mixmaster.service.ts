import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

// ── Interfaces ────────────────────────────────────────────────────────────────

export interface MixEngineerPublic {
  id:                           number;
  username:                     string;
  profile_image:                string | null;
  mixmaster_bio:                string | null;
  mixmaster_reference_price:    number;
  mixmaster_price_min:          number;
  is_certified_producer_arranger: boolean;
  sample_raw_url:               string | null;
  sample_processed_url:         string | null;
  slots_available:              number | null;
  slots_used:                   number | null;
}

export interface MixOrderFull {
  id:                    number;
  title:                 string;
  artist_username:       string | null;
  artist_image:          string | null;
  engineer_username:     string | null;
  engineer_image:        string | null;
  engineer_id:           number | null;
  status:                string;
  stripe_payment_status: string | null;
  total_price:           number;
  deposit_amount:        number;
  remaining_amount:      number;
  engineer_revenue:      number | null;
  revision_count:        number;
  revision1_message:     string | null;
  revision2_message:     string | null;
  can_request_revision:  boolean;
  is_expired:            boolean;
  final_transfer_amount: number | null;
  services: {
    cleaning:  boolean;
    effects:   boolean;
    artistic:  boolean;
    mastering: boolean;
  };
  has_separated_stems:              boolean;
  artist_message:                   string | null;
  brief_vocals:                     string | null;
  brief_backing_vocals:             string | null;
  brief_ambiance:                   string | null;
  brief_bass:                       string | null;
  brief_energy_style:               string | null;
  brief_references:                 string | null;
  brief_instruments:                string | null;
  brief_percussion:                 string | null;
  brief_effects:                    string | null;
  brief_structure:                  string | null;
  reference_file_url:               string | null;
  original_file_url:                string | null;
  processed_file_preview_url:       string | null;
  processed_file_preview_full_url:  string | null;
  archive_file_tree:                string[];
  created_at:   string;
  accepted_at:  string | null;
  deadline:     string | null;
  delivered_at: string | null;
  completed_at: string | null;
}

export interface CheckoutData {
  checkout_url: string;
}

export interface OrderIdData {
  order_id: number;
}

export interface DownloadData {
  download_url: string;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class MixmasterService {

  private http   = inject(HttpClient);
  private apiUrl = environment.apiUrl;

  // ── Public GET ─────────────────────────────────────────────────────────────

  getEngineers(): Observable<ApiResponse<{ engineers: MixEngineerPublic[] }>> {
    return this.http.get<ApiResponse<{ engineers: MixEngineerPublic[] }>>(
      `${this.apiUrl}/mixmaster-api/engineers`
    );
  }

  getEngineer(id: number): Observable<ApiResponse<{ engineer: MixEngineerPublic }>> {
    return this.http.get<ApiResponse<{ engineer: MixEngineerPublic }>>(
      `${this.apiUrl}/mixmaster-api/engineers/${id}`
    );
  }

  // ── Artist actions ─────────────────────────────────────────────────────────

  /**
   * Crée une session Stripe Checkout et retourne l'URL.
   * formData doit contenir: stems_file, reference_file (opt), title, services,
   * briefing fields, success_url, cancel_url.
   */
  createOrder(engineerId: number, formData: FormData): Observable<ApiResponse<CheckoutData>> {
    return this.http.post<ApiResponse<CheckoutData>>(
      `${this.apiUrl}/mixmaster-artist/order/${engineerId}`, formData
    );
  }

  cancelOrder(orderId: number): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/mixmaster-artist/cancel/${orderId}`, {}
    );
  }

  requestRevision(orderId: number, message: string): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/mixmaster-artist/revision/${orderId}`, { revision_message: message }
    );
  }

  approveOrder(orderId: number): Observable<ApiResponse<DownloadData>> {
    return this.http.post<ApiResponse<DownloadData>>(
      `${this.apiUrl}/mixmaster-artist/approve/${orderId}`, {}
    );
  }

  // ── Engineer actions ───────────────────────────────────────────────────────

  acceptOrder(orderId: number): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/mixmaster-engineer/accept/${orderId}`, {}
    );
  }

  rejectOrder(orderId: number): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/mixmaster-engineer/reject/${orderId}`, {}
    );
  }

  uploadProcessed(orderId: number, formData: FormData): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/mixmaster-engineer/upload/${orderId}`, formData
    );
  }

  deliverRevision(orderId: number, formData: FormData): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.apiUrl}/mixmaster-engineer/deliver-revision/${orderId}`, formData
    );
  }

  // ── Payment verification ───────────────────────────────────────────────────

  verifyPayment(sessionId: string): Observable<ApiResponse<OrderIdData>> {
    return this.http.post<ApiResponse<OrderIdData>>(
      `${this.apiUrl}/mixmaster-payment/verify`, { session_id: sessionId }
    );
  }
}
