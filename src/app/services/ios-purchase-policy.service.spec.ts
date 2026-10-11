import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { describe, it, expect, afterEach } from 'vitest';

import { IosPurchasePolicyService, IS_IOS_APP } from './ios-purchase-policy.service';
import { ToastService } from './toast.service';
import { environment } from '../../environments/environment';

const POLICY_URL = `${environment.apiUrl}/api/apple-iap/policy`;

function configure(isIos: boolean): void {
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: IS_IOS_APP, useValue: isIos },
    ],
  });
}

describe('IosPurchasePolicyService', () => {
  let httpMock: HttpTestingController;

  afterEach(() => httpMock.verify());

  describe('hors de l\'app iOS (web, Android)', () => {
    it('tout se paie par Stripe, sans appeler le serveur', () => {
      configure(false);
      const svc = TestBed.inject(IosPurchasePolicyService);
      httpMock = TestBed.inject(HttpTestingController);

      httpMock.expectNone(POLICY_URL);
      expect(svc.ready()).toBe(true);
      expect(svc.subscription()).toBe('stripe');
      expect(svc.beatLicense()).toBe('stripe');
      expect(svc.mixOrder()).toBe('stripe');
      expect(svc.campaignBoost()).toBe('stripe');
      expect(svc.guard('subscription')).toBe(true);
    });
  });

  describe('dans l\'app iOS', () => {
    function setup() {
      configure(true);
      const svc = TestBed.inject(IosPurchasePolicyService);
      httpMock = TestBed.inject(HttpTestingController);
      return svc;
    }

    it('rien n\'est vendable tant que la politique n\'est pas chargée', () => {
      const svc = setup();
      expect(svc.ready()).toBe(false);
      expect(svc.subscription()).toBe('unavailable');
      expect(svc.beatLicense()).toBe('unavailable');
      httpMock.expectOne(POLICY_URL).flush({ success: true, data: { policy: {} } });
    });

    it('applique la politique du serveur', () => {
      const svc = setup();
      httpMock.expectOne(POLICY_URL).flush({ success: true, data: { policy: {
        subscription: 'iap', beat_license: 'stripe',
        mix_order: 'stripe', campaign_boost: 'unavailable',
      } } });

      expect(svc.ready()).toBe(true);
      expect(svc.subscription()).toBe('iap');
      expect(svc.beatLicense()).toBe('stripe');
      expect(svc.mixOrder()).toBe('stripe');
      expect(svc.campaignBoost()).toBe('unavailable');
    });

    it('l\'abonnement ne passe jamais par Stripe, même si le serveur le dit', () => {
      const svc = setup();
      httpMock.expectOne(POLICY_URL).flush({ success: true, data: { policy: {
        subscription: 'stripe', beat_license: 'iap', mix_order: 'nimporte', campaign_boost: 'stripe',
      } } });

      expect(svc.subscription()).toBe('unavailable');
      expect(svc.beatLicense()).toBe('unavailable');
      expect(svc.mixOrder()).toBe('unavailable');
      expect(svc.campaignBoost()).toBe('stripe');
    });

    it('tout est indisponible si le serveur ne répond pas', () => {
      const svc = setup();
      httpMock.expectOne(POLICY_URL).flush('boom', { status: 500, statusText: 'Server Error' });

      expect(svc.ready()).toBe(true);
      expect(svc.subscription()).toBe('unavailable');
      expect(svc.beatLicense()).toBe('unavailable');
    });

    it('guard() bloque et prévient quand la catégorie n\'est pas payable par Stripe', () => {
      const svc = setup();
      const toast = TestBed.inject(ToastService);
      httpMock.expectOne(POLICY_URL).flush({ success: true, data: { policy: {
        subscription: 'iap', beat_license: 'stripe',
        mix_order: 'unavailable', campaign_boost: 'unavailable',
      } } });

      expect(svc.guard('beat_license')).toBe(true);
      expect(toast._toasts().length).toBe(0);

      // 'iap' n'autorise pas Stripe non plus : l'abonnement a son propre chemin.
      expect(svc.guard('subscription')).toBe(false);
      expect(svc.guard('mix_order')).toBe(false);
      expect(toast._toasts().length).toBe(2);
    });
  });
});
