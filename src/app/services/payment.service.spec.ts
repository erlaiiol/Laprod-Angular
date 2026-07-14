/**
 * Tests du PaymentService — intégration Stripe côté Angular
 *
 * Contrats vérifiés :
 *
 * createCheckout() :
 *   • URL correcte : /api/track-payment/track/{id}/{format}/checkout
 *   • Corps JSON avec les options de licence (booleans natifs JS, pas strings)
 *   • Mode Rapide (preset Starter) : options par défaut correctement typées
 *   • Mode Avancé : toutes les options transmises
 *   • Réponse : data.checkout_url (string HTTPS) + data.total (number)
 *
 * verifyPayment() :
 *   • URL correcte : /api/track-payment/verify
 *   • Corps JSON exactement { session_id: string }
 *   • Réponse : data.purchase_id (number)
 *   • Propagation d'erreurs HTTP
 *
 * redirectToCheckout() :
 *   • Positionne window.location.href (pas de requête HTTP)
 */

import { TestBed } from '@angular/core/testing';
import {
  provideHttpClient,
  HttpErrorResponse,
} from '@angular/common/http';
import {
  provideHttpClientTesting,
  HttpTestingController,
} from '@angular/common/http/testing';

import { PaymentService, CheckoutOptions, CheckoutData, VerifyPurchaseData } from './payment.service';
import { ApiResponse } from './topline.service';
import { environment } from '../../environments/environment';

const BASE_URL = `${environment.apiUrl}/api/track-payment`;

// Consentement minimal requis par le backend (create_checkout renvoie 400 sinon)
const REQUIRED_CONSENT = {
  legal_terms_accepted:    true,
  withdrawal_right_waived: true,
};

// Options du preset Starter (mode Rapide — les moins chères)
const QUICK_MODE_OPTIONS: CheckoutOptions = {
  is_exclusive:            false,
  is_lifetime:             false,
  duration_years:          3,
  territory:               'France',
  mechanical_reproduction: false,
  public_show:             false,
  arrangement:             false,
  total_price:             14.99,
  ...REQUIRED_CONSENT,
};

// Options mode Avancé avec droits supplémentaires
const ADVANCED_MODE_OPTIONS: CheckoutOptions = {
  is_exclusive:            false,
  is_lifetime:             false,
  duration_years:          5,
  territory:               'Europe',
  mechanical_reproduction: true,
  public_show:             true,
  arrangement:             false,
  total_price:             74.99,
  ...REQUIRED_CONSENT,
};

// ── Setup ──────────────────────────────────────────────────────────────────────

