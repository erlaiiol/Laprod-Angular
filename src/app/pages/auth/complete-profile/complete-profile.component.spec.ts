import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, ActivatedRoute } from '@angular/router';

import { CompleteProfileComponent } from './complete-profile.component';
import { environment } from '../../../../environments/environment';

const AUTH_URL = `${environment.apiUrl}/api/auth`;

const mockOauthUser = {
  id: 2,
  username: 'google_user',
  email: 'google@laprod.fr',
  profile_image: '',
  roles: {
    is_admin: false, is_beatmaker: false, is_mix_engineer: false,
    is_artist: false, is_mixmaster_engineer: false, is_certified_producer_arranger: false,
  },
  user_type_selected: false,
  email_verified: true,
  notif_count: 0,
  upload_track_tokens: 0,
  topline_tokens: 0,
  is_premium: false,
  subscription_plan: 'free' as const,
  preferred_tag_category: null,
};

function makeActivatedRoute(name: string | null) {
  return {
    provide: ActivatedRoute,
    useValue: {
      snapshot: {
        queryParamMap: { get: (key: string) => (key === 'name' ? name : null) },
      },
    },
  };
}

describe('CompleteProfileComponent', () => {
  let component: CompleteProfileComponent;
  let fixture: ComponentFixture<CompleteProfileComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CompleteProfileComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'select-role', redirectTo: '' },
          { path: '**', redirectTo: '' },
        ]),
        makeActivatedRoute('Jean'),
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CompleteProfileComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
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

  it('pre-fills signature from query param "name"', () => {
    expect(component.signature).toBe('Jean');
  });

  it('starts with loading false and no error', () => {
    expect(component.loading()).toBe(false);
    expect(component.error()).toBeNull();
  });

  it('leaves signature empty when query param "name" is absent', async () => {
    await TestBed.resetTestingModule();
    await TestBed.configureTestingModule({
      imports: [CompleteProfileComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        makeActivatedRoute(null),
      ],
    }).compileComponents();

    const f = TestBed.createComponent(CompleteProfileComponent);
    f.detectChanges();
    await f.whenStable();

    expect(f.componentInstance.signature).toBe('');

    TestBed.inject(HttpTestingController).verify();
  });

  // ── onSubmit() ──────────────────────────────────────────────────────────────

  describe('onSubmit()', () => {
    beforeEach(() => {
      component.username    = 'google_user';
      component.signature   = 'Jean Dupont';
      component.acceptTerms = true;
      localStorage.setItem('access_token', 'fake-oauth-token');
    });

    it('POSTs to /api/auth/complete-oauth-profile with correct payload', () => {
      component.onSubmit();

      const req = httpMock.expectOne(`${AUTH_URL}/complete-oauth-profile`);
      expect(req.request.method).toBe('POST');
      expect(req.request.body).toEqual({
        username:     'google_user',
        signature:    'Jean Dupont',
        accept_terms: true,
      });

      req.flush({
        success: true,
        data: {
          tokens: { access_token: 'new-token', refresh_token: 'rt' },
          user: mockOauthUser,
          next: 'select-role',
        },
      });
    });

    it('sets loading to true during request, false on success', () => {
      component.onSubmit();
      expect(component.loading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/complete-oauth-profile`).flush({
        success: true,
        data: {
          tokens: { access_token: 'new-token', refresh_token: 'rt' },
          user: mockOauthUser,
          next: '/',
        },
      });

      expect(component.loading()).toBe(false);
    });

    it('sets loading to false after HTTP error', () => {
      component.onSubmit();
      expect(component.loading()).toBe(true);

      httpMock.expectOne(`${AUTH_URL}/complete-oauth-profile`).flush(
        { success: false, feedback: { message: "Nom d'utilisateur déjà pris." } },
        { status: 400, statusText: 'Bad Request' },
      );

      expect(component.loading()).toBe(false);
    });

    it('sets error on HTTP error response', () => {
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/complete-oauth-profile`).flush(
        { success: false, feedback: { message: "Nom d'utilisateur déjà pris." } },
        { status: 400, statusText: 'Bad Request' },
      );

      expect(component.error()).toBe("Nom d'utilisateur déjà pris.");
    });

    it('sets error on success=false without redirecting', () => {
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/complete-oauth-profile`).flush({
        success: false,
        feedback: { message: 'Signature requise.' },
      });

      expect(component.error()).toBe('Signature requise.');
    });

    it('stores tokens in localStorage on success', () => {
      component.onSubmit();

      httpMock.expectOne(`${AUTH_URL}/complete-oauth-profile`).flush({
        success: true,
        data: {
          tokens: { access_token: 'brand-new-access', refresh_token: 'brand-new-refresh' },
          user: mockOauthUser,
          next: '/',
        },
      });

      expect(localStorage.getItem('access_token')).toBe('brand-new-access');
      expect(localStorage.getItem('refresh_token')).toBe('brand-new-refresh');
    });
  });
});
