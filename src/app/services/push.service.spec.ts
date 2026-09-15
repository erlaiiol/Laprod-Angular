import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

import { PushService } from './push.service';
import { IS_NATIVE_PLATFORM } from './draft-save.service';
import { environment } from '../../environments/environment';

// ── Mocks ─────────────────────────────────────────────────────────────────────
//
// Comme DraftSaveService (cf. draft-save.service.spec.ts) : IS_NATIVE_PLATFORM
// est overridé via TestBed, et le plugin Firebase (chargé par import() dynamique
// pour ne jamais entrer dans le bundle web, cf. push.service.ts) est mocké en
// remplaçant la méthode overridable _loadMessaging() plutôt qu'en mockant le
// module — un vi.mock() sur un import dynamique s'est révélé peu fiable dans
// cette suite.

function fakeMessaging(overrides: Record<string, unknown> = {}) {
  return {
    addListener:        vi.fn(),
    checkPermissions:   vi.fn().mockResolvedValue({ receive: 'prompt' }),
    requestPermissions: vi.fn().mockResolvedValue({ receive: 'granted' }),
    getToken:           vi.fn().mockResolvedValue({ token: 'tok-fake' }),
    ...overrides,
  };
}

function configure(isNative: boolean): void {
  TestBed.configureTestingModule({
    providers: [
      PushService,
      provideHttpClient(),
      provideHttpClientTesting(),
      provideRouter([]),
      { provide: IS_NATIVE_PLATFORM, useValue: isNative },
    ],
  });
}

describe('PushService', () => {
  let svc: PushService;
  let httpMock: HttpTestingController;

  afterEach(() => {
    httpMock.verify();
  });

  describe('sur le web (IS_NATIVE_PLATFORM = false)', () => {
    beforeEach(() => {
      configure(false);
      svc = TestBed.inject(PushService);
      httpMock = TestBed.inject(HttpTestingController);
    });

    it('init() ne charge jamais Firebase', async () => {
      const spy = vi.spyOn(svc as any, '_loadMessaging');
      await svc.init();
      expect(spy).not.toHaveBeenCalled();
    });

    it('enablePush() retourne false sans solliciter Firebase', async () => {
      const spy = vi.spyOn(svc as any, '_loadMessaging');
      const result = await svc.enablePush();
      expect(result).toBe(false);
      expect(spy).not.toHaveBeenCalled();
    });
  });

  describe('sur mobile natif (IS_NATIVE_PLATFORM = true)', () => {
    beforeEach(() => {
      configure(true);
      svc = TestBed.inject(PushService);
      httpMock = TestBed.inject(HttpTestingController);
    });

    it('init() pose les listeners sans demander de permission', async () => {
      const messaging = fakeMessaging();
      vi.spyOn(svc as any, '_loadMessaging').mockResolvedValue({ FirebaseMessaging: messaging });

      await svc.init();

      expect(messaging.addListener).toHaveBeenCalledWith('tokenReceived', expect.any(Function));
      expect(messaging.addListener).toHaveBeenCalledWith('notificationActionPerformed', expect.any(Function));
      expect(messaging.requestPermissions).not.toHaveBeenCalled();
    });

    it('init() enregistre un jeton frais si la permission est déjà accordée', async () => {
      const messaging = fakeMessaging({
        checkPermissions: vi.fn().mockResolvedValue({ receive: 'granted' }),
      });
      vi.spyOn(svc as any, '_loadMessaging').mockResolvedValue({ FirebaseMessaging: messaging });

      // Fire-and-forget, comme dans app.ts — init() n'est jamais awaité avant
      // le flush de la requête HTTP qu'il déclenche en interne, sinon deadlock :
      // aucun code ne pourrait plus flusher httpMock une fois `await` bloqué dessus.
      void svc.init();
      const req = await vi.waitFor(() => httpMock.expectOne(`${environment.apiUrl}/api/push/register`));
      expect(req.request.body).toEqual({ token: 'tok-fake', platform: expect.stringMatching(/android|ios/) });
      req.flush({ success: true });
    });

    it('enablePush() demande la permission puis enregistre le jeton', async () => {
      const messaging = fakeMessaging();
      vi.spyOn(svc as any, '_loadMessaging').mockResolvedValue({ FirebaseMessaging: messaging });

      let result: boolean | undefined;
      svc.enablePush().then(r => (result = r));

      const req = await vi.waitFor(() => httpMock.expectOne(`${environment.apiUrl}/api/push/register`));
      req.flush({ success: true });

      await vi.waitFor(() => expect(result).toBe(true));
      expect(messaging.requestPermissions).toHaveBeenCalled();
    });

    it('enablePush() retourne false sans appel réseau si la permission est refusée', async () => {
      const messaging = fakeMessaging({
        requestPermissions: vi.fn().mockResolvedValue({ receive: 'denied' }),
      });
      vi.spyOn(svc as any, '_loadMessaging').mockResolvedValue({ FirebaseMessaging: messaging });

      const result = await svc.enablePush();

      expect(result).toBe(false);
      httpMock.expectNone(`${environment.apiUrl}/api/push/register`);
    });

    it('tap sur une notification navigue vers le lien du payload', async () => {
      const messaging = fakeMessaging();   // checkPermissions: 'prompt' → pas d'appel réseau
      vi.spyOn(svc as any, '_loadMessaging').mockResolvedValue({ FirebaseMessaging: messaging });
      const router = TestBed.inject(Router);
      const navigateSpy = vi.spyOn(router, 'navigateByUrl').mockResolvedValue(true);

      await svc.init();
      const call = messaging.addListener.mock.calls.find(
        (c: unknown[]) => c[0] === 'notificationActionPerformed',
      )!;
      const handler = call[1] as (event: unknown) => void;
      handler({ notification: { data: { link: '/upload-track' } } });

      expect(navigateSpy).toHaveBeenCalledWith('/upload-track');
    });
  });

  describe('preferences', () => {
    beforeEach(() => {
      configure(true);
      svc = TestBed.inject(PushService);
      httpMock = TestBed.inject(HttpTestingController);
    });

    it('getPreference() lit /api/push/preference', () => {
      svc.getPreference().subscribe();
      const req = httpMock.expectOne(`${environment.apiUrl}/api/push/preference`);
      expect(req.request.method).toBe('GET');
      req.flush({ success: true, data: { push_opt_in: false } });
    });

    it('setPreference() envoie enabled au bon endpoint', () => {
      svc.setPreference(true).subscribe();
      const req = httpMock.expectOne(`${environment.apiUrl}/api/push/preference`);
      expect(req.request.method).toBe('PUT');
      expect(req.request.body).toEqual({ enabled: true });
      req.flush({ success: true, data: { push_opt_in: true } });
    });
  });
});