describe('PaymentService', () => {
  let service: PaymentService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        PaymentService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service  = TestBed.inject(PaymentService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  // ── createCheckout() : URL et méthode ──────────────────────────────────────

  describe('createCheckout() — URL et méthode', () => {

    it('POSTs vers /api/track-payment/track/:id/:format/checkout', () => {
      service.createCheckout(10, 'mp3', REQUIRED_CONSENT).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/10/mp3/checkout`);
      expect(req.request.method).toBe('POST');
      req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/test', total: 9.99 } });
    });

    it('utilise le bon trackId dans l\'URL', () => {
      service.createCheckout(42, 'wav', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/42/wav/checkout`);
      expect(req.request.urlWithParams).toContain('/42/wav/checkout');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 19.99 } });
    });

    it('accepte mp3, wav et stems comme format', () => {
      for (const format of ['mp3', 'wav', 'stems']) {
        service.createCheckout(1, format, REQUIRED_CONSENT).subscribe();
        const req = httpMock.expectOne(`${BASE_URL}/track/1/${format}/checkout`);
        req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 9.99 } });
      }
    });

  });

  // ── createCheckout() : corps JSON ─────────────────────────────────────────

  describe('createCheckout() — corps JSON', () => {

    it('envoie les options dans le corps JSON', () => {
      service.createCheckout(5, 'wav', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/5/wav/checkout`);
      expect(req.request.body).toEqual(QUICK_MODE_OPTIONS);
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
    });

    it('mode Rapide — is_exclusive est un boolean false (pas une string)', () => {
      service.createCheckout(1, 'mp3', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body['is_exclusive']).toBe(false);
      expect(typeof req.request.body['is_exclusive']).toBe('boolean');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
    });

    it('mode Rapide — duration_years est un number (pas une string)', () => {
      service.createCheckout(1, 'mp3', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body['duration_years']).toBe(3);
      expect(typeof req.request.body['duration_years']).toBe('number');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
    });

    it('mode Rapide — territory est "France" (le moins cher)', () => {
      service.createCheckout(1, 'mp3', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body['territory']).toBe('France');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
    });

    it('mode Rapide — mechanical_reproduction, public_show, arrangement sont false', () => {
      service.createCheckout(1, 'mp3', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body['mechanical_reproduction']).toBe(false);
      expect(req.request.body['public_show']).toBe(false);
      expect(req.request.body['arrangement']).toBe(false);
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
    });

    it('mode Rapide — total_price est un number (Decimal cœté serveur validera)', () => {
      service.createCheckout(1, 'mp3', QUICK_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(typeof req.request.body['total_price']).toBe('number');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
    });

    it('mode Avancé — mechanical_reproduction true transmis', () => {
      service.createCheckout(1, 'mp3', ADVANCED_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body['mechanical_reproduction']).toBe(true);
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 74.99 } });
    });

    it('mode Avancé — territory Europe transmis', () => {
      service.createCheckout(1, 'mp3', ADVANCED_MODE_OPTIONS).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body['territory']).toBe('Europe');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 74.99 } });
    });

    it('options minimales (consentement seul) envoie un objet JSON, pas null', () => {
      service.createCheckout(1, 'mp3', REQUIRED_CONSENT).subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/track/1/mp3/checkout`);
      expect(req.request.body).toEqual(REQUIRED_CONSENT);
      expect(req.request.body).not.toBeNull();
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 9.99 } });
    });

  });

  // ── createCheckout() : réponse ─────────────────────────────────────────────

  describe('createCheckout() — réponse Stripe', () => {

    it('émet ApiResponse<CheckoutData> avec checkout_url string HTTPS', () => {
      let result: ApiResponse<CheckoutData> | undefined;
      service.createCheckout(10, 'mp3', QUICK_MODE_OPTIONS).subscribe({ next: r => result = r });

      const req = httpMock.expectOne(`${BASE_URL}/track/10/mp3/checkout`);
      req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/pay/cs_test_xyz', total: 14.99 } });

      expect(result!.success).toBe(true);
      expect(typeof result!.data!.checkout_url).toBe('string');
      expect(result!.data!.checkout_url).toMatch(/^https:\/\//);
    });

    it('data.total est un number (jamais une string)', () => {
      let result: ApiResponse<CheckoutData> | undefined;
      service.createCheckout(10, 'mp3', QUICK_MODE_OPTIONS).subscribe({ next: r => result = r });

      const req = httpMock.expectOne(`${BASE_URL}/track/10/mp3/checkout`);
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test', total: 14.99 } });
      expect(typeof result!.data!.total).toBe('number');
    });

    it('propage les erreurs HTTP 403 (prix manipulé)', () => {
      let err: HttpErrorResponse | undefined;
      const tampered = { ...QUICK_MODE_OPTIONS, total_price: 0.01 };
      service.createCheckout(10, 'mp3', tampered).subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${BASE_URL}/track/10/mp3/checkout`);
      req.flush(
        { success: false, feedback: { message: 'Prix invalide.' } },
        { status: 403, statusText: 'Forbidden' },
      );
      expect(err!.status).toBe(403);
    });

    it('propage les erreurs HTTP 500 (Stripe indisponible)', () => {
      let err: HttpErrorResponse | undefined;
      service.createCheckout(10, 'mp3', QUICK_MODE_OPTIONS).subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${BASE_URL}/track/10/mp3/checkout`);
      req.flush(
        { success: false, feedback: { message: 'Erreur Stripe.' } },
        { status: 500, statusText: 'Internal Server Error' },
      );
      expect(err!.status).toBe(500);
    });

  });

  // ── verifyPayment() ────────────────────────────────────────────────────────

  describe('verifyPayment() — corps et réponse', () => {

    it('POSTs vers /api/track-payment/verify', () => {
      service.verifyPayment('cs_test_abc123').subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/verify`);
      expect(req.request.method).toBe('POST');
      req.flush({ success: true, data: { purchase_id: 1 } });
    });

    it('envoie exactement { session_id: string } dans le corps JSON', () => {
      service.verifyPayment('cs_test_xyz').subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/verify`);
      expect(req.request.body).toEqual({ session_id: 'cs_test_xyz' });
      // Clé snake_case obligatoire — le backend lit data.get('session_id')
      expect(req.request.body['sessionId']).toBeUndefined();
      req.flush({ success: true, data: { purchase_id: 2 } });
    });

    it('session_id est une string (jamais undefined ou null)', () => {
      service.verifyPayment('cs_test_abc').subscribe();

      const req = httpMock.expectOne(`${BASE_URL}/verify`);
      expect(typeof req.request.body['session_id']).toBe('string');
      expect(req.request.body['session_id']).not.toBeNull();
      req.flush({ success: true, data: { purchase_id: 3 } });
    });

    it('émet ApiResponse<VerifyPurchaseData> avec purchase_id number', () => {
      let result: ApiResponse<VerifyPurchaseData> | undefined;
      service.verifyPayment('cs_test_abc').subscribe({ next: r => result = r });

      const req = httpMock.expectOne(`${BASE_URL}/verify`);
      req.flush({ success: true, data: { purchase_id: 99 } });

      expect(result!.success).toBe(true);
      expect(typeof result!.data!.purchase_id).toBe('number');
      expect(result!.data!.purchase_id).toBe(99);
    });

    it('propage les erreurs HTTP 403 (acheteur JWT ≠ metadata buyer_id)', () => {
      let err: HttpErrorResponse | undefined;
      service.verifyPayment('cs_test_other_user').subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${BASE_URL}/verify`);
      req.flush(
        { success: false, feedback: { message: 'Cette session ne vous appartient pas.' } },
        { status: 403, statusText: 'Forbidden' },
      );
      expect(err!.status).toBe(403);
    });

    it('propage les erreurs HTTP 400 (paiement non confirmé)', () => {
      let err: HttpErrorResponse | undefined;
      service.verifyPayment('cs_test_pending').subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${BASE_URL}/verify`);
      req.flush(
        { success: false, feedback: { message: 'Paiement non confirmé.' } },
        { status: 400, statusText: 'Bad Request' },
      );
      expect(err!.status).toBe(400);
    });

  });

  // ── redirectToCheckout() ───────────────────────────────────────────────────

  describe('redirectToCheckout()', () => {

    it('positionne window.location.href sans requête HTTP', () => {
      // window.location n'est pas mockable via vi.spyOn en jsdom.
      // Contrat clé : aucune requête HTTP ne part (httpMock.verify() dans afterEach).
      // Contrat secondaire : l'appel ne lève pas d'exception.
      expect(() => service.redirectToCheckout('https://checkout.stripe.com/pay/cs_test_live')).not.toThrow();
    });

  });

});
