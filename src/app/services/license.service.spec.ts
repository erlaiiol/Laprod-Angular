import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { LicenseService } from './license.service';
import { environment } from '../../environments/environment';

const API = environment.apiUrl;

describe('LicenseService', () => {
  let service: LicenseService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [LicenseService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(LicenseService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getLicenses() GETs /api/licenses', () => {
    service.getLicenses().subscribe();
    const req = httpMock.expectOne(`${API}/api/licenses`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { licenses: [] } });
  });

  it('getLicense() GETs /api/licenses/:id', () => {
    service.getLicense(7).subscribe();
    const req = httpMock.expectOne(`${API}/api/licenses/7`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: {} });
  });

  it('getComposerLicenses() GETs /api/composer/licenses', () => {
    service.getComposerLicenses().subscribe();
    const req = httpMock.expectOne(`${API}/api/composer/licenses`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { licenses: [], total_revenue: 0, exclusive: [] } });
  });

  it('initiateRenewal() POSTs à /api/track-payment/track/:trackId/renew/:purchaseId', () => {
    service.initiateRenewal(1, 2, {
      is_lifetime: true,
      legal_terms_accepted: true,
      withdrawal_right_waived: true,
    }).subscribe();
    const req = httpMock.expectOne(`${API}/api/track-payment/track/1/renew/2`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.is_lifetime).toBe(true);
    expect(req.request.body.legal_terms_accepted).toBe(true);
    expect(req.request.body.withdrawal_right_waived).toBe(true);
    req.flush({ success: true, data: { checkout_url: 'https://stripe.com', total: 99 } });
  });

  it('verifyRenewal() POSTs à /api/track-payment/verify-renewal', () => {
    service.verifyRenewal('sess_abc').subscribe();
    const req = httpMock.expectOne(`${API}/api/track-payment/verify-renewal`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.session_id).toBe('sess_abc');
    req.flush({ success: true, data: { purchase_id: 5 } });
  });

  it('downloadContract() retourne l\'URL du contrat', () => {
    const url = service.downloadContract(3);
    expect(url).toBe(`${API}/api/licenses/3/contract`);
  });

  // -- daysRemaining() --

  it('daysRemaining() retourne null si expiresAt est null (lifetime)', () => {
    expect(service.daysRemaining(null)).toBeNull();
  });

  it('daysRemaining() retourne un nombre positif pour une date future', () => {
    const future = new Date(Date.now() + 10 * 24 * 3600 * 1000).toISOString();
    expect(service.daysRemaining(future)!).toBeGreaterThan(0);
  });

  it('daysRemaining() retourne un nombre négatif pour une date passée', () => {
    const past = new Date(Date.now() - 5 * 24 * 3600 * 1000).toISOString();
    expect(service.daysRemaining(past)!).toBeLessThan(0);
  });

  // -- urgency() --

  it('urgency() retourne "lifetime" si days est null', () => {
    expect(service.urgency(null)).toBe('lifetime');
  });

  it('urgency() retourne "expired" si days < 0', () => {
    expect(service.urgency(-1)).toBe('expired');
  });

  it('urgency() retourne "urgent" si days <= 7', () => {
    expect(service.urgency(5)).toBe('urgent');
  });

  it('urgency() retourne "soon" si days <= 30', () => {
    expect(service.urgency(20)).toBe('soon');
  });

  it('urgency() retourne "ok" si days > 30', () => {
    expect(service.urgency(60)).toBe('ok');
  });
});
