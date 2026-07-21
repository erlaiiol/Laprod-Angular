import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

/** Barème fermé — doit rester aligné sur utils/money.py (ALLOWED_DISCOUNT_PERCENTS). */
export const PROMO_PERCENTS = [10, 20, 30, 50, 70] as const;
export type PromoPercent = (typeof PROMO_PERCENTS)[number];

export type PromoScope = 'track' | 'mixmaster';

/** Clés de prestation mix/master remisables (alignées sur MIXMASTER_SERVICE_KEYS). */
export type PromoServiceKey = 'cleaning' | 'effects' | 'artistic' | 'mastering' | 'stems';

export const SERVICE_LABELS: Record<PromoServiceKey, string> = {
  cleaning:  'Nettoyage et équilibre',
  effects:   'Mixage avec effets',
  artistic:  'Intervention artistique',
  mastering: 'Mastering final',
  stems:     'Pistes séparées',
};

export interface PromoCode {
  id:              number;
  code:            string;
  percent:         PromoPercent;
  scope:           PromoScope;
  applies_to_all:  boolean;
  once_per_user:   boolean;
  is_active:       boolean;
  is_expired:      boolean;
  is_exhausted:    boolean;
  expires_at:      string | null;
  max_redemptions: number | null;
  redemption_count: number;
  remaining_redemptions: number | null;
  track_ids:       number[];
  service_keys:    PromoServiceKey[];
  created_at:      string | null;
}

export interface PromoContextTrack {
  id:        number;
  title:     string;
  cover_url: string | null;
  price_mp3: number | null;
}

export interface PromoContext {
  tracks:           PromoContextTrack[];
  service_keys:     PromoServiceKey[];
  allowed_percents: number[];
  is_premium:       boolean;
}

export interface PromoListData {
  promo_codes: PromoCode[];
  can_create:  boolean;
}

/** Remise chiffrée renvoyée par l'aperçu — calculée par le MÊME code que le checkout. */
export interface PromoPreview {
  code:     string;
  percent:  PromoPercent;
  gross:    number;
  discount: number;
  net:      number;
}

export interface PromoPayload {
  code:             string;
  percent:          number;
  scope:            PromoScope;
  applies_to_all:   boolean;
  once_per_user:    boolean;
  expires_at:       string | null;
  max_redemptions:  number | null;
  track_ids?:       number[];
  service_keys?:    PromoServiceKey[];
}

@Injectable({ providedIn: 'root' })
export class PromoService {

  private http     = inject(HttpClient);
  private promoUrl = `${environment.apiUrl}/api/promo-codes`;

  /** Mes codes promo (vendeur). */
  list(): Observable<ApiResponse<PromoListData>> {
    return this.http.get<ApiResponse<PromoListData>>(this.promoUrl);
  }

  /** Beats et prestations remisables — alimente les sélecteurs du formulaire. */
  context(): Observable<ApiResponse<PromoContext>> {
    return this.http.get<ApiResponse<PromoContext>>(`${this.promoUrl}/context`);
  }

  create(payload: PromoPayload): Observable<ApiResponse<{ promo_code: PromoCode }>> {
    return this.http.post<ApiResponse<{ promo_code: PromoCode }>>(this.promoUrl, payload);
  }

  update(id: number, payload: Partial<PromoPayload>): Observable<ApiResponse<{ promo_code: PromoCode }>> {
    return this.http.patch<ApiResponse<{ promo_code: PromoCode }>>(`${this.promoUrl}/${id}`, payload);
  }

  /** Activer/désactiver — reste permis même sans Premium actif. */
  setActive(id: number, isActive: boolean): Observable<ApiResponse<{ promo_code: PromoCode }>> {
    return this.http.patch<ApiResponse<{ promo_code: PromoCode }>>(
      `${this.promoUrl}/${id}`, { is_active: isActive },
    );
  }

  remove(id: number): Observable<ApiResponse<{ deleted: boolean; promo_code?: PromoCode }>> {
    return this.http.delete<ApiResponse<{ deleted: boolean; promo_code?: PromoCode }>>(`${this.promoUrl}/${id}`);
  }

  /** Codes applicables à un beat donné (upload-track / edit-track). */
  setTrackPromoCodes(trackId: number, promoCodeIds: number[]): Observable<ApiResponse<{ promo_code_ids: number[] }>> {
    return this.http.put<ApiResponse<{ promo_code_ids: number[] }>>(
      `${this.promoUrl}/track/${trackId}`, { promo_code_ids: promoCodeIds },
    );
  }

  /**
   * Valide un code saisi par l'acheteur et renvoie la remise chiffrée.
   * Ne consomme rien : le quota n'est décrémenté qu'au paiement réussi.
   * Le serveur recalcule tout — on ne lui envoie jamais un montant à croire.
   */
  previewTrack(payload: {
    code: string; track_id: number; format_type: string;
    is_exclusive?: boolean; is_lifetime?: boolean; duration_years?: number;
    territory?: string; mechanical_reproduction?: boolean;
    public_show?: boolean; arrangement?: boolean;
  }): Observable<ApiResponse<PromoPreview>> {
    return this.http.post<ApiResponse<PromoPreview>>(
      `${this.promoUrl}/preview`, { scope: 'track', ...payload },
    );
  }

  previewMixmaster(payload: {
    code: string; engineer_id: number;
    service_cleaning?: boolean; service_effects?: boolean;
    service_artistic?: boolean; service_mastering?: boolean;
    has_separated_stems?: boolean;
  }): Observable<ApiResponse<PromoPreview>> {
    return this.http.post<ApiResponse<PromoPreview>>(
      `${this.promoUrl}/preview`, { scope: 'mixmaster', ...payload },
    );
  }
}
