import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

/**
 * Factorisation du boilerplate HttpTestingController répété dans chaque service spec.
 *
 * Usage :
 *   const { getHttpMock } = setupHttpTesting([MyService, { provide: DEP, useValue: mock }]);
 *
 *   it('does X', () => {
 *     service.callApi().subscribe();
 *     const req = getHttpMock().expectOne('/api/endpoint');
 *     expect(req.request.method).toBe('POST');
 *     req.flush({ success: true, data: {...} });
 *   });
 */
export function setupHttpTesting(additionalProviders: any[] = []) {
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        ...additionalProviders,
      ],
    });
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  return {
    getHttpMock: () => httpMock,
  };
}
