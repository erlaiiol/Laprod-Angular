import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subscription, switchMap, takeWhile, timer, finalize, catchError, of } from 'rxjs';
import { environment } from '../../environments/environment';
import { ToastService } from './toast.service';


export interface JobStatusResponse {
  success: boolean;
  data: {
    status:        'queued' | 'started' | 'finalizing' | 'done' | 'error' | null;
    error_message?: string | null;
    track_id:      string | null;
    topline_id:    string | null;
  };
}

@Injectable({ providedIn: 'root' })
export class UploadStatusService {

  private pollingSub?: Subscription;

  private readonly _status       = signal<'queued' | 'started' | 'finalizing' | 'done' | 'error' | null>(null);
  private readonly _jobId        = signal<string | null>(null);
  private readonly _errorMessage = signal<string | null>(null);
  private readonly _trackId      = signal<string | null>(null);
  private readonly _title        = signal<string | null>(null);
  private readonly _imageUrl     = signal<string | null>(null);

  readonly status       = this._status.asReadonly();
  readonly jobId        = this._jobId.asReadonly();
  readonly errorMessage = this._errorMessage.asReadonly();
  readonly trackId      = this._trackId.asReadonly();
  readonly title        = this._title.asReadonly();
  readonly imageUrl     = this._imageUrl.asReadonly();

  private readonly jobApiUrl = `${environment.apiUrl}/api/job_status`;

  private readonly KEY_JOB    = 'upload_job_id';
  private readonly KEY_TITLE  = 'upload_track_title';
  private readonly KEY_IMAGE  = 'upload_track_image';

  constructor(private http: HttpClient, private toastSvc: ToastService) {
    // Reprendre un job en cours si l'utilisateur a refreshé la page
    const storedJobId = localStorage.getItem(this.KEY_JOB);
    if (storedJobId) {
      this._jobId.set(storedJobId);
      this._title.set(localStorage.getItem(this.KEY_TITLE));
      this._imageUrl.set(localStorage.getItem(this.KEY_IMAGE));
      this._startTimer(storedJobId);
    }
  }

  startPolling(jobId: string, title?: string | null, imageUrl?: string | null): void {
    this._jobId.set(jobId);
    this._title.set(title ?? null);
    this._imageUrl.set(imageUrl ?? null);

    localStorage.setItem(this.KEY_JOB, jobId);
    if (title)    localStorage.setItem(this.KEY_TITLE, title);
    if (imageUrl) localStorage.setItem(this.KEY_IMAGE, imageUrl);

    this.pollingSub?.unsubscribe();
    this._startTimer(jobId);
  }

  stopPolling(): void {
    this.pollingSub?.unsubscribe();
    this.pollingSub = undefined;

    this._jobId.set(null);
    this._status.set(null);
    this._trackId.set(null);
    this._errorMessage.set(null);
    this._title.set(null);
    this._imageUrl.set(null);

    localStorage.removeItem(this.KEY_JOB);
    localStorage.removeItem(this.KEY_TITLE);
    localStorage.removeItem(this.KEY_IMAGE);
  }

  // Séparé de startPolling pour pouvoir être appelé depuis le constructeur
  // sans re-écrire dans localStorage (les valeurs y sont déjà).
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
          true   // inclusif : laisse passer le dernier tick (done/error) dans subscribe
        ),
        finalize(() => {
          // S'exécute sur complete ET sur erreur non catchée
          localStorage.removeItem(this.KEY_JOB);
          localStorage.removeItem(this.KEY_TITLE);
          localStorage.removeItem(this.KEY_IMAGE);
        })
      )
      .subscribe(response => {
        if (!response) return;  // null injecté par catchError → tick ignoré
        this._status.set(response.data.status);
        this._errorMessage.set(response.data.error_message ?? null);
        this._trackId.set(response.data.track_id);
      });
  }
}
