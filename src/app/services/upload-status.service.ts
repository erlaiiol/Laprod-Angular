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

/** Toutes les valeurs possibles du signal status, y compris la phase d'envoi HTTP. */
export type UploadStatus = 'uploading' | 'queued' | 'started' | 'finalizing' | 'done' | 'error' | null;

@Injectable({ providedIn: 'root' })
export class UploadStatusService {

  private pollingSub?: Subscription;

  private readonly _status       = signal<UploadStatus>(null);
  private readonly _jobId        = signal<string | null>(null);
  private readonly _errorMessage = signal<string | null>(null);
  private readonly _trackId      = signal<string | null>(null);
  private readonly _title        = signal<string | null>(null);
  private readonly _imageUrl     = signal<string | null>(null);
  /** Progression 0–100 affichée dans le toast. */
  private readonly _progress     = signal(0);

  readonly status       = this._status.asReadonly();
  readonly jobId        = this._jobId.asReadonly();
  readonly errorMessage = this._errorMessage.asReadonly();
  readonly trackId      = this._trackId.asReadonly();
  readonly title        = this._title.asReadonly();
  readonly imageUrl     = this._imageUrl.asReadonly();
  readonly progress     = this._progress.asReadonly();

  private readonly jobApiUrl = `${environment.apiUrl}/api/job_status`;

  private readonly KEY_JOB   = 'upload_job_id';
  private readonly KEY_TITLE = 'upload_track_title';
  private readonly KEY_IMAGE = 'upload_track_image';

  constructor(private http: HttpClient, private toastSvc: ToastService) {
    // Reprendre un job en cours si l'utilisateur a refreshé la page.
    // L'upload est déjà terminé → on démarre à 68% directement en phase traitement.
    const storedJobId = localStorage.getItem(this.KEY_JOB);
    if (storedJobId) {
      this._jobId.set(storedJobId);
      this._title.set(localStorage.getItem(this.KEY_TITLE));
      this._imageUrl.set(localStorage.getItem(this.KEY_IMAGE));
      this._progress.set(68);
      this._status.set('queued');
      this._startTimer(storedJobId);
    }
  }

  /**
   * Ouvre le toast DÈS le début de l'envoi HTTP, avant même d'avoir le job_id.
   * Doit être appelé juste avant l'appel HTTP dans le composant d'upload.
   */
  openForUpload(title: string, imageUrl: string | null): void {
    this.pollingSub?.unsubscribe();
    this._title.set(title);
    this._setImageUrl(imageUrl);
    this._status.set('uploading');
    this._progress.set(0);
    this._trackId.set(null);
    this._errorMessage.set(null);
  }

  /**
   * Met à jour la progression pendant l'envoi HTTP (0–100 XHR → 0–65 affiché).
   * Réservé à la phase 'uploading'.
   */
  setUploadProgress(xhrPct: number): void {
    if (this._status() !== 'uploading') return;
    this._progress.set(Math.round(xhrPct * 0.65));
  }

  /**
   * Démarre le polling RQ. Appelé dès que le backend renvoie le job_id.
   * Si openForUpload() a déjà été appelé, title/imageUrl sont conservés.
   */
  startPolling(jobId: string, title?: string | null, imageUrl?: string | null): void {
    this._jobId.set(jobId);
    if (title)    this._title.set(title);
    if (imageUrl) this._setImageUrl(imageUrl);

    // Si l'upload XHR vient de finir, progress ≈ 65%. On passe à 68% pour
    // signaler la transition vers la phase traitement worker.
    if (this._progress() < 68) this._progress.set(68);
    this._status.set('queued');

    localStorage.setItem(this.KEY_JOB, jobId);
    if (this._title()) localStorage.setItem(this.KEY_TITLE, this._title()!);
    // Une URL blob: est morte après un reload : inutile (et trompeur) de la persister.
    const imageUrlToStore = this._imageUrl();
    if (imageUrlToStore && !imageUrlToStore.startsWith('blob:')) {
      localStorage.setItem(this.KEY_IMAGE, imageUrlToStore);
    }

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
    this._setImageUrl(null);
    this._progress.set(0);

    localStorage.removeItem(this.KEY_JOB);
    localStorage.removeItem(this.KEY_TITLE);
    localStorage.removeItem(this.KEY_IMAGE);
  }

  /**
   * Écrase l'image du toast en révoquant l'éventuel blob: précédent,
   * sinon l'objet reste retenu en mémoire pour toute la session.
   */
  private _setImageUrl(url: string | null): void {
    const previous = this._imageUrl();
    if (previous?.startsWith('blob:') && previous !== url) {
      URL.revokeObjectURL(previous);
    }
    this._imageUrl.set(url);
  }

  /**
   * Séparé de startPolling() pour être appelable depuis le constructeur
   * (reprise après refresh) sans réécrire dans localStorage.
   */
  private _startTimer(jobId: string): void {
    // 200 ticks × 3 s = 10 min max.
    const MAX_POLLS = 200;
    let   pollCount = 0;

    this.pollingSub = timer(0, 3000)
      .pipe(
        switchMap(() => {
          pollCount++;
          if (pollCount > MAX_POLLS) {
            return of({
              success: true,
              data: {
                status: 'error' as const,
                error_message: 'timeout',
                track_id: null,
                topline_id: null,
              },
            } satisfies JobStatusResponse);
          }
          return this.http.get<JobStatusResponse>(`${this.jobApiUrl}/${jobId}`).pipe(
            catchError(() => {
              this.toastSvc.showToast({ level: 'warning', message: 'Erreur réseau, nouvelle tentative...' });
              return of(null);
            })
          );
        }),
        takeWhile(
          response => response !== null &&
            response.data.status !== 'done' &&
            response.data.status !== 'error',
          true  // inclusif : laisse passer le dernier tick done/error
        ),
        finalize(() => {
          localStorage.removeItem(this.KEY_JOB);
          localStorage.removeItem(this.KEY_TITLE);
          localStorage.removeItem(this.KEY_IMAGE);
        })
      )
      .subscribe(response => {
        if (!response) return;

        if (response.data.error_message === 'timeout') {
          this._status.set('error');
          this._errorMessage.set(
            'Le traitement prend trop de temps (serveur indisponible ?). ' +
            'Votre beat sera peut-être traité automatiquement dans quelques minutes. ' +
            'Vérifiez votre tableau de bord ou contactez le support si le problème persiste.'
          );
          return;
        }

        const status = response.data.status;
        this._status.set(status);
        this._errorMessage.set(response.data.error_message ?? null);
        this._trackId.set(response.data.track_id);

        // Simulation de progression côté worker RQ (68% → 100%).
        // Chaque tick RQ fait avancer la barre ; 'done' la complète immédiatement.
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
          // 'error' : on laisse la progression là où elle est
        }
      });
  }
}
