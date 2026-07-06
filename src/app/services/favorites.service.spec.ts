import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { FavoritesService } from './favorites.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/favorites`;

describe('FavoritesService', () => {
  let service: FavoritesService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [FavoritesService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(FavoritesService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    service.clearCache();
  });

  it('should be created', () => expect(service).toBeTruthy());

  it('toggle() POSTs à /api/favorites/toggle/:id', () => {
    service.toggle(42).subscribe();
    const req = httpMock.expectOne(`${BASE}/toggle/42`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { action: 'added', is_favorite: true } });
  });

  it('toggle() met à jour le cache interne', () => {
    service.toggle(42).subscribe();
    httpMock.expectOne(`${BASE}/toggle/42`).flush({
      success: true,
      data: { action: 'added', is_favorite: true },
    });

    service.check(42).subscribe(res => {
      expect(res.is_favorite).toBe(true);
    });
    // cache hit → aucune requête HTTP supplémentaire
    httpMock.expectNone(`${BASE}/check/42`);
  });

  it('check() GET /api/favorites/check/:id si pas en cache', () => {
    service.check(99).subscribe();
    const req = httpMock.expectOne(`${BASE}/check/99`);
    expect(req.request.method).toBe('GET');
    req.flush({ is_favorite: false });
  });

  it('check() retourne la valeur du cache sans requête HTTP', () => {
    service.toggle(5).subscribe();
    httpMock.expectOne(`${BASE}/toggle/5`).flush({ success: true, data: { action: 'added', is_favorite: true } });

    service.check(5).subscribe(res => expect(res.is_favorite).toBe(true));
    httpMock.expectNone(`${BASE}/check/5`);
  });

  it('prefetch() GETs /api/favorites/check-batch', () => {
    service.prefetch([1, 2, 3]).subscribe();
    const req = httpMock.expectOne(`${BASE}/check-batch?ids=1,2,3`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { '1': true, '2': false, '3': true } });
  });

  it('prefetch() avec tableau vide ne fait pas de requête HTTP', () => {
    service.prefetch([]).subscribe();
    httpMock.expectNone(`${BASE}/check-batch`);
  });

  it('clearCache() vide le cache', () => {
    service.toggle(10).subscribe();
    httpMock.expectOne(`${BASE}/toggle/10`).flush({ success: true, data: { action: 'added', is_favorite: true } });

    service.clearCache();

    service.check(10).subscribe();
    httpMock.expectOne(`${BASE}/check/10`).flush({ is_favorite: true });
  });

  it('recordListening() POSTs à /api/favorites/listening/:id', () => {
    service.recordListening(7).subscribe();
    const req = httpMock.expectOne(`${BASE}/listening/7`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true });
  });
});
