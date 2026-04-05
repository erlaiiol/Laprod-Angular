import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface WalletInfo {
  balance_available:         number;
  balance_pending:           number;
  stripe_account_id:         string | null;
  stripe_onboarding_complete: boolean;
  stripe_account_status:     string | null;
}

export interface WalletTransaction {
  id:                 number;
  type:               string;
  amount:             number;
  status:             'pending' | 'available' | 'transferred' | 'expired';
  description:        string | null;
  available_at:       string | null;
  created_at:         string;
  stripe_transfer_id: string | null;
}

export interface WalletData {
  wallet:              WalletInfo;
  transactions:        WalletTransaction[];
  show_connect_alert:  boolean;
}

export interface Purchase {
  id:               number;
  track_id:         number;
  format_purchased: string;
  price_paid:       number;
  track_price:      number;
  contract_price:   number;
  composer_revenue: number;
  contract_file:    string | null;
  created_at:       string;
  track: {
    id:                 number;
    title:              string;
    image_file:         string;
    composer_username:  string;
  } | null;
}

export interface SalesData {
  sales:         Purchase[];
  total_revenue: number;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class WalletService {

  private http         = inject(HttpClient);
  private walletUrl    = `${environment.apiUrl}/wallet-api`;
  private cudWalletUrl    = `${environment.apiUrl}/cud_wallet`;
  private contractsUrl = `${environment.apiUrl}/api/contracts`;
  private stripeUrl    = `${environment.apiUrl}/api/stripe`;

  // ── Wallet ────────────────────────────────────────────────────────────────

  getWallet(): Observable<ApiResponse<WalletData>> {
    return this.http.get<ApiResponse<WalletData>>(this.walletUrl);
  }

  withdraw(amount: number): Observable<ApiResponse<{ transfer_id: string; amount: number }>> {
    return this.http.post<ApiResponse<{ transfer_id: string; amount: number }>>(
      `${this.cudWalletUrl}/withdraw`,
      { amount },
    );
  }

  // ── Contracts / Purchases ─────────────────────────────────────────────────

  getMyPurchases(): Observable<ApiResponse<{ purchases: Purchase[] }>> {
    return this.http.get<ApiResponse<{ purchases: Purchase[] }>>(`${this.contractsUrl}/my`);
  }

  getMySales(): Observable<ApiResponse<SalesData>> {
    return this.http.get<ApiResponse<SalesData>>(`${this.contractsUrl}/sales`);
  }

  // ── Stripe Connect ────────────────────────────────────────────────────────

  getStripeStatus(): Observable<ApiResponse<{
    stripe_account_id: string | null;
    stripe_onboarding_complete: boolean;
    stripe_account_status: string | null;
  }>> {
    return this.http.get<any>(`${this.stripeUrl}/status`);
  }

  getSetupUrl(returnUrl?: string): Observable<ApiResponse<{ url: string }>> {
    return this.http.post<ApiResponse<{ url: string }>>(`${this.stripeUrl}/setup-url`, {
      return_url:  returnUrl,
      refresh_url: returnUrl,
    });
  }

  getDashboardUrl(): Observable<ApiResponse<{ url: string }>> {
    return this.http.post<ApiResponse<{ url: string }>>(`${this.stripeUrl}/dashboard-url`, {});
  }

  refreshStripeStatus(): Observable<ApiResponse<{
    stripe_onboarding_complete: boolean;
    stripe_account_status: string;
  }>> {
    return this.http.post<any>(`${this.stripeUrl}/refresh`, {});
  }
}
