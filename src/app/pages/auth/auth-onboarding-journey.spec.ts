/**
 * Tests de parcours utilisateur - Inscription et 1ere connexion
 *
 * Parcours classique :
 *   Register -> email envoye (.confirm-panel)
 *   Verify-email -> token valide -> state='success' -> lien /login
 *   Login -> 1ere connexion -> SHOW_SELECT_ROLE -> /select-role
 *   Select-role -> Beatmaker -> navigate('/') ou Mix -> navigate('/submit-sample')
 *
 * Parcours OAuth (Google) :
 *   complete-profile -> /select-role -> meme comportement
 */

import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, ActivatedRoute, Router } from '@angular/router';
import { vi } from 'vitest';

import { RegisterComponent }        from './register/register.component';
import { VerifyEmailComponent }     from './verify-email/verify-email.component';
import { LoginComponent }           from './login/login.component';
import { SelectRoleComponent }      from './select-role/select-role.component';
import { CompleteProfileComponent } from './complete-profile/complete-profile.component';
import { environment }              from '../../../environments/environment';

const API = environment.apiUrl;

function makeRoute(params: Record<string, string | null> = {}) {
  return {
    provide: ActivatedRoute,
    useValue: {
      snapshot: { queryParamMap: { get: (k: string) => params[k] ?? null } },
    },
  };
}

const BASE_USER = {
  id: 1,
  username: 'testuser',
  email: 'test@laprod.fr',
  profile_image: '',
  roles: {
    is_admin: false, is_beatmaker: false, is_mix_engineer: false,
    is_artist: false, is_producer: false, is_mixmaster_engineer: false, is_certified_producer_arranger: false,
  },
  user_type_selected: false,
  email_verified: true,
  notif_count: 0,
  upload_track_tokens: 2,
  topline_tokens: 0,
  is_premium: false,
  subscription_plan: 'free' as const,
  preferred_tag_category: null,
};

// ─────────────────────────────────────────────────────────────────────────────
// ETAPE 1 - Inscription
// ─────────────────────────────────────────────────────────────────────────────

