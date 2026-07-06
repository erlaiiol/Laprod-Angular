import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { ToplineService } from './topline.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/toplines`;

describe('ToplineService', () => {
  let service: ToplineService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [ToplineService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(ToplineService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getTrackToplines() GETs /api/toplines/track/:id', () => {
    service.getTrackToplines(5).subscribe();
    const req = httpMock.expectOne(`${BASE}/track/5`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { toplines: [] } });
  });

  it('getMyToplines() GETs /api/toplines/my/:id', () => {
    service.getMyToplines(7).subscribe();
    const req = httpMock.expectOne(`${BASE}/my/7`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { toplines: [] } });
  });

  it('uploadTopline() POSTs à /api/toplines/upload', () => {
    service.uploadTopline(new FormData()).subscribe();
    const req = httpMock.expectOne(`${BASE}/upload`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { job_id: 'abc' } });
  });

  it('uploadTopline() ajoute X-Guest-Session si guestSessionId fourni', () => {
    service.uploadTopline(new FormData(), 'guest-uuid-123').subscribe();
    const req = httpMock.expectOne(`${BASE}/upload`);
    expect(req.request.headers.get('X-Guest-Session')).toBe('guest-uuid-123');
    req.flush({ success: true, data: { job_id: 'abc' } });
  });

  it('claimGuestToplines() POSTs à /api/toplines/claim', () => {
    service.claimGuestToplines('session-id').subscribe();
    const req = httpMock.expectOne(`${BASE}/claim`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.guest_session_id).toBe('session-id');
    req.flush({ success: true, data: { claimed: 1 } });
  });

  it('publishTopline() POSTs à /api/toplines/:id/publish', () => {
    service.publishTopline(10).subscribe();
    const req = httpMock.expectOne(`${BASE}/10/publish`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true });
  });

  it('unpublishTopline() POSTs à /api/toplines/:id/unpublish', () => {
    service.unpublishTopline(10).subscribe();
    const req = httpMock.expectOne(`${BASE}/10/unpublish`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true });
  });

  it('deleteTopline() DELETE à /api/toplines/:id', () => {
    service.deleteTopline(10).subscribe();
    const req = httpMock.expectOne(`${BASE}/10`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true });
  });

  it('updateDescription() PATCH à /api/toplines/:id', () => {
    service.updateDescription(10, 'Ma description').subscribe();
    const req = httpMock.expectOne(`${BASE}/10`);
    expect(req.request.method).toBe('PATCH');
    expect(req.request.body.description).toBe('Ma description');
    req.flush({ success: true });
  });
});
