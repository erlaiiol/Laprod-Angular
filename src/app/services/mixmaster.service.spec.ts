/**
 * Tests du MixmasterService — intégration Stripe côté Angular
 *
 * Contrats vérifiés :
 *
 * createOrder() :
 *   • URL correcte : /api/mixmaster-artist/order/{engineerId}
 *   • Méthode POST avec corps FormData (multipart, jamais JSON)
 *   • Les booléens de services sont '1' ou '0' (jamais 'true'/'false')
 *     → String(true)='true' serait rejeté par bval() côté Flask
 *   • success_url et cancel_url sont des chaînes complètes transmises
 *   • La réponse est typée ApiResponse<CheckoutData> avec checkout_url: string
 *
 * verifyPayment() :
 *   • URL correcte : /api/mixmaster-payment/verify
 *   • Corps JSON exactement { session_id: string } (clé unique, pas d'extras)
 *   • La réponse est typée ApiResponse<OrderIdData> avec order_id: number
 *   • Les erreurs HTTP sont propagées telles quelles aux souscripteurs
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

import { MixmasterService, CheckoutData, OrderIdData } from './mixmaster.service';
import { ApiResponse } from './topline.service';
import { environment } from '../../environments/environment';

const API = environment.apiUrl;

// ── Helpers ────────────────────────────────────────────────────────────────────

/** Construit un FormData minimal représentant une commande en mode Rapide. */
function buildQuickModeFormData(
  engineerId: number,
  services: { cleaning: boolean; effects: boolean; mastering: boolean; artistic: boolean },
  hasSeparatedStems = false,
): FormData {
  const fd = new FormData();
  fd.append('title', 'Test Quick Mode');
  // Contrat critique : ternaire '1'/'0', pas String(boolean)
  fd.append('service_cleaning',    services.cleaning   ? '1' : '0');
  fd.append('service_effects',     services.effects    ? '1' : '0');
  fd.append('service_artistic',    services.artistic   ? '1' : '0');
  fd.append('service_mastering',   services.mastering  ? '1' : '0');
  fd.append('has_separated_stems', hasSeparatedStems   ? '1' : '0');
  fd.append('artist_message', '');
  fd.append('success_url', `${window.location.origin}/mix/payment-success`);
  fd.append('cancel_url',  `${window.location.origin}/mix/order/${engineerId}`);
  fd.append('stems_file',    new Blob(['PK fake zip'], { type: 'application/zip' }), 'stems.zip');
  fd.append('reference_file', new Blob(['ID3 fake'],   { type: 'audio/mpeg'      }), 'ref.mp3');
  return fd;
}

/** Construit un FormData en mode Avancé avec tous les champs de briefing. */
function buildAdvancedModeFormData(engineerId: number): FormData {
  const fd = buildQuickModeFormData(
    engineerId,
    { cleaning: true, effects: true, mastering: true, artistic: false },
  );
  fd.append('brief_vocals',         'Voix claire, réverbe légère');
  fd.append('brief_backing_vocals', 'Harmonies larges en stéréo');
  fd.append('brief_ambiance',       'Atmosphère sombre et intimiste');
  fd.append('brief_bass',           'Sub profond, kick court');
  fd.append('brief_energy_style',   'Dynamique, percutant');
  fd.append('brief_references',     'Drake - CLB');
  fd.append('brief_instruments',    'Piano mis en avant');
  fd.append('brief_percussion',     'Snare claquante');
  fd.append('brief_effects_brief',  'Delay ping-pong sur voix');
  fd.append('brief_structure',      'Refrain plus large');
  return fd;
}

// ── Setup ──────────────────────────────────────────────────────────────────────

