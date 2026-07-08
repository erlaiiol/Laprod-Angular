import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { catchError, EMPTY, filter, Observable, switchMap, tap } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';
import { AppRefreshService } from './app-refresh.service';

export interface AppNotification {
  id:         number;
  type:       string;
  title:      string;
  message:    string;
  link:       string | null;
  is_read:    boolean;
  created_at: string;
}

type NotifListResponse = {
  success: boolean;
  data?: { notifications: AppNotification[] };
  feedback?: { level: string; message: string };
};

type NotifActionResponse = {
  success: boolean;
  feedback: { level: string; message: string };
  data?: { link?: string | null };
};

@Injectable({ providedIn: 'root' })
export class NotificationService {

  private base = `${environment.apiUrl}/api/main`;

  // Signal centralisé partagé avec la navbar
  readonly notifications = signal<AppNotification[]>([]);
  readonly unreadCount   = signal(0);

  constructor(
    private http:       HttpClient,
    private auth:       AuthService,
    private refreshSvc: AppRefreshService,
  ) {
    // Rafraîchissement silencieux en arrière-plan.
    // switchMap annule la requête précédente si un nouvel événement arrive avant la réponse.
    // catchError empêche une erreur réseau ponctuelle de couper le flux.
    this.refreshSvc.soft$.pipe(
      filter(() => this.auth.isLoggedIn()),
      switchMap(() => this.load().pipe(catchError(() => EMPTY))),
      takeUntilDestroyed(),
    ).subscribe();
  }

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  load(): Observable<NotifListResponse> {
    return this.http.get<NotifListResponse>(`${this.base}/notifications`, {
      headers: this.headers,
    }).pipe(
      tap(res => {
        if (res.success && res.data) {
          this.notifications.set(res.data.notifications);
          this.unreadCount.set(res.data.notifications.filter(n => !n.is_read).length);
        }
      }),
    );
  }

  markAsRead(id: number): Observable<NotifActionResponse> {
    return this.http.post<NotifActionResponse>(
      `${this.base}/notifications/${id}/read`,
      {},
      { headers: this.headers },
    ).pipe(
      tap(res => {
        if (res.success) {
          this.notifications.update(list =>
            list.map(n => n.id === id ? { ...n, is_read: true } : n),
          );
          this.unreadCount.update(c => Math.max(0, c - 1));
        }
      }),
    );
  }

  markAllAsRead(): Observable<NotifActionResponse> {
    return this.http.post<NotifActionResponse>(
      `${this.base}/notifications/mark-all-read`,
      {},
      { headers: this.headers },
    ).pipe(
      tap(res => {
        if (res.success) {
          this.notifications.update(list => list.map(n => ({ ...n, is_read: true })));
          this.unreadCount.set(0);
        }
      }),
    );
  }
}
