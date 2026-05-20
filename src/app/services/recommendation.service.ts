import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Track } from './track.service';

export interface RecommendationsResponse {
  success: boolean;
  data: {
    tracks: Track[];
    is_personalized: boolean;
  };
}

export interface RecommendationProfile {
  success: boolean;
  data: {
    profile: {
      keys: Record<string, number>;
      tags: Record<string, number>;
      styles: Record<string, number>;
      preferred_bpm_center: number;
      preferred_duration: number;
      avg_completion: number;
      favorite_beatmakers: Record<string, number>;
    };
    listen_event_count: number;
  };
}

@Injectable({ providedIn: 'root' })
export class RecommendationService {

  private http = inject(HttpClient);
  private readonly apiUrl = `${environment.apiUrl}/api/recommendations`;

  getTracks(): Observable<RecommendationsResponse> {
    return this.http.get<RecommendationsResponse>(`${this.apiUrl}/tracks`);
  }

  getMyProfile(): Observable<RecommendationProfile> {
    return this.http.get<RecommendationProfile>(`${this.apiUrl}/my-profile`);
  }

}
