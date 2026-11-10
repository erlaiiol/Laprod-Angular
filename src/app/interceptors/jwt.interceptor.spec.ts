import { vi } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { HttpClient, HttpErrorResponse, HttpInterceptorFn, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { jwtInterceptor } from './jwt.interceptor';
import { AuthService } from '../services/auth.service';

describe('jwtInterceptorInterceptor', () => {
  const interceptor: HttpInterceptorFn = (req, next) =>
    TestBed.runInInjectionContext(() => jwtInterceptor(req, next));

  let http: HttpClient;
  let httpMock: HttpTestingController;
  let authUrl: string;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        provideHttpClient(withInterceptors([jwtInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
    authUrl = TestBed.inject(AuthService).getAuthUrl();
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('should be created', () => {
    expect(interceptor).toBeTruthy();
  });

  it('laisse remonter le 401 de /login tel quel (message serveur conservé)', () => {
    const body = { success: false, feedback: { message: 'Identifiants incorrects.' } };
    let received: HttpErrorResponse | undefined;

    http.post(`${authUrl}/login`, {}).subscribe({ error: (e) => (received = e) });
    httpMock.expectOne(`${authUrl}/login`).flush(body, { status: 401, statusText: 'Unauthorized' });

    expect(received?.status).toBe(401);
    expect(received?.error?.feedback?.message).toBe('Identifiants incorrects.');
  });

  it('ne tente pas de refresh sur un 401 sans session', () => {
    let received: HttpErrorResponse | undefined;

    http.get('/api/main/whatever').subscribe({ error: (e) => (received = e) });
    httpMock.expectOne('/api/main/whatever').flush({}, { status: 401, statusText: 'Unauthorized' });

    httpMock.expectNone(`${authUrl}/refresh`);
    expect(received?.status).toBe(401);
  });
});

// Real AuthService + interceptor: catches accidental replacement of the refresh header.
describe('JWT session recovery', () => {
  let http: HttpClient;
  let mock: HttpTestingController;
  let auth: AuthService;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    localStorage.setItem('access_token', 'old-access');
    localStorage.setItem('refresh_token', 'refresh-secret');
    TestBed.configureTestingModule({ providers: [
      provideRouter([]), provideHttpClient(withInterceptors([jwtInterceptor])), provideHttpClientTesting(),
    ] });
    http = TestBed.inject(HttpClient);
    mock = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
  });

  afterEach(() => { mock.verify(); localStorage.clear(); sessionStorage.clear(); });

  it('shares one refresh, preserves its header, stores rotation and retries concurrent requests', () => {
    http.get('/api/one').subscribe();
    http.get('/api/two').subscribe();
    mock.expectOne('/api/one').flush({}, { status: 401, statusText: 'Unauthorized' });
    mock.expectOne('/api/two').flush({}, { status: 401, statusText: 'Unauthorized' });
    const refresh = mock.expectOne(`${auth.getAuthUrl()}/refresh`);
    expect(refresh.request.headers.get('Authorization')).toBe('Bearer refresh-secret');
    refresh.flush({ data: { access_token: 'new-access', refresh_token: 'new-refresh' } });
    for (const url of ['/api/one', '/api/two']) {
      const retry = mock.expectOne(url);
      expect(retry.request.headers.get('Authorization')).toBe('Bearer new-access');
      retry.flush({});
    }
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh');
    // A subsequent renewal must be a new request (shared observable was released).
    auth.refreshToken().subscribe();
    const nextRefresh = mock.expectOne(`${auth.getAuthUrl()}/refresh`);
    expect(nextRefresh.request.headers.get('Authorization')).toBe('Bearer new-refresh');
    nextRefresh.flush({ data: { access_token: 'third-access', refresh_token: 'third-refresh' } });
  });

  for (const status of [0, 429, 503]) {
    it(`keeps credentials when refresh fails with transient status ${status}`, () => {
      http.get('/api/one').subscribe({ error: () => {} });
      mock.expectOne('/api/one').flush({}, { status: 401, statusText: 'Unauthorized' });
      const refresh = mock.expectOne(`${auth.getAuthUrl()}/refresh`);
      if (status === 0) refresh.error(new ProgressEvent('error'));
      else refresh.flush({}, { status, statusText: 'Unavailable' });
      expect(auth.getToken()).toBe('old-access');
      expect(localStorage.getItem('refresh_token')).toBe('refresh-secret');
    });
  }

  for (const status of [401, 422]) {
    it(`clears a definitively rejected refresh (${status}), including proactive refresh`, () => {
      auth.refreshToken().subscribe({ error: () => {} });
      mock.expectOne(`${auth.getAuthUrl()}/refresh`).flush({}, { status, statusText: 'Invalid token' });
      expect(auth.getToken()).toBeNull();
      expect(localStorage.getItem('refresh_token')).toBeNull();
    });
  }

  it('retries a late 401 using the token already renewed by another request', () => {
    http.get('/api/one').subscribe();
    http.get('/api/two').subscribe();
    const first = mock.expectOne('/api/one');
    const late = mock.expectOne('/api/two');
    first.flush({}, { status: 401, statusText: 'Unauthorized' });
    mock.expectOne(`${auth.getAuthUrl()}/refresh`).flush({ data: { access_token: 'new-access' } });
    mock.expectOne('/api/one').flush({});
    late.flush({}, { status: 401, statusText: 'Unauthorized' });
    const retry = mock.expectOne('/api/two');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer new-access');
    retry.flush({});
    mock.expectNone(`${auth.getAuthUrl()}/refresh`);
  });

  it('does not leak credentials to an external URL', () => {
    http.get('https://external.example/api/file').subscribe();
    const req = mock.expectOne('https://external.example/api/file');
    expect(req.request.headers.has('Authorization')).toBe(false);
    req.flush({});
  });

  it('does not restore credentials if logout happened while refresh was in flight', () => {
    auth.refreshToken().subscribe({ error: () => {} });
    const refresh = mock.expectOne(`${auth.getAuthUrl()}/refresh`);
    auth.silentLogout();
    refresh.flush({ data: { access_token: 'new-access', refresh_token: 'new-refresh' } });
    expect(auth.getToken()).toBeNull();
  });
});
