import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { TrackService } from './track.service';
import { environment } from '../../environments/environment';

const BASE_URL = `${environment.apiUrl}/api/tracks`;

describe('TrackService', () => {
  let service: TrackService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        TrackService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service = TestBed.inject(TrackService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('getTracks() GETs /api/tracks/tracks', () => {
    service.getTracks().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/tracks`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { tracks: [], pagination: { page: 1, per_page: 20, total: 0, pages: 1 } } });
  });

  it('getTracks() inclut les filtres comme query params', () => {
    service.getTracks({ bpm_min: 80 }).subscribe();

    const req = httpMock.expectOne((r) => r.url === `${BASE_URL}/tracks`);
    expect(req.request.params.get('bpm_min')).toBe('80');
    req.flush({ success: true, data: { tracks: [], pagination: { page: 1, per_page: 20, total: 0, pages: 1 } } });
  });

  it('getTrack(id) GETs /api/tracks/track/:id', () => {
    service.getTrack(42).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/track/42`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { track: {} } });
  });

  it('getRandomTrack() GETs /api/tracks/random', () => {
    service.getRandomTrack().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/random`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { track: {} } });
  });

  it('getRandomTrack() exclut l\'id courant si fourni', () => {
    service.getRandomTrack(42).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/random?exclude_id=42`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { track: {} } });
  });
});
