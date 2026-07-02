import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';
import { PurchasedTrack } from './purchases.service';

// ── Types ──────────────────────────────────────────────────────────────────────

export interface LicenseItem {
  id:             number;
  format:         string;
  price_paid:     number;
  created_at:     string;
  is_exclusive:   boolean;
  duration_years: number | null;
  is_lifetime:    boolean;
  territory:      string | null;
  expires_at:     string | null;
  license_status: 'active' | 'expired' | 'renewed' | 'cancelled';
  contract_url:   string | null;
  track:          PurchasedTrack | null;
}

export interface LicenseDetail extends LicenseItem {
  days_remaining:  number | null;
  is_sole_licensee: boolean;
  renewed_from_id: number | null;
  renewed_to_id:   number | null;
}

export interface ComposerLicense {
  id:              number;
  format:          string;
  price_paid:      number;
  composer_revenue: number;
  created_at:      string;
  is_exclusive:    boolean;
  duration_years:  number | null;
  is_lifetime:     boolean;
  territory:       string | null;
  expires_at:      string | null;
  license_status:  string;
  buyer_username:  string;
  buyer_id:        number;
  track_title:     string;
  track_id:        number;
}

export interface ComposerLicensesData {
  licenses:      ComposerLicense[];
  total_revenue: number;
  exclusive:     ComposerLicense[];
}

export interface RenewalData {
  checkout_url: string;
  total:        number;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class LicenseService {

  private http   = inject(HttpClient);
  private apiUrl = environment.apiUrl;

  getLicenses(): Observable<ApiResponse<{ licenses: LicenseItem[] }>> {
    return this.http.get<ApiResponse<{ licenses: LicenseItem[] }>>(
      `${this.apiUrl}/api/licenses`,
    );
  }

  getLicense(purchaseId: number): Observable<ApiResponse<LicenseDetail>> {
    return this.http.get<ApiResponse<LicenseDetail>>(
      `${this.apiUrl}/api/licenses/${purchaseId}`,
    );
  }

  initiateRenewal(
    trackId: number,
    purchaseId: number,
    options: { duration_years?: number; is_lifetime?: boolean; territory?: string },
  ): Observable<ApiResponse<RenewalData>> {
    return this.http.post<ApiResponse<RenewalData>>(
      `${this.apiUrl}/api/track-payment/track/${trackId}/renew/${purchaseId}`,
      options,
    );
  }

  verifyRenewal(sessionId: string): Observable<ApiResponse<{ purchase_id: number }>> {
    return this.http.post<ApiResponse<{ purchase_id: number }>>(
      `${this.apiUrl}/api/track-payment/verify-renewal`,
      { session_id: sessionId },
    );
  }

  getComposerLicenses(): Observable<ApiResponse<ComposerLicensesData>> {
    return this.http.get<ApiResponse<ComposerLicensesData>>(
      `${this.apiUrl}/api/composer/licenses`,
    );
  }

  downloadContract(purchaseId: number): string {
    return `${this.apiUrl}/api/licenses/${purchaseId}/contract`;
  }

  /** Nombre de jours avant expiration — null si lifetime, négatif si expiré. */
  daysRemaining(expiresAt: string | null): number | null {
    if (!expiresAt) return null;
    const diff = new Date(expiresAt).getTime() - Date.now();
    return Math.ceil(diff / (1000 * 60 * 60 * 24));
  }

  /** Urgence d'affichage selon les jours restants. */
  urgency(days: number | null): 'lifetime' | 'ok' | 'soon' | 'urgent' | 'expired' {
    if (days === null) return 'lifetime';
    if (days < 0)  return 'expired';
    if (days <= 7) return 'urgent';
    if (days <= 30) return 'soon';
    return 'ok';
  }
}
