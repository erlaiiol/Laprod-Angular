import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Subscription, switchMap, takeWhile, timer, finalize, catchError, of } from 'rxjs';
import { environment } from '../../environments/environment';
import { ToastService } from './toast.service';
import { JobStatusResponse } from './upload-status.service';

export type ToplineUploadStatus = 'uploading' | 'queued' | 'started' | 'finalizing' | 'done' | 'error' | null;

@Injectable({ providedIn: 'root' })
export class ToplineStatusService {

  private pollingSub?: Subscription;

  private readonly _status        = signal<ToplineUploadStatus>(null);
  private readonly _jobId         = signal<string | null>(null);
  private readonly _toplineId     = signal<string | null>(null);
  private readonly _beatTrackId   = signal<number | null>(null);
  private readonly _trackTitle    = signal<string | null>(null);
  private readonly _trackImageUrl = signal<string | null>(null);
  private readonly _errorMessage  = signal<string | null>(null);
  private readonly _progress      = signal(0);

  readonly status        = this._status.asReadonly();
  readonly jobId         = this._jobId.asReadonly();
  readonly toplineId     = this._toplineId.asReadonly();
  readonly beatTrackId   = this._beatTrackId.asReadonly();
  readonly trackTitle    = this._trackTitle.asReadonly();
  readonly trackImageUrl = this._trackImageUrl.asReadonly();
  readonly errorMessage  = this._errorMessage.asReadonly();
  readonly progress      = this._progress.asReadonly();

  private readonly jobApiUrl        = `${environment.apiUrl}/api/job_status`;
  private readonly KEY_JOB          = 'topline_job_id';
  private readonly KEY_BEAT_TRACK   = 'topline_beat_track_id';
  private readonly KEY_TRACK_TITLE  = 'topline_beat_track_title';
  private readonly KEY_TRACK_IMAGE  = 'topline_beat_track_image';

  constructor(private http: HttpClient, private toastSvc: ToastService) {
    // Reprendre un job en cours si l'utilisateur a rafraîchi la page
    const storedJobId = localStorage.getItem(this.KEY_JOB);
    if (storedJobId) {
      this._jobId.set(storedJobId);
      const storedTrackId = localStorage.getItem(this.KEY_BEAT_TRACK);
      this._beatTrackId.set(storedTrackId ? parseInt(storedTrackId, 10) : null);
      this._trackTitle.set(localStorage.getItem(this.KEY_TRACK_TITLE));
      this._trackImageUrl.set(localStorage.getItem(this.KEY_TRACK_IMAGE));
      this._progress.set(68);
      this._status.set('queued');
      this._startTimer(storedJobId);
    }
  }

  /** Ouvre le toast dès le début de l'envoi HTTP, avant d'avoir le job_id. */
  openForUpload(beatTrackId: number, trackTitle: string, trackImageUrl: string | null): void {
    this.pollingSub?.unsubscribe();
    this._beatTrackId.set(beatTrackId);
    this._trackTitle.set(trackTitle);
    this._trackImageUrl.set(trackImageUrl);
    this._status.set('uploading');
    this._progress.set(0);
    this._toplineId.set(null);
    this._errorMessage.set(null);
  }

  /** Démarre le polling RQ. Appelé dès que le backend renvoie le job_id. */
  startPolling(jobId: string): void {
    this._jobId.set(jobId);
    if (this._progress() < 68) this._progress.set(68);
    this._status.set('queued');

    localStorage.setItem(this.KEY_JOB, jobId);
    const trackId = this._beatTrackId();
    if (trackId)                    localStorage.setItem(this.KEY_BEAT_TRACK, String(trackId));
    if (this._trackTitle())         localStorage.setItem(this.KEY_TRACK_TITLE, this._trackTitle()!);
    if (this._trackImageUrl())      localStorage.setItem(this.KEY_TRACK_IMAGE, this._trackImageUrl()!);

    this.pollingSub?.unsubscribe();
    this._startTimer(jobId);
  }

  /**
   * Utilisé par le chemin mobile natif : la topline est déjà traitée côté client,
   * il n'y a pas de job_id à poller — on passe directement à l'état "done".
   */
  setDoneWithId(toplineId: number): void {
    this.pollingSub?.unsubscribe();
    this._toplineId.set(String(toplineId));
    this._status.set('done');
    this._progress.set(100);
    this.toastSvc.showToast({ level: 'success', message: 'Topline traitée avec succès !' });
  }

  stopPolling(): void {
    this.pollingSub?.unsubscribe();
    this.pollingSub = undefined;

    this._jobId.set(null);
    this._status.set(null);
    this._toplineId.set(null);
    this._beatTrackId.set(null);
    this._trackTitle.set(null);
    this._trackImageUrl.set(null);
    this._errorMessage.set(null);
    this._progress.set(0);

    localStorage.removeItem(this.KEY_JOB);
    localStorage.removeItem(this.KEY_BEAT_TRACK);
    localStorage.removeItem(this.KEY_TRACK_TITLE);
    localStorage.removeItem(this.KEY_TRACK_IMAGE);
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
          true
        ),
        finalize(() => {
          localStorage.removeItem(this.KEY_JOB);
          localStorage.removeItem(this.KEY_BEAT_TRACK);
          localStorage.removeItem(this.KEY_TRACK_TITLE);
          localStorage.removeItem(this.KEY_TRACK_IMAGE);
        })
      )
      .subscribe(response => {
        if (!response) return;

        const status = response.data.status;
        this._status.set(status);
        this._toplineId.set(response.data.topline_id);
        this._errorMessage.set(response.data.error_message ?? null);

        switch (status) {
          case 'queued':
            this._progress.set(Math.min(73, this._progress() + 1));
            break;
          case 'started':
            this._progress.set(Math.min(90, this._progress() + 4));
            break;
          case 'finalizing':
            this._progress.set(95);
            break;
          case 'done':
            this._progress.set(100);
            break;
        }

        if (status === 'done') {
          this.toastSvc.showToast({ level: 'success', message: 'Topline traitée avec succès !' });
        } else if (status === 'error') {
          this.toastSvc.showToast({
            level: 'error',
            message: response.data.error_message ?? 'Erreur lors du traitement de la topline.',
          });
        }
      });
  }
}
