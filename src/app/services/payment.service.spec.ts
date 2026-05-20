import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { PaymentService } from './payment.service';
import { environment } from '../../environments/environment';

const BASE_URL = `${environment.apiUrl}/api/track-payment`;

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
    service = TestBed.inject(PaymentService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('createCheckout() POSTs to /api/track-payment/track/:id/:format/checkout', () => {
    service.createCheckout(10, 'mp3', {}).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/track/10/mp3/checkout`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/test', total: 9.99 } });
  });

  it('createCheckout() envoie les options dans le body', () => {
    const options = { is_lifetime: true, territory: 'France' as const };
    service.createCheckout(5, 'wav', options).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/track/5/wav/checkout`);
    expect(req.request.body).toEqual(options);
    req.flush({ success: true, data: { checkout_url: 'https://checkout.stripe.com/test', total: 19.99 } });
  });

  it('verifyPayment() POSTs session_id to /api/track-payment/verify', () => {
    service.verifyPayment('cs_test_abc123').subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/verify`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { purchase_id: 1 } });
  });

  it('verifyPayment() envoie le body correct { session_id }', () => {
    service.verifyPayment('cs_test_xyz').subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/verify`);
    expect(req.request.body).toEqual({ session_id: 'cs_test_xyz' });
    req.flush({ success: true, data: { purchase_id: 2 } });
  });
});
