import { vi } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';

import { AuthService, User } from './auth.service';
import { environment } from '../../environments/environment';

// ── Données de test ───────────────────────────────────────────────────────────

const mockUser: User = {
  id: 1,
  username: 'test_user',
  email: 'test@laprod.fr',
  profile_image: 'images/default_profile.png',
  roles: {
    is_admin: false,
    is_beatmaker: true,
    is_mix_engineer: false,
    is_artist: false,
    is_producer: false,
    is_mixmaster_engineer: false,
    is_certified_producer_arranger: false,
    mixmaster_sample_submitted: false,
  },
  user_type_selected: true,
  email_verified: true,
  notif_count: 0,
  upload_track_tokens: 2,
  topline_tokens: 0,
  is_premium: false,
  subscription_plan: 'free',
  preferred_tag_category: null,
};

const mockLoginSuccess = {
  success: true,
  feedback: { level: 'success', message: 'Connexion réussie' },
  data: {
    tokens: { access_token: 'jwt-access-token', refresh_token: 'jwt-refresh-token' },
    user: mockUser,
  },
};

const AUTH_URL = `${environment.apiUrl}/api/auth`;

// ── Suite de tests ────────────────────────────────────────────────────────────

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();

    TestBed.configureTestingModule({
      providers: [
        AuthService,
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([{ path: 'login', redirectTo: '' }, { path: '**', redirectTo: '' }]),
      ],
    });

    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  // -- Création --

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  // -- État initial --

  it('isLoggedIn() returns false when no user is stored', () => {
    expect(service.isLoggedIn()).toBe(false);
  });

  it('currentUser() returns null initially', () => {
    expect(service.currentUser()).toBeNull();
  });

  it('isAdmin() returns false for anonymous user', () => {
    expect(service.isAdmin()).toBe(false);
  });

  // -- login() --

  it('login() POSTs to /api/auth/login with correct payload', () => {
    service.login('user@test.com', 'password123', false).subscribe();

    const req = httpMock.expectOne(`${AUTH_URL}/login`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      identifier: 'user@test.com',
      password: 'password123',
      remember: false,
      captcha_token: null,
    });

    req.flush(mockLoginSuccess);
  });

  it('login() updates currentUser signal on success', () => {
    service.login('user@test.com', 'password123', false).subscribe();

    httpMock.expectOne(`${AUTH_URL}/login`).flush(mockLoginSuccess);

    expect(service.currentUser()).not.toBeNull();
    expect(service.currentUser()?.email).toBe('test@laprod.fr');
  });

  it('login() sets isLoggedIn() to true on success', () => {
    service.login('user@test.com', 'password123', false).subscribe();

    httpMock.expectOne(`${AUTH_URL}/login`).flush(mockLoginSuccess);

    expect(service.isLoggedIn()).toBe(true);
  });

  it('login() does not update currentUser on failure', () => {
    service.login('bad@test.com', 'wrongpass', false).subscribe({ error: () => {} });

    httpMock.expectOne(`${AUTH_URL}/login`).flush(
      { success: false, feedback: { level: 'warning', message: 'Identifiants incorrects.' } },
      { status: 401, statusText: 'Unauthorized' }
    );

    expect(service.currentUser()).toBeNull();
    expect(service.isLoggedIn()).toBe(false);
  });

  // -- logout() --

  it('logout() clears currentUser signal', () => {
    service.login('user@test.com', 'password123', false).subscribe();
    httpMock.expectOne(`${AUTH_URL}/login`).flush(mockLoginSuccess);
    expect(service.isLoggedIn()).toBe(true);

    service.logout().subscribe();
    httpMock.expectOne(`${AUTH_URL}/logout`).flush({ success: true });

    expect(service.isLoggedIn()).toBe(false);
    expect(service.currentUser()).toBeNull();
  });

  // -- me() --

  it('me() GETs /api/auth/me', () => {
    service.me().subscribe();

    const req = httpMock.expectOne(`${AUTH_URL}/me`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { user: mockUser } });
  });

  it('me() updates currentUser signal on success', () => {
    service.me().subscribe();

    httpMock.expectOne(`${AUTH_URL}/me`).flush({ success: true, data: { user: mockUser } });

    expect(service.currentUser()?.username).toBe('test_user');
  });

  // -- Computed signals --

  it('isBeatmaker() reflects user roles', () => {
    service.login('user@test.com', 'password123', false).subscribe();
    httpMock.expectOne(`${AUTH_URL}/login`).flush(mockLoginSuccess);

    expect(service.isBeatmaker()).toBe(true);
    expect(service.isAdmin()).toBe(false);
  });

  // -- navigateAfterOauth() — partagée entre OauthCallbackComponent (retour web
  // Google/Apple) et le flow natif Apple (LoginComponent/RegisterComponent) --

  describe('navigateAfterOauth()', () => {
    let router: Router;
    let navigateSpy: ReturnType<typeof vi.spyOn>;

    beforeEach(() => {
      router = TestBed.inject(Router);
      navigateSpy = vi.spyOn(router, 'navigate');
    });

    it("next='complete-profile' navigue avec le nom suggéré en query param", () => {
      service.navigateAfterOauth('complete-profile', 'Zoé');
      expect(navigateSpy).toHaveBeenCalledWith(['/complete-profile'], { queryParams: { name: 'Zoé' } });
    });

    it("next='complete-profile' sans nom suggéré n'ajoute pas de query param", () => {
      service.navigateAfterOauth('complete-profile', '');
      expect(navigateSpy).toHaveBeenCalledWith(['/complete-profile'], { queryParams: {} });
    });

    it("next='select-role' navigue vers /select-role", () => {
      service.navigateAfterOauth('select-role');
      expect(navigateSpy).toHaveBeenCalledWith(['/select-role']);
    });

    it("next='/' navigue vers l'accueil quand le profil est complet", () => {
      service.login('user@test.com', 'password123', false).subscribe();
      httpMock.expectOne(`${AUTH_URL}/login`).flush(mockLoginSuccess); // user_type_selected: true

      service.navigateAfterOauth('/');
      expect(navigateSpy).toHaveBeenCalledWith(['/']);
    });

    it("next='/' redirige vers /select-role si le profil est incomplet (filet de sécurité)", () => {
      const incompleteUser = { ...mockUser, user_type_selected: false };
      service.login('user@test.com', 'password123', false).subscribe();
      httpMock.expectOne(`${AUTH_URL}/login`).flush({ ...mockLoginSuccess, data: { ...mockLoginSuccess.data, user: incompleteUser } });

      service.navigateAfterOauth('/');
      expect(navigateSpy).toHaveBeenCalledWith(['/select-role']);
    });
  });
});
