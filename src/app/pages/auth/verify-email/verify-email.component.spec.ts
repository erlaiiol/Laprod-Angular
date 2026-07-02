import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, ActivatedRoute } from '@angular/router';

import { VerifyEmailComponent } from './verify-email.component';
import { environment } from '../../../../environments/environment';

const VERIFY_URL = `${environment.apiUrl}/api/auth/verify-email`;

function makeRoute(token: string | null) {
  return {
    provide: ActivatedRoute,
    useValue: { snapshot: { queryParamMap: { get: (k: string) => (k === 'token' ? token : null) } } },
  };
}

async function setup(token: string | null) {
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
      makeRoute(token),
    ],
  }).compileComponents();

  const fixture  = TestBed.createComponent(VerifyEmailComponent);
  const httpMock = TestBed.inject(HttpTestingController);
  return { fixture, component: fixture.componentInstance, httpMock };
}

describe('VerifyEmailComponent', () => {

  afterEach(() => TestBed.resetTestingModule());

  // ── État chargement ─────────────────────────────────────────────────────────

  it('is in loading state before the API responds', async () => {
    const { fixture, component, httpMock } = await setup('any-token');
    fixture.detectChanges(); // déclenche ngOnInit → appel HTTP

    expect(component.state()).toBe('loading');

    // consommer la requête en suspens pour satisfaire httpMock.verify()
    httpMock.expectOne(VERIFY_URL).flush({ success: true, feedback: { message: 'OK' } });
  });

  // ── Token absent ────────────────────────────────────────────────────────────

  it('shows "Lien invalide" heading when no token is in the URL', async () => {
    const { fixture, component, httpMock } = await setup(null);
    fixture.detectChanges(); // aucun appel HTTP attendu

    expect(component.state()).toBe('error');
    const h2 = fixture.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2?.textContent?.trim()).toBe('Lien invalide');

    httpMock.expectNone(VERIFY_URL);
  });

  // ── Token valide ────────────────────────────────────────────────────────────

  it('shows "Email vérifié !" and a login link after a valid token', async () => {
    const { fixture, component, httpMock } = await setup('valid-token');
    fixture.detectChanges();

    httpMock.expectOne(VERIFY_URL).flush({
      success: true,
      feedback: { message: 'Email vérifié ! Vous pouvez maintenant vous connecter.' },
    });
    fixture.detectChanges();

    expect(component.state()).toBe('success');

    const h2 = fixture.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2?.textContent?.trim()).toBe('Email vérifié !');

    // Lien "Se connecter" doit être visible → l'utilisateur peut passer à la connexion
    const loginLink = fixture.nativeElement.querySelector('a[routerLink="/login"]');
    expect(loginLink).toBeTruthy();
  });

  it('displays the server message on success', async () => {
    const { fixture, httpMock } = await setup('valid-token');
    fixture.detectChanges();

    httpMock.expectOne(VERIFY_URL).flush({
      success: true,
      feedback: { message: 'Votre compte est maintenant actif.' },
    });
    fixture.detectChanges();

    const p = fixture.nativeElement.querySelector('p') as HTMLElement;
    expect(p?.textContent).toContain('Votre compte est maintenant actif.');
  });

  // ── Token expiré ────────────────────────────────────────────────────────────

  it('shows "Lien expiré" and a register link when the token is expired', async () => {
    const { fixture, component, httpMock } = await setup('expired-token');
    fixture.detectChanges();

    httpMock.expectOne(VERIFY_URL).flush(
      { success: false, code: 'TOKEN_EXPIRED', feedback: { message: 'Lien expiré.' } },
      { status: 400, statusText: 'Bad Request' },
    );
    fixture.detectChanges();

    expect(component.state()).toBe('expired');

    const h2 = fixture.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2?.textContent?.trim()).toBe('Lien expiré');

    // Lien "Retour à l'inscription" → l'utilisateur sait quoi faire
    const registerLink = fixture.nativeElement.querySelector('a[routerLink="/register"]');
    expect(registerLink).toBeTruthy();
  });

  // ── Erreur générique ────────────────────────────────────────────────────────

  it('shows "Lien invalide" heading on a generic API error', async () => {
    const { fixture, component, httpMock } = await setup('corrupted-token');
    fixture.detectChanges();

    httpMock.expectOne(VERIFY_URL).flush(
      { success: false, feedback: { message: 'Token invalide.' } },
      { status: 400, statusText: 'Bad Request' },
    );
    fixture.detectChanges();

    expect(component.state()).toBe('error');
    const h2 = fixture.nativeElement.querySelector('h2') as HTMLElement;
    expect(h2?.textContent?.trim()).toBe('Lien invalide');

    // En état d'erreur : lien vers /register (pas /login) car le lien est probablement corrompu
    const registerLink = fixture.nativeElement.querySelector('a[routerLink="/register"]');
    expect(registerLink).toBeTruthy();
  });
});
