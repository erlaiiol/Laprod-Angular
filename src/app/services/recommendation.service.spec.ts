import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { RecommendationService } from './recommendation.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/recommendations`;

describe('RecommendationService', () => {
  let service: RecommendationService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [RecommendationService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(RecommendationService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getTracks() GETs /api/recommendations/tracks sans paramètre', () => {
    service.getTracks().subscribe();
    const req = httpMock.expectOne(`${BASE}/tracks`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { tracks: [], is_personalized: false } });
  });

  it('getTracks() ajoute tag_category en param si fourni', () => {
    service.getTracks('Ambiance').subscribe();
    const req = httpMock.expectOne(r => r.url === `${BASE}/tracks`);
    expect(req.request.params.get('tag_category')).toBe('Ambiance');
    req.flush({ success: true, data: { tracks: [], is_personalized: true } });
  });

  it('getTracks() ne passe pas tag_category si null', () => {
    service.getTracks(null).subscribe();
    const req = httpMock.expectOne(`${BASE}/tracks`);
    expect(req.request.params.has('tag_category')).toBe(false);
    req.flush({ success: true, data: { tracks: [], is_personalized: false } });
  });

  it('getMyProfile() GETs /api/recommendations/my-profile', () => {
    service.getMyProfile().subscribe();
    const req = httpMock.expectOne(`${BASE}/my-profile`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { profile: {}, listen_event_count: 0 } });
  });
});
