import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { GuestToplineService } from './guest-topline.service';
import { environment } from '../../environments/environment';

const CLAIM_URL = `${environment.apiUrl}/api/toplines/claim`;

describe('GuestToplineService', () => {
  let service: GuestToplineService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [GuestToplineService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(GuestToplineService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  it('should be created', () => expect(service).toBeTruthy());

  it('sessionId() crée et persiste un UUID dans localStorage', () => {
    const id1 = service.sessionId();
    expect(id1).toBeTruthy();
    expect(localStorage.getItem('laprod_guest_session')).toBe(id1);
  });

  it('sessionId() réutilise l\'ID existant en localStorage', () => {
    localStorage.setItem('laprod_guest_session', 'fixed-uuid');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [GuestToplineService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(GuestToplineService);
    httpMock = TestBed.inject(HttpTestingController);
    expect(service.sessionId()).toBe('fixed-uuid');
  });

  it('remainingAttempts() commence à 3', () => {
    expect(service.remainingAttempts()).toBe(3);
  });

  it('hasAttemptsLeft() est vrai au démarrage', () => {
    expect(service.hasAttemptsLeft()).toBe(true);
  });

  it('decrementAttempt() réduit remainingAttempts', () => {
    service.decrementAttempt();
    expect(service.remainingAttempts()).toBe(2);
  });

  it('decrementAttempt() persiste le compteur dans localStorage', () => {
    service.decrementAttempt();
    expect(localStorage.getItem('laprod_guest_attempts')).toBe('1');
  });

  it('hasAttemptsLeft() devient false après 3 decrements', () => {
    service.decrementAttempt();
    service.decrementAttempt();
    service.decrementAttempt();
    expect(service.hasAttemptsLeft()).toBe(false);
    expect(service.remainingAttempts()).toBe(0);
  });

  it('syncFromServer() synchronise si le serveur dit moins de tentatives restantes', () => {
    service.syncFromServer(1); // serveur dit 1 restant → 2 utilisés
    expect(service.remainingAttempts()).toBe(1);
  });

  it('markPendingClaim() stocke le sessionId dans localStorage', () => {
    service.markPendingClaim();
    expect(localStorage.getItem('laprod_pending_topline_session')).toBeTruthy();
  });

  it('hasPendingClaim() retourne true après markPendingClaim()', () => {
    service.markPendingClaim();
    expect(service.hasPendingClaim()).toBe(true);
  });

  it('clearPendingClaim() supprime l\'entrée localStorage', () => {
    service.markPendingClaim();
    service.clearPendingClaim();
    expect(service.hasPendingClaim()).toBe(false);
  });

  it('claimAfterLogin() POSTs à /api/toplines/claim', () => {
    service.markPendingClaim();
    service.claimAfterLogin().subscribe();
    const req = httpMock.expectOne(CLAIM_URL);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.guest_session_id).toBeTruthy();
    req.flush({ success: true, data: { claimed: 1 } });
  });
});
