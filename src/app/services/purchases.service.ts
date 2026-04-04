import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

export interface PurchasedTrack {
  id:               number;
  title:            string;
  image_file:       string | null;
  composer_username: string | null;
  composer_image:   string | null;
}

export interface PurchaseItem {
  id:            number;
  format:        string;
  price_paid:    number;
  track_price:   number;
  contract_price: number;
  has_contract:  boolean;
  created_at:    string;
  stream_url:    string;
  contract_url:  string | null;
  track:         PurchasedTrack | null;
}

export interface MixOrderPurchase {
  id:                               number;
  title:                            string;
  total_price:                      number;
  completed_at:                     string | null;
  created_at:                       string;
  services: {
    cleaning:  boolean;
    effects:   boolean;
    artistic:  boolean;
    mastering: boolean;
  };
  engineer_username:                string | null;
  engineer_image:                   string | null;
  processed_file_preview_url:       string | null;
  processed_file_preview_full_url:  string | null;
  download_url:                     string;
}

export interface PurchasesData {
  purchases:      PurchaseItem[];
  total_spent:    number;
  mm_orders:      MixOrderPurchase[];
  mm_total_spent: number;
}

@Injectable({ providedIn: 'root' })
export class PurchasesService {

  private http         = inject(HttpClient);
  private purchasesUrl = `${environment.apiUrl}/purchases`;

  getMyPurchases(): Observable<ApiResponse<PurchasesData>> {
    return this.http.get<ApiResponse<PurchasesData>>(this.purchasesUrl);
  }
}
