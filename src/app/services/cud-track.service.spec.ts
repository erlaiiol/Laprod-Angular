import { TestBed } from '@angular/core/testing';
import { provideHttpClient, HttpRequest } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { CudTrackService, TrackData } from './cud-track.service';
import { environment } from '../../environments/environment';

const API = environment.apiUrl;

const minimalTrack: TrackData = {
  title: 'Mon Beat',
  bpm: 140,
  key: 'Am',
  style: 'Trap',
  price_mp3: 10,
  price_wav: 20,
};

describe('CudTrackService', () => {
  let service: CudTrackService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [CudTrackService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(CudTrackService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('postTrack() POSTs à /api/tracks/post avec observe:events', () => {
    service.postTrack(minimalTrack).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/post`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body instanceof FormData).toBe(true);
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' }, data: { job_id: 'j1', title: 'Mon Beat', image_url: null } });
  });

  it('postTrack() inclut les champs obligatoires dans le FormData', () => {
    service.postTrack(minimalTrack).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/post`);
    const fd: FormData = req.request.body;
    expect(fd.get('title')).toBe('Mon Beat');
    expect(fd.get('bpm')).toBe('140');
    expect(fd.get('key')).toBe('Am');
    expect(fd.get('style')).toBe('Trap');
    expect(fd.get('price_mp3')).toBe('10');
    expect(fd.get('price_wav')).toBe('20');
    req.flush({ success: true });
  });

  it('postTrack() inclut le fichier MP3 si fourni', () => {
    const file = new File(['audio'], 'beat.mp3', { type: 'audio/mpeg' });
    service.postTrack({ ...minimalTrack, file_mp3: file }).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/post`);
    const fd: FormData = req.request.body;
    expect(fd.get('file_mp3')).toBeTruthy();
    req.flush({ success: true });
  });

  it('putTrack() PUTs à /api/tracks/put/:id avec FormData', () => {
    service.putTrack(42, minimalTrack).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/put/42`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body instanceof FormData).toBe(true);
    expect((req.request.body as FormData).get('title')).toBe('Mon Beat');
    req.flush({ success: true, message: 'OK' });
  });

  it('putTrack() inclut regenerate_preview si défini', () => {
    service.putTrack(1, { ...minimalTrack, regenerate_preview: true }).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/put/1`);
    expect((req.request.body as FormData).get('regenerate_preview')).toBe('1');
    req.flush({ success: true });
  });

  it('deleteTrack() DELETE à /api/tracks/delete/:id', () => {
    service.deleteTrack(7).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/delete/7`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true });
  });

  it('validateAiSuggestion() PATCH à /api/tracks/:id/validate-suggestion', () => {
    service.validateAiSuggestion(3).subscribe();
    const req = httpMock.expectOne(`${API}/api/tracks/3/validate-suggestion`);
    expect(req.request.method).toBe('PATCH');
    req.flush({ success: true });
  });

  it('getUploadOptions() GETs /api/filters/tags/all', () => {
    service.getUploadOptions().subscribe();
    const req = httpMock.expectOne(`${API}/api/filters/tags/all`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, keys: [], styles: [], tags: [] });
  });
});
