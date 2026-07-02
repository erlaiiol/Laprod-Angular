import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { UploadStatusService } from './upload-status.service';
import { ToastService } from './toast.service';
import { environment } from '../../environments/environment';

const JOB_URL = (id: string) => `${environment.apiUrl}/api/job_status/${id}`;

const flush = (httpMock: HttpTestingController, jobId: string, status: string, trackId = '1') => {
  httpMock.expectOne(JOB_URL(jobId)).flush({
    success: true,
    data: { status, track_id: status === 'done' ? trackId : null, topline_id: null },
  });
};

describe('UploadStatusService', () => {
  let service: UploadStatusService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        UploadStatusService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ToastService, useValue: { showToast: vi.fn() } },
      ],
    });
    service = TestBed.inject(UploadStatusService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    service.stopPolling();
    httpMock.verify();
    localStorage.clear();
  });

  // ── openForUpload ────────────────────────────────────────────────────────────

  describe('openForUpload()', () => {
    it('passe status à uploading et remet progress à 0', () => {
      service.openForUpload('Mon Beat', null);
      expect(service.status()).toBe('uploading');
      expect(service.progress()).toBe(0);
    });

    it('stocke title et imageUrl', () => {
      service.openForUpload('Mon Beat', 'blob:local');
      expect(service.title()).toBe('Mon Beat');
      expect(service.imageUrl()).toBe('blob:local');
    });

    it('efface errorMessage et trackId résiduels', () => {
      (service as any)._errorMessage.set('ancienne erreur');
      (service as any)._trackId.set('42');
      service.openForUpload('New Beat', null);
      expect(service.errorMessage()).toBeNull();
      expect(service.trackId()).toBeNull();
    });

    it('accepte imageUrl null (pas de cover)', () => {
      service.openForUpload('Instrumental', null);
      expect(service.imageUrl()).toBeNull();
    });
  });

  // ── setUploadProgress ────────────────────────────────────────────────────────

  describe('setUploadProgress()', () => {
    beforeEach(() => service.openForUpload('Beat', null));

    it('mappe 0 % XHR → 0 % affiché', () => {
      service.setUploadProgress(0);
      expect(service.progress()).toBe(0);
    });

    it('mappe 100 % XHR → 65 % affiché', () => {
      service.setUploadProgress(100);
      expect(service.progress()).toBe(65);
    });

    it('mappe 50 % XHR → 33 % affiché (arrondi)', () => {
      service.setUploadProgress(50);
      expect(service.progress()).toBe(Math.round(50 * 0.65));
    });

    it('ne modifie rien si status n\'est pas uploading', () => {
      // status est déjà 'uploading', on le force à null
      service.stopPolling(); // remet status=null et progress=0
      service.setUploadProgress(80);
      expect(service.progress()).toBe(0);
    });
  });

  // ── startPolling ─────────────────────────────────────────────────────────────

  describe('startPolling()', () => {
    it('passe immédiatement status à queued', () => {
      service.openForUpload('Beat', null);
      service.startPolling('job-queued');
      expect(service.status()).toBe('queued');
    });

    it('monte progress à 68 si en dessous de 68 (XHR terminé à 65)', () => {
      service.openForUpload('Beat', null);
      service.setUploadProgress(100); // → 65 %
      service.startPolling('job-bump');
      expect(service.progress()).toBe(68);
    });

    it('ne rétrograde pas progress si déjà ≥ 68', () => {
      service.openForUpload('Beat', null);
      (service as any)._progress.set(75);
      service.startPolling('job-high');
      expect(service.progress()).toBe(75);
    });

    it('persiste job_id dans localStorage', () => {
      service.startPolling('job-store');
      expect(localStorage.getItem('upload_job_id')).toBe('job-store');
    });

    it('persiste title dans localStorage si défini', () => {
      service.openForUpload('Mon Son', null);
      service.startPolling('job-title');
      expect(localStorage.getItem('upload_track_title')).toBe('Mon Son');
    });
  });

  // ── simulation de progression RQ ─────────────────────────────────────────────

  describe('simulation de progression RQ', () => {
    it('done → progress=100 et status=done', fakeAsync(() => {
      service.openForUpload('Beat', null);
      service.startPolling('job-done');
      tick(0);
      flush(httpMock, 'job-done', 'done', '7');
      tick(0);
      expect(service.progress()).toBe(100);
      expect(service.status()).toBe('done');
      expect(service.trackId()).toBe('7');
    }));

    it('finalizing → progress=95', fakeAsync(() => {
      service.openForUpload('Beat', null);
      service.startPolling('job-final');
      tick(0);
      flush(httpMock, 'job-final', 'finalizing');
      tick(3000);
      expect(service.progress()).toBe(95);
      flush(httpMock, 'job-final', 'done');
      tick(0);
    }));

    it('queued → progress incrémenté de 1 (cap 73)', fakeAsync(() => {
      service.openForUpload('Beat', null);
      service.startPolling('job-q');
      // progress démarre à 68
      tick(0);
      flush(httpMock, 'job-q', 'queued');
      tick(3000);
      expect(service.progress()).toBe(69);
      flush(httpMock, 'job-q', 'done');
      tick(0);
    }));

    it('started → progress incrémenté de 4 (cap 90)', fakeAsync(() => {
      service.openForUpload('Beat', null);
      service.startPolling('job-s');
      tick(0);
      flush(httpMock, 'job-s', 'started');
      tick(3000);
      expect(service.progress()).toBe(72); // 68 + 4
      flush(httpMock, 'job-s', 'done');
      tick(0);
    }));

    it('error → status=error et errorMessage défini', fakeAsync(() => {
      service.openForUpload('Beat', null);
      service.startPolling('job-err');
      tick(0);
      httpMock.expectOne(JOB_URL('job-err')).flush({
        success: true,
        data: { status: 'error', error_message: 'worker crash', track_id: null, topline_id: null },
      });
      tick(0);
      expect(service.status()).toBe('error');
      expect(service.errorMessage()).toBe('worker crash');
      // progress ne doit pas changer sur erreur
      expect(service.progress()).toBe(68);
    }));
  });

  // ── stopPolling ──────────────────────────────────────────────────────────────

  describe('stopPolling()', () => {
    it('remet status à null et progress à 0', () => {
      service.openForUpload('Beat', null);
      service.stopPolling();
      expect(service.status()).toBeNull();
      expect(service.progress()).toBe(0);
    });

    it('vide title et imageUrl', () => {
      service.openForUpload('Beat', 'blob:url');
      service.stopPolling();
      expect(service.title()).toBeNull();
      expect(service.imageUrl()).toBeNull();
    });

    it('retire les clés localStorage', () => {
      service.startPolling('job-del');
      service.stopPolling();
      expect(localStorage.getItem('upload_job_id')).toBeNull();
      expect(localStorage.getItem('upload_track_title')).toBeNull();
    });
  });
});
