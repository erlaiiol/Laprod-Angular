import { TestBed, fakeAsync, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { PlayerService } from './player.service';
import { AuthService } from './auth.service';
import { environment } from '../../environments/environment';
import { Track } from './track.service';

const API = environment.apiUrl;

const mockTrack: Track = {
  id:              1,
  title:           'Mon Beat',
  stream_url:      '/stream/1',
  full_stream_url: null,
  image_file:      '',
  composer_user:   { username: 'beatmaker' },
  bpm:             140,
  key:             'Am',
  style:           'Trap',
  price_mp3:       10,
  tags:            [],
  is_approved:         true,
  playlist_count:      0,
  first_playlist_image: null,
};

describe('PlayerService', () => {
  let service: PlayerService;
  let httpMock: HttpTestingController;

  const authStub = { getToken: () => 'tok', isLoggedIn: () => true };

  beforeEach(() => {
    localStorage.removeItem('access_token');
    TestBed.configureTestingModule({
      providers: [
        PlayerService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authStub },
      ],
    });
    service  = TestBed.inject(PlayerService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    // absorb any outstanding requests (fire-and-forget in play())
    httpMock.match(() => true).forEach(r => r.flush({}));
    httpMock.verify();
  });

  it('should be created', () => expect(service).toBeTruthy());

  it('currentTrack() démarre à null', () => {
    expect(service.currentTrack()).toBeNull();
  });

  it('isPlaying() démarre à false', () => {
    expect(service.isPlaying()).toBe(false);
  });

  it('volume() démarre à 0.8', () => {
    expect(service.volume()).toBe(0.8);
  });

  it('setVolume() met à jour le signal volume', () => {
    service.setVolume(0.5);
    expect(service.volume()).toBe(0.5);
  });

  it('setVolume() est limité entre 0 et 1', () => {
    service.setVolume(-0.5);
    expect(service.volume()).toBe(0);
    service.setVolume(1.5);
    expect(service.volume()).toBe(1);
  });

  it('play() définit currentTrack', () => {
    service.play(mockTrack);
    expect(service.currentTrack()).toEqual(mockTrack);
    // absorber les requêtes fire-and-forget
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('play() définit playOnReady à true', () => {
    service.play(mockTrack);
    expect(service.playOnReady).toBe(true);
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('play() efface le contexte viewingMixOrder', () => {
    service.play(mockTrack);
    expect(service.viewingMixOrder()).toBeNull();
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('close() réinitialise tous les signals', () => {
    service.play(mockTrack);
    httpMock.match(() => true).forEach(r => r.flush({}));

    service.close();
    expect(service.currentTrack()).toBeNull();
    expect(service.isPlaying()).toBe(false);
    expect(service.currentTime()).toBe(0);
    expect(service.duration()).toBe(0);
    expect(service.playOnReady).toBe(false);
  });

  it('buildAudioUrl() préfixe une url relative avec apiUrl', () => {
    const url = service.buildAudioUrl({ ...mockTrack, stream_url: '/stream/1' });
    expect(url).toBe(`${API}/stream/1`);
  });

  it('buildAudioUrl() retourne les url blob: et http telles quelles', () => {
    expect(service.buildAudioUrl({ ...mockTrack, stream_url: 'blob:abc' })).toBe('blob:abc');
    expect(service.buildAudioUrl({ ...mockTrack, stream_url: 'https://example.com/s' })).toBe('https://example.com/s');
  });

  it('buildAudioUrl() retourne \'\' si stream_url est vide', () => {
    expect(service.buildAudioUrl({ ...mockTrack, stream_url: '' })).toBe('');
  });

  it('play() bascule sur le titre entier (full_stream_url) quand disponible', () => {
    const full = { ...mockTrack, full_stream_url: '/stream/1/full' };
    service.play(full);
    expect(service.isPreviewSource()).toBe(false);
    expect(service.buildAudioUrl(full)).toBe(`${API}/stream/1/full`);
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('play() avec forcePreview reste sur stream_url même si full_stream_url existe', () => {
    const full = { ...mockTrack, full_stream_url: '/stream/1/full' };
    service.play(full, 'home', { forcePreview: true });
    expect(service.isPreviewSource()).toBe(true);
    expect(service.buildAudioUrl(full)).toBe(`${API}/stream/1`);
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('play() sans full_stream_url reste en isPreviewSource', () => {
    service.play(mockTrack);
    expect(service.isPreviewSource()).toBe(true);
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('playNext() GETs /api/tracks/random', () => {
    service.playNext();
    const req = httpMock.expectOne(r => r.url.includes('/api/tracks/random'));
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { track: mockTrack } });
    // absorb the play() fire-and-forget requests
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('playNext() ajoute exclude_id si un track est en cours', () => {
    service.play(mockTrack);
    httpMock.match(() => true).forEach(r => r.flush({}));

    service.playNext();
    const req = httpMock.expectOne(r => r.url.includes('/api/tracks/random'));
    expect(req.request.url).toContain('exclude_id=1');
    req.flush({ success: true, data: { track: mockTrack } });
    httpMock.match(() => true).forEach(r => r.flush({}));
  });

  it('seek() met à jour audioEl.currentTime', () => {
    service.seek(42);
    expect(service.audioEl.currentTime).toBe(42);
  });

  it('viewingTrack démarre à null', () => {
    expect(service.viewingTrack()).toBeNull();
  });
});