describe('MixmasterService — intégration Stripe', () => {
  let service: MixmasterService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        MixmasterService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service   = TestBed.inject(MixmasterService);
    httpMock  = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('devrait être créé', () => {
    expect(service).toBeTruthy();
  });

  // ── createOrder() : URL et méthode ─────────────────────────────────────────

  describe('createOrder() — URL et méthode', () => {

    it('POSTs vers /api/mixmaster-artist/order/{engineerId}', () => {
      const fd = buildQuickModeFormData(42, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(42, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/42`);
      expect(req.request.method).toBe('POST');
      req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/test' } });
    });

    it('utilise le bon engineerId dans l\'URL', () => {
      const fd = buildQuickModeFormData(99, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(99, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/99`);
      expect(req.request.urlWithParams).toContain('/99');
      req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/test' } });
    });

  });

  // ── createOrder() : corps FormData ─────────────────────────────────────────

  describe('createOrder() — corps FormData', () => {

    it('envoie un corps FormData (multipart), pas du JSON', () => {
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      expect(req.request.body).toBeInstanceOf(FormData);
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('envoie service_cleaning="1" quand le service est actif (mode Rapide)', () => {
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      const body = req.request.body as FormData;
      expect(body.get('service_cleaning')).toBe('1');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('envoie service_cleaning="0" quand le service est inactif (mode Rapide)', () => {
      const fd = buildQuickModeFormData(1, { cleaning: false, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      const body = req.request.body as FormData;
      expect(body.get('service_cleaning')).toBe('0');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('envoie service_mastering="1" quand le service est actif', () => {
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: true, artistic: false });
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      const body = req.request.body as FormData;
      expect(body.get('service_mastering')).toBe('1');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('envoie has_separated_stems="1" quand la case est cochée', () => {
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false }, true);
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      const body = req.request.body as FormData;
      expect(body.get('has_separated_stems')).toBe('1');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('envoie has_separated_stems="0" quand la case n\'est pas cochée', () => {
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false }, false);
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      const body = req.request.body as FormData;
      expect(body.get('has_separated_stems')).toBe('0');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('inclut success_url et cancel_url comme chaînes complètes', () => {
      const fd = buildQuickModeFormData(5, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(5, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/5`);
      const body = req.request.body as FormData;
      expect(body.get('success_url')).toBeTruthy();
      expect(body.get('cancel_url')).toBeTruthy();
      // Les URLs sont des chaînes (jamais null)
      expect(typeof body.get('success_url')).toBe('string');
      expect(typeof body.get('cancel_url')).toBe('string');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('inclut les champs de briefing avancé en mode Avancé', () => {
      const fd = buildAdvancedModeFormData(7);
      service.createOrder(7, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/7`);
      const body = req.request.body as FormData;
      expect(body.get('brief_vocals')).toBe('Voix claire, réverbe légère');
      expect(body.get('brief_ambiance')).toBe('Atmosphère sombre et intimiste');
      expect(body.get('brief_references')).toBe('Drake - CLB');
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

    it('n\'envoie pas de header Content-Type explicite (laissé au navigateur pour multipart)', () => {
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      // Angular ne doit pas forcer application/json sur un FormData
      expect(req.request.headers.get('Content-Type')).toBeNull();
      req.flush({ success: true, data: { checkout_url: 'https://stripe.test' } });
    });

  });

  // ── createOrder() : réponse ─────────────────────────────────────────────────

  describe('createOrder() — réponse Stripe', () => {

    it('émet ApiResponse<CheckoutData> avec checkout_url string', () => {
      let result: ApiResponse<CheckoutData> | undefined;
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe({ next: r => result = r });

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/pay/cs_test_abc' } });

      expect(result!.success).toBe(true);
      expect(typeof result!.data!.checkout_url).toBe('string');
      expect(result!.data!.checkout_url).toMatch(/^https:\/\//);
    });

    it('propage les erreurs HTTP (ex: 400 aucun service sélectionné)', () => {
      let err: HttpErrorResponse | undefined;
      const fd = buildQuickModeFormData(1, { cleaning: false, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      req.flush(
        { success: false, feedback: { message: 'Sélectionnez au moins un service.' } },
        { status: 400, statusText: 'Bad Request' },
      );
      expect(err!.status).toBe(400);
    });

    it('propage les erreurs HTTP 500 (ex: Stripe indisponible)', () => {
      let err: HttpErrorResponse | undefined;
      const fd = buildQuickModeFormData(1, { cleaning: true, effects: false, mastering: false, artistic: false });
      service.createOrder(1, fd).subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${API}/api/mixmaster-artist/order/1`);
      req.flush(
        { success: false, feedback: { message: 'Erreur Stripe.' } },
        { status: 500, statusText: 'Internal Server Error' },
      );
      expect(err!.status).toBe(500);
    });

  });

  // ── verifyPayment() ─────────────────────────────────────────────────────────

  describe('verifyPayment() — corps et réponse', () => {

    it('POSTs vers /api/mixmaster-payment/verify', () => {
      service.verifyPayment('cs_test_abc123').subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-payment/verify`);
      expect(req.request.method).toBe('POST');
      req.flush({ success: true, data: { order_id: 1 } });
    });

    it('envoie exactement { session_id: string } dans le corps JSON', () => {
      service.verifyPayment('cs_test_xyz789').subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-payment/verify`);
      expect(req.request.body).toEqual({ session_id: 'cs_test_xyz789' });
      // La clé doit être snake_case 'session_id', pas camelCase 'sessionId'
      expect(req.request.body['sessionId']).toBeUndefined();
      req.flush({ success: true, data: { order_id: 5 } });
    });

    it('session_id est une string (jamais null ou number)', () => {
      service.verifyPayment('cs_test_live_abc').subscribe();

      const req = httpMock.expectOne(`${API}/api/mixmaster-payment/verify`);
      expect(typeof req.request.body['session_id']).toBe('string');
      req.flush({ success: true, data: { order_id: 2 } });
    });

    it('émet ApiResponse<OrderIdData> avec order_id number', () => {
      let result: ApiResponse<OrderIdData> | undefined;
      service.verifyPayment('cs_test_abc').subscribe({ next: r => result = r });

      const req = httpMock.expectOne(`${API}/api/mixmaster-payment/verify`);
      req.flush({ success: true, data: { order_id: 42 } });

      expect(result!.success).toBe(true);
      expect(typeof result!.data!.order_id).toBe('number');
      expect(result!.data!.order_id).toBe(42);
    });

    it('propage les erreurs HTTP (ex: 403 session appartenant à un autre utilisateur)', () => {
      let err: HttpErrorResponse | undefined;
      service.verifyPayment('cs_test_stolen').subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${API}/api/mixmaster-payment/verify`);
      req.flush(
        { success: false, feedback: { message: 'Cette commande ne vous appartient pas.' } },
        { status: 403, statusText: 'Forbidden' },
      );
      expect(err!.status).toBe(403);
    });

    it('propage les erreurs HTTP (ex: 400 paiement non confirmé)', () => {
      let err: HttpErrorResponse | undefined;
      service.verifyPayment('cs_test_pending').subscribe({ error: e => err = e });

      const req = httpMock.expectOne(`${API}/api/mixmaster-payment/verify`);
      req.flush(
        { success: false, feedback: { message: 'Paiement non confirmé.' } },
        { status: 400, statusText: 'Bad Request' },
      );
      expect(err!.status).toBe(400);
    });

  });

});
