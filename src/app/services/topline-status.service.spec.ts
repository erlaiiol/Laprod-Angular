import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { vi } from 'vitest';

import { ToplineStatusService } from './topline-status.service';
import { ToastService } from './toast.service';
import { environment } from '../../environments/environment';

describe('ToplineStatusService', () => {
  let service: ToplineStatusService;
  let httpMock: HttpTestingController;
  const showToast = vi.fn();

  beforeEach(() => {
    showToast.mockReset();
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        ToplineStatusService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ToastService, useValue: { showToast } },
      ],
    });
    service  = TestBed.inject(ToplineStatusService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    service.stopPolling();
    httpMock.match(() => true).forEach(r => r.flush({}));
    httpMock.verify();
    localStorage.clear();
  });

  it('should be created', () => expect(service).toBeTruthy());

  it('status() démarre à null', () => {
    expect(service.status()).toBeNull();
  });

  it('progress() démarre à 0', () => {
    expect(service.progress()).toBe(0);
  });

  it('openForUpload() passe le status à "uploading"', () => {
    service.openForUpload(1, 'Mon Beat', null);
    expect(service.status()).toBe('uploading');
    expect(service.progress()).toBe(0);
    expect(service.beatTrackId()).toBe(1);
    expect(service.trackTitle()).toBe('Mon Beat');
  });

  it('openForUpload() accepte une imageUrl null', () => {
    service.openForUpload(2, 'Beat 2', null);
    expect(service.trackImageUrl()).toBeNull();
  });

  it('setDoneWithId() passe le status à "done" et progress à 100', () => {
    service.setDoneWithId(42);
    expect(service.status()).toBe('done');
    expect(service.progress()).toBe(100);
    expect(service.toplineId()).toBe('42');
    expect(showToast).toHaveBeenCalledWith(expect.objectContaining({ level: 'success' }));
  });

  it('stopPolling() réinitialise tous les signals', () => {
    service.openForUpload(1, 'Beat', null);
    service.stopPolling();
    expect(service.status()).toBeNull();
    expect(service.beatTrackId()).toBeNull();
    expect(service.trackTitle()).toBeNull();
    expect(service.progress()).toBe(0);
  });

  it('stopPolling() supprime les clés localStorage', () => {
    localStorage.setItem('topline_job_id', 'j1');
    service.stopPolling();
    expect(localStorage.getItem('topline_job_id')).toBeNull();
  });

  it('startPolling() stocke le jobId dans localStorage', () => {
    service.openForUpload(1, 'Beat', null);
    service.startPolling('job-abc');
    expect(localStorage.getItem('topline_job_id')).toBe('job-abc');
    service.stopPolling();
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('startPolling() passe le status à "queued"', () => {
    service.openForUpload(1, 'Beat', null);
    service.startPolling('job-abc');
    expect(service.status()).toBe('queued');
    service.stopPolling();
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('startPolling() passe progress à au moins 68', () => {
    service.openForUpload(1, 'Beat', null);
    service.startPolling('job-abc');
    expect(service.progress()).toBeGreaterThanOrEqual(68);
    service.stopPolling();
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('jobId() reflète le jobId passé à startPolling()', () => {
    service.openForUpload(1, 'Beat', null);
    service.startPolling('job-xyz');
    expect(service.jobId()).toBe('job-xyz');
    service.stopPolling();
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('reprend le job depuis localStorage si topline_job_id est présent au démarrage', () => {
    localStorage.setItem('topline_job_id', 'job-resume');
    localStorage.setItem('topline_beat_track_id', '5');
    localStorage.setItem('topline_beat_track_title', 'Beat Repris');

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        ToplineStatusService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: ToastService, useValue: { showToast } },
      ],
    });
    const svc2 = TestBed.inject(ToplineStatusService);
    httpMock   = TestBed.inject(HttpTestingController);

    expect(svc2.jobId()).toBe('job-resume');
    expect(svc2.beatTrackId()).toBe(5);
    expect(svc2.status()).toBe('queued');

    svc2.stopPolling();
    httpMock.match(() => true).forEach(r => r.flush({}));
    httpMock.verify();
  });
});
