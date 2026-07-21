import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { vi } from 'vitest';

import { SelectRoleComponent } from './select-role.component';
import { environment } from '../../../../environments/environment';

const SELECT_ROLE_URL = `${environment.apiUrl}/api/auth/select-role`;

const mockUser = (isMix = false, isBeatmaker = false, isArtist = false) => ({
  id: 1,
  username: 'test_user',
  email: 'test@laprod.fr',
  profile_image: '',
  roles: {
    is_admin: false,
    is_beatmaker: isBeatmaker,
    is_mix_engineer: isMix,
    is_artist: isArtist,
    is_mixmaster_engineer: isMix,
    is_certified_producer_arranger: false,
  },
  user_type_selected: true,
  email_verified: true,
  notif_count: 0,
  upload_track_tokens: 2,
  topline_tokens: 0,
  is_premium: false,
  subscription_plan: 'free' as const,
  preferred_tag_category: null,
});

describe('SelectRoleComponent', () => {
  let component: SelectRoleComponent;
  let fixture: ComponentFixture<SelectRoleComponent>;
  let httpMock: HttpTestingController;
  let router: Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SelectRoleComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: '',              redirectTo: 'home',  pathMatch: 'full' },
          { path: 'home',          redirectTo: '' },
          { path: 'submit-sample', redirectTo: '' },
          { path: '**',            redirectTo: '' },
        ]),
      ],
    }).compileComponents();

    fixture   = TestBed.createComponent(SelectRoleComponent);
    component = fixture.componentInstance;
    httpMock  = TestBed.inject(HttpTestingController);
    router    = TestBed.inject(Router);
    fixture.detectChanges();
    await fixture.whenStable();
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
  });

  // ── État initial ─────────────────────────────────────────────────────────────

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('starts with no role selected', () => {
    expect(component.isArtist()).toBe(false);
    expect(component.isBeatmaker()).toBe(false);
    expect(component.isMixEngineer()).toBe(false);
    expect(component.hasSelection()).toBe(false);
  });

  it('submit button is disabled when no role is selected', () => {
    const btn = fixture.nativeElement.querySelector('button.btn-submit') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('does not show error element initially', () => {
    const err = fixture.nativeElement.querySelector('.role-error');
    expect(err).toBeNull();
  });

  // ── Interactions DOM — sélection de rôle ─────────────────────────────────────

  it('clicking "Interprete" adds .selected class to its button', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[0] as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(component.isArtist()).toBe(true);
    expect((buttons[0] as HTMLButtonElement).classList.contains('selected')).toBe(true);
  });

  it('clicking "Beatmaker" adds .selected class to its button', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[1] as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(component.isBeatmaker()).toBe(true);
    expect((buttons[1] as HTMLButtonElement).classList.contains('selected')).toBe(true);
  });

  it('clicking "Mix Engineer" adds .selected class to its button', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[2] as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(component.isMixEngineer()).toBe(true);
    expect((buttons[2] as HTMLButtonElement).classList.contains('selected')).toBe(true);
  });

  it('clicking "Producteur" adds .selected class to its button', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[3] as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(component.isProducer()).toBe(true);
    expect((buttons[3] as HTMLButtonElement).classList.contains('selected')).toBe(true);
  });

  it('clicking the same button twice deselects the role', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(component.isArtist()).toBe(true);

    (buttons[0] as HTMLButtonElement).click();
    fixture.detectChanges();
    expect(component.isArtist()).toBe(false);
    expect((buttons[0] as HTMLButtonElement).classList.contains('selected')).toBe(false);
  });

  it('multiple roles can be selected simultaneously', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[0] as HTMLButtonElement).click();
    (buttons[1] as HTMLButtonElement).click();
    fixture.detectChanges();

    expect(component.isArtist()).toBe(true);
    expect(component.isBeatmaker()).toBe(true);
    expect((buttons[0] as HTMLButtonElement).classList.contains('selected')).toBe(true);
    expect((buttons[1] as HTMLButtonElement).classList.contains('selected')).toBe(true);
  });

  it('submit button becomes enabled after selecting a role', () => {
    const buttons = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (buttons[0] as HTMLButtonElement).click();
    fixture.detectChanges();

    const submitBtn = fixture.nativeElement.querySelector('button.btn-submit') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(false);
  });

  // ── Validation — soumission sans sélection ───────────────────────────────────

  it('shows .role-error when submitting with no role selected', () => {
    component.onSubmit();
    fixture.detectChanges();

    const errEl = fixture.nativeElement.querySelector('.role-error') as HTMLElement;
    expect(errEl).toBeTruthy();
    expect(errEl.textContent).toContain('au moins un rôle');
  });

  it('does not call the API when no role is selected', () => {
    component.onSubmit();
    httpMock.expectNone(SELECT_ROLE_URL);
  });

  // ── Navigation après succès ───────────────────────────────────────────────────

  it('navigates to / after selecting Beatmaker and submitting', () => {
    const spy = vi.spyOn(router, 'navigate');
    component.toggle('beatmaker');
    component.onSubmit();

    httpMock.expectOne(SELECT_ROLE_URL).flush({
      success: true,
      data: { user: mockUser(false, true, false), next: '/' },
    });

    expect(spy).toHaveBeenCalledWith(['/']);
  });

  it('navigates to /submit-sample after selecting Mix Engineer and submitting', () => {
    const spy = vi.spyOn(router, 'navigate');
    component.toggle('mix');
    component.onSubmit();

    httpMock.expectOne(SELECT_ROLE_URL).flush({
      success: true,
      data: { user: mockUser(true, false, false), next: 'submit-sample' },
    });

    expect(spy).toHaveBeenCalledWith(['/submit-sample']);
  });

  it('navigates to / after selecting Artiste and submitting', () => {
    const spy = vi.spyOn(router, 'navigate');
    component.toggle('artist');
    component.onSubmit();

    httpMock.expectOne(SELECT_ROLE_URL).flush({
      success: true,
      data: { user: mockUser(false, false, true), next: '/' },
    });

    expect(spy).toHaveBeenCalledWith(['/']);
  });

  // ── Payload HTTP ──────────────────────────────────────────────────────────────

  it('sends correct payload with all four flags', () => {
    component.toggle('artist');
    component.toggle('beatmaker');
    component.toggle('mix');
    component.toggle('producer');
    component.onSubmit();

    const req = httpMock.expectOne(SELECT_ROLE_URL);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({
      is_artist:       true,
      is_beatmaker:    true,
      is_mix_engineer: true,
      is_producer:     true,
    });

    req.flush({ success: true, data: { user: mockUser(true, true, true), next: '/' } });
  });

  // ── États loading et erreur ───────────────────────────────────────────────────

  it('sets loading to true during request, false on success', () => {
    component.toggle('artist');
    component.onSubmit();
    expect(component.loading()).toBe(true);

    httpMock.expectOne(SELECT_ROLE_URL).flush({
      success: true,
      data: { user: mockUser(false, false, true), next: '/' },
    });

    expect(component.loading()).toBe(false);
  });

  it('sets error and stops loading on API error', () => {
    component.toggle('artist');
    component.onSubmit();

    httpMock.expectOne(SELECT_ROLE_URL).flush(
      { success: false, feedback: { message: 'Erreur serveur.' } },
      { status: 500, statusText: 'Server Error' },
    );

    expect(component.loading()).toBe(false);
    expect(component.error()).toContain('Erreur');
  });
});
