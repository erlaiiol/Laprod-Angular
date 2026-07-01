import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { vi } from 'vitest';

import { LoginComponent } from './login.component';
import { environment } from '../../../../environments/environment';

const AUTH_URL = `${environment.apiUrl}/api/auth`;

const mockUser = (userTypeSelected = true) => ({
  id: 1,
  username: 'test_user',
  email: 'test@laprod.fr',
  profile_image: '',
  roles: {
    is_admin: false, is_beatmaker: true, is_mix_engineer: false,
    is_artist: false, is_mixmaster_engineer: false, is_certified_producer_arranger: false,
  },
  user_type_selected: userTypeSelected,
  email_verified: true,
  notif_count: 0,
  upload_track_tokens: 2,
  topline_tokens: 0,
  is_premium: false,
  subscription_plan: 'free' as const,
  preferred_tag_category: null,
});

const loginSuccess = (userTypeSelected = true, code?: string) => ({
  success: true,
  feedback: { level: 'info', message: 'Bienvenue !' },
  ...(code ? { code } : {}),
  data: {
    tokens: { access_token: 'at', refresh_token: 'rt' },
    user: mockUser(userTypeSelected),
  },
});

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let httpMock: HttpTestingController;
  let router: Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: '',           redirectTo: 'home', pathMatch: 'full' },
          { path: 'home',       redirectTo: '' },
          { path: 'select-role', redirectTo: '' },
          { path: 'login',       redirectTo: '' },
          { path: '**',          redirectTo: '' },
        ]),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    await fixture.whenStable();
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  // ── État initial ────────────────────────────────────────────────────────────

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('starts in clean state', () => {
    expect(component.loading()).toBe(false);
    expect(component.error()).toBeNull();
    expect(component.pendingEmail()).toBeNull();
    expect(component.resendSuccess()).toBe(false);
    expect(component.showPasswordSetLink()).toBe(false);
  });

  // ── onSubmit() ──────────────────────────────────────────────────────────────

  describe('onSubmit()', () => {
    beforeEach(() => {
      component.identifier = 'test@laprod.fr';
      component.password   = 'TestPass123!';
    });

    it('POSTs to /api/auth/login with correct payload', () => {
      component.remember = true;
      component.onSubmit();

      const req = httpMock.expectOne(`${AUTH_URL}/login`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({
        identifier: 'test@laprod.fr',
        password:   'TestPass123!',
        remember:   true,
      });

      req.flush(loginSuccess());
    });

    it('navigates to / after successful login with role already selected', () => {
      const spy = vi.spyOn(router, 'navigate');
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/login`).flush(loginSuccess(true));

      expect(spy).toHaveBeenCalledWith(['/']);
    });

    it('navigates to /select-role when SHOW_SELECT_ROLE code is returned', () => {
      const spy = vi.spyOn(router, 'navigate');
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/login`).flush(loginSuccess(false, 'SHOW_SELECT_ROLE'));

      expect(spy).toHaveBeenCalledWith(['/select-role']);
    });

    it('navigates to /select-role when user.user_type_selected is false (safety net)', () => {
      const spy = vi.spyOn(router, 'navigate');
      component.onSubmit();

      // Backend retourne succès sans code explicite mais user sans rôle
      httpMock.expectOne(`${AUTH_URL}/login`).flush(loginSuccess(false));

      expect(spy).toHaveBeenCalledWith(['/select-role']);
    });

    it('sets error message on 401', () => {
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/login`).flush(
        { success: false, feedback: { message: 'Identifiants incorrects.' } },
        { status: 401, statusText: 'Unauthorized' },
      );

      expect(component.error()).toBe('Identifiants incorrects.');
    });

    it('shows resend-email panel on SHOW_EMAIL_CONFIRMATION_LINK code', () => {
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/login`).flush(
        { success: false, code: 'SHOW_EMAIL_CONFIRMATION_LINK',
          data: { confirmation_email: 'test@laprod.fr' } },
        { status: 403, statusText: 'Forbidden' },
      );

      expect(component.pendingEmail()).toBe('test@laprod.fr');
      expect(component.error()).toBeNull();
    });

    it('shows password-set link on SHOW_PASSWORD_SET_LINK code', () => {
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/login`).flush(
        { success: false, code: 'SHOW_PASSWORD_SET_LINK',
          data: { password_email: 'test@laprod.fr' } },
        { status: 401, statusText: 'Unauthorized' },
      );

      expect(component.showPasswordSetLink()).toBe(true);
      expect(component.passwordEmail()).toBe('test@laprod.fr');
    });

    it('sets loading to true during request, false on success', () => {
      component.onSubmit();
      expect(component.loading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/login`).flush(loginSuccess());

      expect(component.loading()).toBe(false);
    });

    it('sets loading to false after error', () => {
      component.onSubmit();
      expect(component.loading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/login`).flush(
        { success: false, feedback: { message: 'Erreur.' } },
        { status: 401, statusText: 'Unauthorized' },
      );

      expect(component.loading()).toBe(false);
    });

    it('clears previous error at start of new submit', () => {
      component.error.set('Ancienne erreur');
      component.onSubmit();

      expect(component.error()).toBeNull();

      httpMock.expectOne(`${AUTH_URL}/login`).flush(loginSuccess());
    });
  });

  // ── resendVerification() ────────────────────────────────────────────────────

  describe('resendVerification()', () => {
    it('falls back to identifier when pendingEmail is null', () => {
      component.identifier = 'test@laprod.fr';
      component.resendVerification();

      const req = httpMock.expectOne(`${AUTH_URL}/resend-verification`);
      req.flush({ success: true });
    });

    it('uses pendingEmail when available', () => {
      component.identifier = 'username';
      component.pendingEmail.set('real@laprod.fr');
      component.resendVerification();

      const req = httpMock.expectOne(`${AUTH_URL}/resend-verification`);
      expect(req.request.body).toEqual({ identifier: 'real@laprod.fr' });
      req.flush({ success: true });
    });

    it('sets resendSuccess to true on success', () => {
      component.pendingEmail.set('test@laprod.fr');
      component.resendVerification();

      httpMock.expectOne(`${AUTH_URL}/resend-verification`).flush({ success: true });

      expect(component.resendSuccess()).toBe(true);
    });

    it('sets error on resend failure', () => {
      component.pendingEmail.set('test@laprod.fr');
      component.resendVerification();

      httpMock.expectOne(`${AUTH_URL}/resend-verification`).flush(
        { success: false },
        { status: 500, statusText: 'Server Error' },
      );

      expect(component.error()).toBe('Erreur lors du renvoi. Réessayez.');
    });
  });
});
