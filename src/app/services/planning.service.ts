import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

// ── Types ─────────────────────────────────────────────────────────────────────

export type PlanningEventType =
  | 'recording_session' | 'writing_session' | 'rehearsal' | 'concert' | 'showcase'
  | 'residency' | 'video_shoot' | 'media_interview' | 'meeting' | 'appointment'
  | 'sacem_deposit' | 'contractual_deadline' | 'release' | 'other';

export type PlanningEventStatus = 'proposed' | 'confirmed' | 'cancelled';

export interface PlanningEventDTO {
  id:              number;
  /** null = événement personnel, aucun lien roster requis. */
  roster_link_id:  number | null;
  title:           string;
  description:     string | null;
  event_type:      PlanningEventType;
  status:          PlanningEventStatus;
  start_at:        string;
  end_at:          string | null;
  timezone:        string;
  all_day:         boolean;
  location:        string | null;
  created_by:      { id: number; username: string; profile_image: string | null };
  created_at:      string;
}

export interface CreatePlanningEventPayload {
  title:        string;
  description?: string;
  event_type:   PlanningEventType;
  start_at:     string;
  end_at?:      string;
  timezone?:    string;
  all_day?:     boolean;
  location?:    string;
}

// Libellés français des types d'événement, utilisés dans les <select> et badges.
export const PLANNING_EVENT_TYPE_LABELS: Record<PlanningEventType, string> = {
  recording_session:    'Session d\'enregistrement',
  writing_session:      'Session d\'écriture',
  rehearsal:            'Répétition',
  concert:              'Concert',
  showcase:              'Showcase',
  residency:              'Résidence',
  video_shoot:              'Tournage clip',
  media_interview:            'Interview média',
  meeting:                      'Réunion',
  appointment:                    'Rendez-vous',
  sacem_deposit:                    'Dépôt SACEM',
  contractual_deadline:              'Échéance contractuelle',
  release:                             'Date de sortie',
  other:                                 'Autre',
};

export const PLANNING_EVENT_TYPE_ICONS: Record<PlanningEventType, string> = {
  recording_session:  'bi-mic-fill',
  writing_session:     'bi-pencil-square',
  rehearsal:            'bi-music-note-beamed',
  concert:               'bi-soundwave',
  showcase:                'bi-easel2',
  residency:                 'bi-house-door',
  video_shoot:                 'bi-camera-video-fill',
  media_interview:               'bi-broadcast',
  meeting:                         'bi-people-fill',
  appointment:                       'bi-calendar-event',
  sacem_deposit:                       'bi-file-earmark-check',
  contractual_deadline:                  'bi-hourglass-split',
  release:                                 'bi-rocket-takeoff',
  other:                                     'bi-calendar3',
};

type ApiResponse<T = unknown> = {
  success:  boolean;
  feedback?: { level: string; message: string };
  data?:    T;
};

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class PlanningService {

  private base = `${environment.apiUrl}/api/planning`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  mine(): Observable<ApiResponse<{ events: PlanningEventDTO[] }>> {
    return this.http.get<any>(`${this.base}/mine`, { headers: this.headers });
  }

  listForLink(linkId: number): Observable<ApiResponse<{ events: PlanningEventDTO[] }>> {
    return this.http.get<any>(`${this.base}/roster/${linkId}/events`, { headers: this.headers });
  }

  /** linkId null → événement personnel (aucun lien roster requis). */
  create(linkId: number | null, payload: CreatePlanningEventPayload): Observable<ApiResponse<{ event: PlanningEventDTO }>> {
    const url = linkId ? `${this.base}/roster/${linkId}/events` : `${this.base}/events`;
    return this.http.post<any>(url, payload, { headers: this.headers });
  }

  update(eventId: number, payload: Partial<CreatePlanningEventPayload>): Observable<ApiResponse<{ event: PlanningEventDTO }>> {
    return this.http.put<any>(`${this.base}/events/${eventId}`, payload, { headers: this.headers });
  }

  confirm(eventId: number): Observable<ApiResponse<{ event: PlanningEventDTO }>> {
    return this.http.post<any>(`${this.base}/events/${eventId}/confirm`, {}, { headers: this.headers });
  }

  cancel(eventId: number): Observable<ApiResponse<{ event: PlanningEventDTO }>> {
    return this.http.post<any>(`${this.base}/events/${eventId}/cancel`, {}, { headers: this.headers });
  }

  delete(eventId: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.base}/events/${eventId}`, { headers: this.headers });
  }

  regenerateIcalToken(): Observable<ApiResponse<{ feed_path: string }>> {
    return this.http.post<any>(`${this.base}/ical-token/regenerate`, {}, { headers: this.headers });
  }
}