describe('Parcours 1 - Inscription classique', () => {

  let fixture:   ComponentFixture<RegisterComponent>;
  let component: RegisterComponent;
  let httpMock:  HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [RegisterComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login',    redirectTo: '' },
          { path: 'register', redirectTo: '' },
          { path: '**',       redirectTo: '' },
        ]),
      ],
    }).compileComponents();

    fixture   = TestBed.createComponent(RegisterComponent);
    component = fixture.componentInstance;
    httpMock  = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    await fixture.whenStable();
  });

  afterEach(() => { httpMock.verify(); localStorage.clear(); });

  it('affiche le formulaire au depart', () => {
    const form = fixture.nativeElement.querySelector('form');
    expect(form).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.confirm-panel')).toBeNull();
  });

  it('affiche .confirm-panel avec email apres soumission reussie', () => {
    component.username        = 'testuser';
    component.email           = 'test@laprod.fr';
    component.password        = 'TestPass123!';
    component.passwordConfirm = 'TestPass123!';
    component.signature       = 'Test User';
    component.acceptTerms     = true;

    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/register`).flush({
      success: true,
      code: 'SEND_CONFIRM_EMAIL_MESSAGE',
      feedback: { level: 'info', message: 'Email envoye.' },
      data: { user: { username: 'testuser', email: 'test@laprod.fr' } },
    });

    fixture.detectChanges();

    expect(component.confirmedEmail()).toBe('test@laprod.fr');
    const panel = fixture.nativeElement.querySelector('.confirm-panel') as HTMLElement;
    expect(panel).toBeTruthy();
    expect(panel.textContent).toContain('test@laprod.fr');
  });

  it('masque le formulaire apres confirmation (confirmedEmail set)', () => {
    component.onSubmit();
    httpMock.expectOne(`${API}/api/auth/register`).flush({
      success: true,
      code: 'SEND_CONFIRM_EMAIL_MESSAGE',
      feedback: { level: 'info', message: '' },
      data: { user: { username: 'testuser', email: 'test@laprod.fr' } },
    });
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('form')).toBeNull();
  });

  it('affiche .alert-box.alert-danger en cas erreur', () => {
    component.username        = 'testuser';
    component.email           = 'taken@laprod.fr';
    component.password        = 'TestPass123!';
    component.passwordConfirm = 'TestPass123!';
    component.signature       = 'Test';
    component.acceptTerms     = true;
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/register`).flush(
      { success: false, feedback: { level: 'error', message: 'Cet email est deja utilise.' } },
      { status: 400, statusText: 'Bad Request' },
    );

    fixture.detectChanges();

    const errEl = fixture.nativeElement.querySelector('.alert-box.alert-danger') as HTMLElement;
    expect(errEl).toBeTruthy();
    expect(errEl.textContent).toContain('deja utilise');
  });

  it('desactive le bouton pendant le chargement', () => {
    component.username = 'u'; component.email = 'e@e.com'; component.password = 'p';
    component.onSubmit();

    fixture.detectChanges();
    const btn = fixture.nativeElement.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);

    httpMock.expectOne(`${API}/api/auth/register`).flush({
      success: true, code: 'SEND_CONFIRM_EMAIL_MESSAGE',
      feedback: { level: 'info', message: '' },
      data: { user: { username: 'u', email: 'e@e.com' } },
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// ETAPE 2 - Verification email
// ─────────────────────────────────────────────────────────────────────────────

describe('Parcours 2 - Verification du lien email', () => {

  afterEach(() => TestBed.resetTestingModule());

  async function setupVerify(token: string | null) {
    await TestBed.configureTestingModule({
      imports: [VerifyEmailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'login',    redirectTo: '' },
          { path: 'register', redirectTo: '' },
          { path: '**',       redirectTo: '' },
        ]),
        makeRoute(token ? { token } : {}),
      ],
    }).compileComponents();

    const fix  = TestBed.createComponent(VerifyEmailComponent);
    const http = TestBed.inject(HttpTestingController);
    return { fix, comp: fix.componentInstance, http };
  }

  it('etat initial = "loading" quand un token est present', async () => {
    const { fix, comp, http } = await setupVerify('some-token');
    fix.detectChanges();

    expect(comp.state()).toBe('loading');
    http.expectOne(`${API}/api/auth/verify-email`).flush({ success: true, feedback: { message: 'OK' } });
  });

  it('succes -> h2 "Email verifie !" + lien /login visible dans le DOM', async () => {
    const { fix, comp, http } = await setupVerify('valid-token');
    fix.detectChanges();

    http.expectOne(`${API}/api/auth/verify-email`).flush({
      success: true,
      feedback: { message: 'Email verifie ! Vous pouvez maintenant vous connecter.' },
    });
    fix.detectChanges();

    expect(comp.state()).toBe('success');
    const h2 = fix.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2.textContent?.trim()).toBe('Email vérifié !');
    expect(fix.nativeElement.querySelector('a[routerLink="/login"]')).toBeTruthy();
  });

  it('token expire -> h2 "Lien expire" + lien /register visible', async () => {
    const { fix, comp, http } = await setupVerify('expired-token');
    fix.detectChanges();

    http.expectOne(`${API}/api/auth/verify-email`).flush(
      { success: false, code: 'TOKEN_EXPIRED', feedback: { message: 'Lien expire.' } },
      { status: 400, statusText: 'Bad Request' },
    );
    fix.detectChanges();

    expect(comp.state()).toBe('expired');
    const h2 = fix.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2.textContent?.trim()).toBe('Lien expiré');
    expect(fix.nativeElement.querySelector('a[routerLink="/register"]')).toBeTruthy();
  });

  it('token absent -> h2 "Lien invalide" sans appel HTTP', async () => {
    const { fix, comp, http } = await setupVerify(null);
    fix.detectChanges();

    expect(comp.state()).toBe('error');
    const h2 = fix.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2.textContent?.trim()).toBe('Lien invalide');
    http.expectNone(`${API}/api/auth/verify-email`);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// ETAPE 3 - 1ere connexion (regression bug: SHOW_SELECT_ROLE -> /select-role)
// ─────────────────────────────────────────────────────────────────────────────

describe('Parcours 3 - 1ere connexion apres verification email', () => {

  let fixture:   ComponentFixture<LoginComponent>;
  let component: LoginComponent;
  let httpMock:  HttpTestingController;
  let router:    Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [LoginComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: '',            redirectTo: 'home', pathMatch: 'full' },
          { path: 'home',        redirectTo: '' },
          { path: 'select-role', redirectTo: '' },
          { path: '**',          redirectTo: '' },
        ]),
      ],
    }).compileComponents();

    fixture   = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    httpMock  = TestBed.inject(HttpTestingController);
    router    = TestBed.inject(Router);
    await fixture.whenStable();
  });

  afterEach(() => { httpMock.verify(); localStorage.clear(); });

  // TEST CRITIQUE - Regression du bug :
  // Avant le fix, `return;` empechait la navigation quand le code etait SHOW_SELECT_ROLE.
  it('[REGRESSION] SHOW_SELECT_ROLE -> navigation vers /select-role (jamais vers /)', () => {
    const spy = vi.spyOn(router, 'navigate');

    component.identifier = 'test@laprod.fr';
    component.password   = 'TestPass123!';
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/login`).flush({
      success: true,
      code: 'SHOW_SELECT_ROLE',
      feedback: { level: 'info', message: 'Choisissez votre role.' },
      data: {
        tokens: { access_token: 'at', refresh_token: 'rt' },
        user: { ...BASE_USER, user_type_selected: false },
      },
    });

    expect(spy).toHaveBeenCalledWith(['/select-role']);
    expect(spy).not.toHaveBeenCalledWith(['/']);
  });

  it('user_type_selected=false sans code explicite -> /select-role', () => {
    const spy = vi.spyOn(router, 'navigate');

    component.identifier = 'test@laprod.fr';
    component.password   = 'TestPass123!';
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/login`).flush({
      success: true,
      feedback: { level: 'info', message: 'Bienvenue !' },
      data: {
        tokens: { access_token: 'at', refresh_token: 'rt' },
        user: { ...BASE_USER, user_type_selected: false },
      },
    });

    expect(spy).toHaveBeenCalledWith(['/select-role']);
  });

  it('user avec role deja selectionne -> navigation vers /', () => {
    const spy = vi.spyOn(router, 'navigate');

    component.identifier = 'test@laprod.fr';
    component.password   = 'TestPass123!';
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/login`).flush({
      success: true,
      feedback: { level: 'info', message: 'Bienvenue !' },
      data: {
        tokens: { access_token: 'at', refresh_token: 'rt' },
        user: { ...BASE_USER, user_type_selected: true },
      },
    });

    expect(spy).toHaveBeenCalledWith(['/']);
    expect(spy).not.toHaveBeenCalledWith(['/select-role']);
  });

  it('affiche .pending-email-panel quand SHOW_EMAIL_CONFIRMATION_LINK', () => {
    component.identifier = 'test@laprod.fr';
    component.password   = 'WrongPass!';
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/login`).flush(
      {
        success: false,
        code: 'SHOW_EMAIL_CONFIRMATION_LINK',
        data: { confirmation_email: 'test@laprod.fr' },
      },
      { status: 403, statusText: 'Forbidden' },
    );
    fixture.detectChanges();

    expect(component.pendingEmail()).toBe('test@laprod.fr');
    const panel = fixture.nativeElement.querySelector('.pending-email-panel');
    expect(panel).toBeTruthy();
    expect(fixture.nativeElement.querySelector('.alert-box.alert-danger')).toBeNull();
  });

  it('affiche .alert-box.alert-danger sur identifiants incorrects', () => {
    component.identifier = 'test@laprod.fr';
    component.password   = 'WrongPass!';
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/login`).flush(
      { success: false, feedback: { level: 'error', message: 'Identifiants incorrects.' } },
      { status: 401, statusText: 'Unauthorized' },
    );
    fixture.detectChanges();

    const err = fixture.nativeElement.querySelector('.alert-box.alert-danger') as HTMLElement;
    expect(err).toBeTruthy();
    expect(err.textContent).toContain('Identifiants incorrects.');
  });

  it('le bouton submit est desactive pendant le chargement', () => {
    component.identifier = 'test@laprod.fr';
    component.password   = 'TestPass123!';
    component.onSubmit();
    fixture.detectChanges();

    const btn = fixture.nativeElement.querySelector('button[type="submit"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);

    httpMock.expectOne(`${API}/api/auth/login`).flush({
      success: true,
      feedback: { level: 'info', message: '' },
      data: { tokens: { access_token: 'at', refresh_token: 'rt' }, user: BASE_USER },
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// ETAPE 4 - Selection du role
// ─────────────────────────────────────────────────────────────────────────────

describe('Parcours 4 - Selection du role', () => {

  let fixture:   ComponentFixture<SelectRoleComponent>;
  let component: SelectRoleComponent;
  let httpMock:  HttpTestingController;
  let router:    Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [SelectRoleComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: '',              redirectTo: 'home', pathMatch: 'full' },
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

  afterEach(() => { httpMock.verify(); localStorage.clear(); });

  it('le bouton "Valider mon profil" est desactive avant toute selection', () => {
    const btn = fixture.nativeElement.querySelector('button.btn-submit') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it('un clic sur "Beatmaker" active .selected et active le bouton submit', () => {
    const roleBtns = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (roleBtns[1] as HTMLButtonElement).click();
    fixture.detectChanges();

    expect((roleBtns[1] as HTMLButtonElement).classList.contains('selected')).toBe(true);
    const submitBtn = fixture.nativeElement.querySelector('button.btn-submit') as HTMLButtonElement;
    expect(submitBtn.disabled).toBe(false);
  });

  it('Beatmaker -> navigate(["/"])', () => {
    const spy = vi.spyOn(router, 'navigate');
    component.toggle('beatmaker');
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/select-role`).flush({
      success: true,
      data: {
        user: { ...BASE_USER, user_type_selected: true, roles: { ...BASE_USER.roles, is_beatmaker: true } },
        next: '/',
      },
    });

    expect(spy).toHaveBeenCalledWith(['/']);
  });

  it('Mix Engineer -> navigate(["/submit-sample"])', () => {
    const spy = vi.spyOn(router, 'navigate');
    component.toggle('mix');
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/select-role`).flush({
      success: true,
      data: {
        user: { ...BASE_USER, user_type_selected: true, roles: { ...BASE_USER.roles, is_mix_engineer: true } },
        next: 'submit-sample',
      },
    });

    expect(spy).toHaveBeenCalledWith(['/submit-sample']);
  });

  it('soumission sans selection -> .role-error visible', () => {
    component.onSubmit();
    fixture.detectChanges();

    const errEl = fixture.nativeElement.querySelector('.role-error') as HTMLElement;
    expect(errEl).toBeTruthy();
    expect(errEl.textContent).toContain('au moins un');
  });

  it('double-clic deselectionne le role', () => {
    const btns = fixture.nativeElement.querySelectorAll('button.role-btn') as NodeListOf<HTMLButtonElement>;
    (btns[0] as HTMLButtonElement).click(); fixture.detectChanges();
    expect(component.isArtist()).toBe(true);

    (btns[0] as HTMLButtonElement).click(); fixture.detectChanges();
    expect(component.isArtist()).toBe(false);
    expect((btns[0] as HTMLButtonElement).classList.contains('selected')).toBe(false);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Parcours OAuth - complete-profile avant select-role
// ─────────────────────────────────────────────────────────────────────────────

describe('Parcours OAuth - Completion du profil Google', () => {

  let fixture:   ComponentFixture<CompleteProfileComponent>;
  let component: CompleteProfileComponent;
  let httpMock:  HttpTestingController;
  let router:    Router;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [CompleteProfileComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([
          { path: 'select-role', redirectTo: '' },
          { path: '**',          redirectTo: '' },
        ]),
        makeRoute({ name: 'Jean' }),
      ],
    }).compileComponents();

    fixture   = TestBed.createComponent(CompleteProfileComponent);
    component = fixture.componentInstance;
    httpMock  = TestBed.inject(HttpTestingController);
    router    = TestBed.inject(Router);
    fixture.detectChanges();
    await fixture.whenStable();
  });

  afterEach(() => { httpMock.verify(); localStorage.clear(); });

  it('pre-remplit la signature avec le nom Google (query param "name")', () => {
    expect(component.signature).toBe('Jean');
  });

  it('navigue vers /select-role apres soumission reussie quand next="select-role"', () => {
    const spy = vi.spyOn(router, 'navigate');

    component.username    = 'jean_google';
    component.signature   = 'Jean Dupont';
    component.acceptTerms = true;
    localStorage.setItem('access_token', 'oauth-token');

    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/complete-oauth-profile`).flush({
      success: true,
      data: {
        tokens: { access_token: 'new-at', refresh_token: 'new-rt' },
        user: { ...BASE_USER, username: 'jean_google', email_verified: true },
        next: 'select-role',
      },
    });

    expect(spy).toHaveBeenCalledWith(['/select-role']);
  });

  it('affiche erreur si username deja pris', () => {
    component.username    = 'existinguser';
    component.signature   = 'Jean';
    component.acceptTerms = true;
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/complete-oauth-profile`).flush(
      { success: false, feedback: { message: "Nom d'utilisateur deja pris." } },
      { status: 400, statusText: 'Bad Request' },
    );

    expect(component.error()).toContain('deja pris');
  });

  it('stocke les tokens en localStorage apres succes', () => {
    component.username    = 'jean_google';
    component.signature   = 'Jean';
    component.acceptTerms = true;
    component.onSubmit();

    httpMock.expectOne(`${API}/api/auth/complete-oauth-profile`).flush({
      success: true,
      data: {
        tokens: { access_token: 'oauth-access', refresh_token: 'oauth-refresh' },
        user: { ...BASE_USER },
        next: '/',
      },
    });

    expect(localStorage.getItem('access_token')).toBe('oauth-access');
    expect(localStorage.getItem('refresh_token')).toBe('oauth-refresh');
  });
});
