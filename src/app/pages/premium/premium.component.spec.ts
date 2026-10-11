import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';
import { signal } from '@angular/core';
import { vi, describe, it, expect, afterEach } from 'vitest';

import { PremiumComponent } from './premium.component';
import { AuthService } from '../../services/auth.service';
import { IS_IOS_APP } from '../../services/ios-purchase-policy.service';
import { IosPurchaseService } from '../../services/ios-purchase.service';
import { environment } from '../../../environments/environment';

// Ce spec ne couvre qu'une chose : le choix du moyen de paiement selon la
// plateforme. Dans l'app iOS, aucun clic ne doit pouvoir ouvrir un checkout
// Stripe pour un abonnement (App Review 3.1.1) — c'est la régression à ne
// jamais laisser passer.

const API = environment.apiUrl;

const PLANS_RESPONSE = {
  success: true,
  data: {
    plans: [],
    comparison: {
      columns: [
        { key: 'free',    label: 'Découverte', price: 0,    tone: 'tu' },
        { key: 'premium', label: 'Premium',    price: 4.99, tone: 'tu' },
      ],
      groups: [],
    },
  },
};

function fakeAuth() {
  return {
    currentUser: signal(null),
    isPremium:   signal(false),
    isPro:       signal(false),
    plan:        signal('free'),
    planLabel:   signal('Découverte'),
    me:          vi.fn().mockReturnValue({ subscribe: vi.fn() }),
  };
}

function fakeIosPurchase() {
  return {
    loadOffers: vi.fn().mockResolvedValue([
      { plan: 'premium', productId: 'p.premium', displayPrice: '5,99 €' },
    ]),
    purchase:  vi.fn().mockResolvedValue({ credited: 1, subscription_plan: 'premium', is_premium_active: true }),
    restore:   vi.fn().mockResolvedValue(null),
    reconcile: vi.fn().mockResolvedValue(null),
    onTransactionUpdated: vi.fn().mockResolvedValue({ remove: vi.fn() }),
  };
}

const tick = () => new Promise<void>(resolve => setTimeout(resolve));

describe('PremiumComponent — moyen de paiement selon la plateforme', () => {
  let fixture: ComponentFixture<PremiumComponent>;
  let httpMock: HttpTestingController;
  let ios: ReturnType<typeof fakeIosPurchase>;

  function setup(isIos: boolean): void {
    ios = fakeIosPurchase();
    TestBed.configureTestingModule({
      imports: [PremiumComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: AuthService, useValue: fakeAuth() },
        { provide: IosPurchaseService, useValue: ios },
        { provide: IS_IOS_APP, useValue: isIos },
      ],
    });
    fixture = TestBed.createComponent(PremiumComponent);
    httpMock = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    httpMock.expectOne(`${API}/api/premium/plans`).flush(PLANS_RESPONSE);
  }

  async function settle(): Promise<void> {
    await tick();
    fixture.detectChanges();
  }

  const planButton = () =>
    fixture.nativeElement.querySelector('.btn-plan-premium') as HTMLButtonElement | null;
  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';

  afterEach(() => httpMock.verify());

  it('web : le bouton ouvre le checkout Stripe, avec le prix de la grille', async () => {
    setup(false);
    await settle();

    expect(text()).toContain('4.99');
    expect(text()).not.toContain('Restaurer mes achats');
    planButton()!.click();

    httpMock.expectOne(`${API}/api/premium/subscribe`).flush({ success: false });
    expect(ios.loadOffers).not.toHaveBeenCalled();
    expect(ios.purchase).not.toHaveBeenCalled();
  });

  it('app iOS : le bouton passe par l\'achat intégré, jamais par Stripe', async () => {
    setup(true);
    httpMock.expectOne(`${API}/api/apple-iap/policy`).flush({ success: true, data: { policy: {
      subscription: 'iap', beat_license: 'stripe', mix_order: 'stripe', campaign_boost: 'unavailable',
    } } });
    await settle();
    await settle();

    // Prix de l'App Store, pas celui de la grille Stripe.
    expect(text()).toContain('5,99 €');
    expect(text()).not.toContain('4.99');
    expect(text()).toContain('Restaurer mes achats');
    expect(text()).not.toContain('Stripe');

    planButton()!.click();
    await settle();

    expect(ios.purchase).toHaveBeenCalledWith('p.premium');
    httpMock.expectNone(`${API}/api/premium/subscribe`);
  });

  it('app iOS sans achat intégré : ni prix, ni bouton, ni Stripe', async () => {
    setup(true);
    httpMock.expectOne(`${API}/api/apple-iap/policy`).flush({ success: true, data: { policy: {
      subscription: 'unavailable', beat_license: 'stripe', mix_order: 'stripe', campaign_boost: 'unavailable',
    } } });
    await settle();

    expect(planButton()).toBeNull();
    expect(text()).not.toContain('4.99');
    expect(text()).toContain('ne sont pas proposés dans l\'application iOS');
    expect(ios.loadOffers).not.toHaveBeenCalled();

    // Même appelée directement, la méthode Stripe refuse de partir.
    fixture.componentInstance.subscribe('premium');
    httpMock.expectNone(`${API}/api/premium/subscribe`);
  });

  it('app iOS : « Restaurer mes achats » interroge StoreKit', async () => {
    setup(true);
    httpMock.expectOne(`${API}/api/apple-iap/policy`).flush({ success: true, data: { policy: {
      subscription: 'iap', beat_license: 'stripe', mix_order: 'stripe', campaign_boost: 'unavailable',
    } } });
    await settle();

    (fixture.nativeElement.querySelector('.btn-restore') as HTMLButtonElement).click();
    await settle();
    expect(ios.restore).toHaveBeenCalledTimes(1);
  });
});
