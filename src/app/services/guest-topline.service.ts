import { Injectable, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

const SESSION_KEY  = 'laprod_guest_session';
const ATTEMPTS_KEY = 'laprod_guest_attempts';
const PENDING_KEY  = 'laprod_pending_topline_session';
const MAX_ATTEMPTS = 3;

@Injectable({ providedIn: 'root' })
export class GuestToplineService {

  private http = inject(HttpClient);

  readonly sessionId = computed(() => this._getOrCreateSessionId());

  private _attemptCount = signal<number>(
    parseInt(localStorage.getItem(ATTEMPTS_KEY) ?? '0', 10)
  );

  readonly remainingAttempts = computed(() =>
    Math.max(0, MAX_ATTEMPTS - this._attemptCount())
  );

  readonly hasAttemptsLeft = computed(() => this.remainingAttempts() > 0);

  private _getOrCreateSessionId(): string {
    let id = localStorage.getItem(SESSION_KEY);
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem(SESSION_KEY, id);
    }
    return id;
  }

  decrementAttempt(): void {
    const next = this._attemptCount() + 1;
    this._attemptCount.set(next);
    localStorage.setItem(ATTEMPTS_KEY, String(next));
  }

  syncFromServer(remaining: number | null): void {
    if (remaining === null) return;
    const used = MAX_ATTEMPTS - remaining;
    this._attemptCount.set(Math.max(this._attemptCount(), used));
    localStorage.setItem(ATTEMPTS_KEY, String(this._attemptCount()));
  }

  markPendingClaim(): void {
    localStorage.setItem(PENDING_KEY, this.sessionId());
  }

  claimAfterLogin(): Observable<{ success: boolean; data?: { claimed: number } }> {
    const guestSessionId = localStorage.getItem(PENDING_KEY) ?? this.sessionId();
    return this.http.post<{ success: boolean; data?: { claimed: number } }>(
      `${environment.apiUrl}/api/toplines/claim`,
      { guest_session_id: guestSessionId },
    );
  }

  clearPendingClaim(): void {
    localStorage.removeItem(PENDING_KEY);
  }

  hasPendingClaim(): boolean {
    return !!localStorage.getItem(PENDING_KEY);
  }
}
