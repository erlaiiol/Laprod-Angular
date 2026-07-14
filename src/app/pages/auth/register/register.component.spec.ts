import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { RegisterComponent } from './register.component';
import { environment } from '../../../../environments/environment';

const AUTH_URL = `${environment.apiUrl}/api/auth`;

describe('RegisterComponent', () => {
  let component: RegisterComponent;
  let fixture: ComponentFixture<RegisterComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RegisterComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(RegisterComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
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

  it('starts with all signals in clean state', () => {
    expect(component.loading()).toBe(false);
    expect(component.error()).toBeNull();
    expect(component.confirmedEmail()).toBeNull();
    expect(component.pendingEmail()).toBeNull();
    expect(component.resendSuccess()).toBe(false);
  });

  // ── onSubmit() ──────────────────────────────────────────────────────────────

  describe('onSubmit()', () => {
    function fillValidForm(comp: RegisterComponent): void {
      comp.username        = 'newuser';
      comp.email           = 'new@laprod.fr';
      comp.password        = 'TestPass123!';
      comp.passwordConfirm = 'TestPass123!';
      comp.signature       = 'Ma Signature';
      comp.acceptTerms     = true;
    }

    it('POSTs to /api/auth/register with the correct payload', () => {
      fillValidForm(component);
      component.onSubmit();

      const req = httpMock.expectOne(`${AUTH_URL}/register`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({
        username:         'newuser',
        password:         'TestPass123!',
        password_confirm: 'TestPass123!',
        email:            'new@laprod.fr',
        signature:        'Ma Signature',
        accept_terms:     true,
        captcha_token:    null,
      });

      req.flush({ success: true, data: { user: { username: 'newuser', email: 'new@laprod.fr' } } });
    });

    it('sets confirmedEmail on success', () => {
      fillValidForm(component);
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/register`).flush({
        success: true,
        data: { user: { username: 'newuser', email: 'new@laprod.fr' } },
      });

      expect(component.confirmedEmail()).toBe('new@laprod.fr');
      expect(component.error()).toBeNull();
    });

    it('falls back to component.email if response has no user.email', () => {
      fillValidForm(component);
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/register`).flush({
        success: true,
        data: { user: null },
      });

      expect(component.confirmedEmail()).toBe('new@laprod.fr');
    });

    it('sets loading to true during request, false after success', () => {
      fillValidForm(component);
      component.onSubmit();
      expect(component.loading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/register`).flush({
        success: true,
        data: { user: { username: 'newuser', email: 'new@laprod.fr' } },
      });

      expect(component.loading()).toBe(false);
    });

    it('sets loading to false after HTTP error', () => {
      fillValidForm(component);
      component.onSubmit();
      expect(component.loading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/register`).flush(
        { success: false, feedback: { message: 'Erreur.' } },
        { status: 400, statusText: 'Bad Request' },
      );

      expect(component.loading()).toBe(false);
    });

    it('sets error message on generic HTTP error', () => {
      fillValidForm(component);
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/register`).flush(
        { success: false, feedback: { message: 'Email déjà utilisé.' } },
        { status: 400, statusText: 'Bad Request' },
      );

      expect(component.error()).toBe('Email déjà utilisé.');
      expect(component.confirmedEmail()).toBeNull();
    });

    it('sets pendingEmail on PENDING_EMAIL_VERIFICATION code', () => {
      fillValidForm(component);
      component.email = 'pending@laprod.fr';
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/register`).flush(
        { success: false, code: 'PENDING_EMAIL_VERIFICATION', data: { email: 'pending@laprod.fr' } },
        { status: 409, statusText: 'Conflict' },
      );

      expect(component.pendingEmail()).toBe('pending@laprod.fr');
      expect(component.error()).toBeNull();
    });

    it('sets pendingEmail on SEND_CONFIRM_EMAIL_MESSAGE code', () => {
      fillValidForm(component);
      component.email = 'bounce@laprod.fr';
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/register`).flush(
        { success: false, code: 'SEND_CONFIRM_EMAIL_MESSAGE', data: { user: { email: 'bounce@laprod.fr' } } },
        { status: 500, statusText: 'Server Error' },
      );

      expect(component.pendingEmail()).toBe('bounce@laprod.fr');
    });

    it('clears pendingEmail at the start of a new submit', () => {
      component.pendingEmail.set('stale@laprod.fr');
      fillValidForm(component);
      component.onSubmit();

      expect(component.pendingEmail()).toBeNull();

      httpMock.expectOne(`${AUTH_URL}/register`).flush({
        success: true,
        data: { user: { username: 'newuser', email: 'new@laprod.fr' } },
      });
    });
  });

  // ── resendVerification() ────────────────────────────────────────────────────

  describe('resendVerification()', () => {
    it('does nothing if pendingEmail is null', () => {
      component.resendVerification();
      httpMock.expectNone(`${AUTH_URL}/resend-verification`);
    });

    it('does nothing if resendLoading is already true', () => {
      component.pendingEmail.set('pending@laprod.fr');
      component.resendLoading.set(true);
      component.resendVerification();
      httpMock.expectNone(`${AUTH_URL}/resend-verification`);
    });

    it('POSTs to resend-verification with pendingEmail as identifier', () => {
      component.pendingEmail.set('pending@laprod.fr');
      component.resendVerification();

      const req = httpMock.expectOne(`${AUTH_URL}/resend-verification`);
      expect(req.request.method).toBe('POST');
      req.flush({ success: true });
    });

    it('sets resendSuccess to true on success', () => {
      component.pendingEmail.set('pending@laprod.fr');
      component.resendVerification();

      httpMock.expectOne(`${AUTH_URL}/resend-verification`).flush({ success: true });

      expect(component.resendSuccess()).toBe(true);
    });

    it('sets error on resend failure', () => {
      component.pendingEmail.set('pending@laprod.fr');
      component.resendVerification();

      httpMock.expectOne(`${AUTH_URL}/resend-verification`).flush(
        { success: false },
        { status: 500, statusText: 'Server Error' },
      );

      expect(component.error()).toBe('Erreur lors du renvoi. Réessayez.');
      expect(component.resendSuccess()).toBe(false);
    });

    it('resets resendSuccess at the start of a new resend', () => {
      component.pendingEmail.set('pending@laprod.fr');
      component.resendSuccess.set(true);
      component.resendVerification();

      expect(component.resendSuccess()).toBe(false);

      httpMock.expectOne(`${AUTH_URL}/resend-verification`).flush({ success: true });
    });

    it('sets loading false after resend completes', () => {
      component.pendingEmail.set('pending@laprod.fr');
      component.resendVerification();
      expect(component.resendLoading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/resend-verification`).flush({ success: true });

      expect(component.resendLoading()).toBe(false);
    });
  });
});
