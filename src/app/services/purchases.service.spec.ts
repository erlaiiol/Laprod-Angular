import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { PurchasesService } from './purchases.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/purchases`;

describe('PurchasesService', () => {
  let service: PurchasesService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [PurchasesService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(PurchasesService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getMyPurchases() GETs /api/purchases', () => {
    service.getMyPurchases().subscribe();
    const req = httpMock.expectOne(BASE);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { purchases: [], total_spent: 0, mm_orders: [], mm_total_spent: 0 } });
  });

  it('getMyPurchases() retourne les données correctement', () => {
    let result: any;
    service.getMyPurchases().subscribe(res => result = res.data);
    httpMock.expectOne(BASE).flush({
      success: true,
      data: { purchases: [{ id: 1, format: 'mp3' }], total_spent: 9.99, mm_orders: [], mm_total_spent: 0 },
    });
    expect(result.purchases.length).toBe(1);
    expect(result.total_spent).toBe(9.99);
  });
});
