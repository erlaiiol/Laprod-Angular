import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { PlaylistService } from './playlist.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/playlists`;

describe('PlaylistService', () => {
  let service: PlaylistService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [PlaylistService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(PlaylistService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getMyPlaylists() GETs /api/playlists/my', () => {
    service.getMyPlaylists().subscribe();
    const req = httpMock.expectOne(`${BASE}/my`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: [] });
  });

  it('getPlaylist() GETs /api/playlists/:id', () => {
    service.getPlaylist(42).subscribe();
    const req = httpMock.expectOne(`${BASE}/42`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { id: 42, title: 'Test', tracks: [] } });
  });

  it('createPlaylist() POSTs FormData to /api/playlists', () => {
    const fd = new FormData();
    fd.append('title', 'New PL');
    service.createPlaylist(fd).subscribe();
    const req = httpMock.expectOne(BASE);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { id: 1, title: 'New PL', track_count: 0, beatmaker_username: 'bm', image_file: null, created_at: null } });
  });

  it('updatePlaylist() PUTs FormData to /api/playlists/:id', () => {
    const fd = new FormData();
    fd.append('title', 'Updated');
    service.updatePlaylist(1, fd).subscribe();
    const req = httpMock.expectOne(`${BASE}/1`);
    expect(req.request.method).toBe('PUT');
    req.flush({ success: true, data: { id: 1, title: 'Updated', track_count: 0, beatmaker_username: 'bm', image_file: null, created_at: null } });
  });

  it('deletePlaylist() DELETEs /api/playlists/:id', () => {
    service.deletePlaylist(5).subscribe();
    const req = httpMock.expectOne(`${BASE}/5`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true });
  });

  it('addTrack() POSTs {track_id} to /api/playlists/:id/tracks', () => {
    service.addTrack(1, 99).subscribe();
    const req = httpMock.expectOne(`${BASE}/1/tracks`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ track_id: 99 });
    req.flush({ success: true });
  });

  it('removeTrack() DELETEs /api/playlists/:id/tracks/:trackId', () => {
    service.removeTrack(1, 99).subscribe();
    const req = httpMock.expectOne(`${BASE}/1/tracks/99`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true });
  });

  it('getByBeatmaker() GETs /api/playlists/by-beatmaker/:username', () => {
    service.getByBeatmaker('testuser').subscribe();
    const req = httpMock.expectOne(`${BASE}/by-beatmaker/testuser`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: [] });
  });

  it('getContaining() GETs /api/playlists/containing/:trackId/by/:username', () => {
    service.getContaining(7, 'testuser').subscribe();
    const req = httpMock.expectOne(`${BASE}/containing/7/by/testuser`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: [1, 3] });
  });
});
