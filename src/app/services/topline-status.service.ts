import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subscription, switchMap, takeWhile, timer, finalize, catchError, of } from 'rxjs';
import { environment } from '../../environments/environment';
import { ToastService } from './toast.service';
import { JobStatusResponse } from './upload-status.service';

@Injectable({ providedIn: 'root' })
export class ToplineStatusService {

  private pollingSub?: Subscription;

  private readonly _status       = signal<'queued' | 'started' | 'finalizing' | 'done' | 'error' | null>(null);
  private readonly _jobId        = signal<string | null>(null);
  private readonly _toplineId    = signal<string | null>(null);
  private readonly _errorMessage = signal<string | null>(null);

  readonly status       = this._status.asReadonly();
  readonly jobId        = this._jobId.asReadonly();
  readonly toplineId    = this._toplineId.asReadonly();
  readonly errorMessage = this._errorMessage.asReadonly();

  private readonly jobApiUrl = `${environment.apiUrl}/api/job_status`;
  private readonly KEY_JOB   = 'topline_job_id';

  constructor(private http: HttpClient, private toastSvc: ToastService) {
    // Reprendre un job en cours si l'utilisateur a rafraîchi la page
    const storedJobId = localStorage.getItem(this.KEY_JOB);
    if (storedJobId) {
      this._jobId.set(storedJobId);
      this._startTimer(storedJobId);
    }
  }

  startPolling(jobId: string): void {
    this._jobId.set(jobId);
    localStorage.setItem(this.KEY_JOB, jobId);

    this.pollingSub?.unsubscribe();
    this._startTimer(jobId);
  }

  stopPolling(): void {
    this.pollingSub?.unsubscribe();
    this.pollingSub = undefined;

    this._jobId.set(null);
    this._status.set(null);
    this._toplineId.set(null);
    this._errorMessage.set(null);

    localStorage.removeItem(this.KEY_JOB);
  }

  private _startTimer(jobId: string): void {
    this.pollingSub = timer(0, 3000)
      .pipe(
        switchMap(() =>
          this.http.get<JobStatusResponse>(`${this.jobApiUrl}/${jobId}`).pipe(
            catchError(() => {
              this.toastSvc.showToast({ level: 'warning', message: 'Erreur réseau, nouvelle tentative...' });
              return of(null);
            })
          )
        ),
        takeWhile(
          response => response !== null &&
            response.data.status !== 'done' &&
            response.data.status !== 'error',
          true  // inclusif : laisse passer le dernier tick (done/error)
        ),
        finalize(() => {
          localStorage.removeItem(this.KEY_JOB);
        })
      )
      .subscribe(response => {
        if (!response) return;
        this._status.set(response.data.status);
        this._toplineId.set(response.data.topline_id);
        this._errorMessage.set(response.data.error_message ?? null);

        if (response.data.status === 'done') {
          this.toastSvc.showToast({ level: 'success', message: 'Topline traitée avec succès !' });
        } else if (response.data.status === 'error') {
          this.toastSvc.showToast({
            level: 'error',
            message: response.data.error_message ?? 'Erreur lors du traitement de la topline.',
          });
        }
      });
  }
}
