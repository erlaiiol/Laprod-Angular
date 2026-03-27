import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

// ── Request / Response types ──────────────────────────────────────────────────

export interface CheckoutOptions {
  is_lifetime?:             boolean;
  duration_years?:          number;
  territory?:               'France' | 'Europe' | 'Monde entier';
  mechanical_reproduction?: boolean;
  public_show?:             boolean;
  arrangement?:             boolean;
  total_price?:             number;
  buyer_address?:           string;
  buyer_email?:             string;
}

export interface CheckoutData {
  checkout_url: string;
  total:        number;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class PaymentService {

  private http   = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/api/payment`;

  /**
   * Crée une session Stripe Checkout pour l'achat d'un track.
   * En cas de succès, redirige le navigateur vers checkout_url (Stripe).
   */
  createCheckout(
    trackId: number,
    format: string,
    options: CheckoutOptions,
  ): Observable<ApiResponse<CheckoutData>> {
    return this.http.post<ApiResponse<CheckoutData>>(
      `${this.apiUrl}/track/${trackId}/${format}/checkout`,
      options,
    );
  }

  /** Redirige le navigateur vers l'URL Stripe Checkout. */
  redirectToCheckout(url: string): void {
    window.location.href = url;
  }
}
