import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest';

import {
  IosPurchaseService, STOREKIT_PURCHASE,
  IosPurchaseCancelledError, IosPurchasePendingError,
} from './ios-purchase.service';
import { environment } from '../../environments/environment';

const API = `${environment.apiUrl}/api/apple-iap`;

function fakePlugin(overrides: Record<string, unknown> = {}) {
  return {
    getProducts: vi.fn().mockResolvedValue({ products: [
      { productId: 'p.premium', displayName: 'Premium', description: '', displayPrice: '4,99 €' },
    ] }),
    purchase:              vi.fn().mockResolvedValue({ transactionJWS: 'jws-1' }),
    restorePurchases:      vi.fn().mockResolvedValue({ transactions: [] }),
    getActiveEntitlements: vi.fn().mockResolvedValue({ transactions: [] }),
    addListener:           vi.fn().mockResolvedValue({ remove: vi.fn() }),
    ...overrides,
  };
}

/** Laisse les promesses en attente se résoudre avant d'inspecter HttpTestingController. */
const tick = () => new Promise<void>(resolve => setTimeout(resolve));

describe('IosPurchaseService', () => {
  let svc: IosPurchaseService;
  let httpMock: HttpTestingController;
  let plugin: ReturnType<typeof fakePlugin>;

  function setup(overrides: Record<string, unknown> = {}): void {
    plugin = fakePlugin(overrides);
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: STOREKIT_PURCHASE, useValue: plugin },
      ],
    });
    svc = TestBed.inject(IosPurchaseService);
    httpMock = TestBed.inject(HttpTestingController);
  }

  afterEach(() => httpMock.verify());

  describe('loadOffers()', () => {
    it('croise les produits du serveur avec les prix de l\'App Store', async () => {
      setup();
      const promise = svc.loadOffers();
      httpMock.expectOne(`${API}/products`).flush({ success: true, data: {
        configured: true,
        app_account_token: 'tok',
        products: [
          { plan: 'premium',  product_id: 'p.premium' },
          { plan: 'semi_pro', product_id: 'p.absent-du-store' },
        ],
      } });

      // Un palier dont le produit n'existe pas côté App Store n'est pas proposé.
      expect(await promise).toEqual([
        { plan: 'premium', productId: 'p.premium', displayPrice: '4,99 €' },
      ]);
      expect(plugin.getProducts).toHaveBeenCalledWith({
        productIds: ['p.premium', 'p.absent-du-store'],
      });
    });

    it('ne propose rien et n\'interroge pas StoreKit si le serveur n\'est pas configuré', async () => {
      setup();
      const promise = svc.loadOffers();
      httpMock.expectOne(`${API}/products`).flush({ success: true, data: {
        configured: false, products: [], app_account_token: 'tok',
      } });
      expect(await promise).toEqual([]);
      expect(plugin.getProducts).not.toHaveBeenCalled();
    });
  });

  describe('purchase()', () => {
    beforeEach(() => setup());

    it('attache le jeton de compte et fait vérifier la transaction par le serveur', async () => {
      const offers = svc.loadOffers();
      httpMock.expectOne(`${API}/products`).flush({ success: true, data: {
        configured: true, app_account_token: 'tok-user',
        products: [{ plan: 'premium', product_id: 'p.premium' }],
      } });
      await offers;

      const promise = svc.purchase('p.premium');
      await tick();
      expect(plugin.purchase).toHaveBeenCalledWith({
        productId: 'p.premium', appAccountToken: 'tok-user',
      });

      const req = httpMock.expectOne(`${API}/verify`);
      expect(req.request.body).toEqual({ transactions: ['jws-1'] });
      req.flush({ success: true, data: {
        credited: 1, subscription_plan: 'premium', is_premium_active: true,
      } });

      expect((await promise).credited).toBe(1);
    });

    it('une annulation n\'appelle pas le serveur', async () => {
      plugin.purchase.mockRejectedValue({ code: 'USER_CANCELLED' });
      await expect(svc.purchase('p.premium')).rejects.toBeInstanceOf(IosPurchaseCancelledError);
      httpMock.expectNone(`${API}/verify`);
    });

    it('un achat en attente de validation est distingué d\'une erreur', async () => {
      plugin.purchase.mockRejectedValue({ code: 'PENDING' });
      await expect(svc.purchase('p.premium')).rejects.toBeInstanceOf(IosPurchasePendingError);
      httpMock.expectNone(`${API}/verify`);
    });

    it('un refus du serveur fait échouer l\'achat', async () => {
      const promise = svc.purchase('p.premium');
      const rejection = expect(promise).rejects.toBeTruthy();
      await tick();
      httpMock.expectOne(`${API}/verify`).flush(
        { success: false, code: 'IAP_INVALID_TRANSACTION', feedback: { level: 'error', message: 'non' } },
        { status: 400, statusText: 'Bad Request' },
      );
      await rejection;
    });
  });

  describe('restore() / reconcile()', () => {
    it('restore() envoie toutes les transactions en une seule requête', async () => {
      setup({ restorePurchases: vi.fn().mockResolvedValue({
        transactions: [{ transactionJWS: 'a' }, { transactionJWS: 'b' }],
      }) });
      const promise = svc.restore();
      await tick();
      const req = httpMock.expectOne(`${API}/verify`);
      expect(req.request.body).toEqual({ transactions: ['a', 'b'] });
      req.flush({ success: true, data: { credited: 0, subscription_plan: 'free', is_premium_active: false } });
      expect((await promise)?.credited).toBe(0);
    });

    it('reconcile() ne fait aucune requête quand l\'appareil n\'a aucun achat', async () => {
      setup();
      expect(await svc.reconcile()).toBeNull();
      httpMock.expectNone(`${API}/verify`);
      expect(plugin.restorePurchases).not.toHaveBeenCalled();
    });
  });

  describe('onTransactionUpdated()', () => {
    it('fait vérifier la transaction reçue et prévient l\'appelant', async () => {
      setup();
      const callback = vi.fn();
      await svc.onTransactionUpdated(callback);

      const listener = plugin.addListener.mock.calls[0][1] as (e: { transactionJWS: string }) => void;
      listener({ transactionJWS: 'late' });

      const req = httpMock.expectOne(`${API}/verify`);
      expect(req.request.body).toEqual({ transactions: ['late'] });
      req.flush({ success: true, data: { credited: 1, subscription_plan: 'premium', is_premium_active: true } });
      expect(callback).toHaveBeenCalledWith(expect.objectContaining({ credited: 1 }));
    });
  });
});
