import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ClipShareService, clipCaption, clipTrackLink, shareMedium } from './clip-share.service';
import { CLIP_CAMERA } from './clip-camera-plugin';
import { AuthService } from './auth.service';

describe('clip-share — légende et attribution', () => {
  it('lien absolu vers le beat, avec UTM par plateforme', () => {
    expect(clipTrackLink(42, 'tiktok'))
      .toBe('https://laprod.net/track/42?utm_source=clip&utm_medium=tiktok&utm_campaign=mode_clip');
  });

  it('légende : crédit beatmaker + lien', () => {
    const c = clipCaption('kbeats', 42);
    expect(c).toContain('@kbeats');
    expect(c).toContain('https://laprod.net/track/42');
  });

  it('cible de partage reconnue d\'après l\'identifiant système', () => {
    expect(shareMedium('com.burbn.instagram.shareextension')).toBe('instagram');
    expect(shareMedium('com.zhiliaoapp.musically')).toBe('tiktok');
    expect(shareMedium('com.google.ios.youtube.ShareExtension')).toBe('youtube');
    expect(shareMedium('com.apple.UIKit.activity.Message')).toBe('sms');
    expect(shareMedium(undefined)).toBe('share');
  });
});

describe('ClipShareService', () => {
  const params = { path: 'file:///c.mp4', trackId: 7, clipUid: '1b4e28ba-2fa1-11d2-883f-0016d3cca427', beatmaker: 'kbeats', mode: 'rec', durationSec: 30.4 };
  let cam: { share: ReturnType<typeof vi.fn>; canShareTo: ReturnType<typeof vi.fn>; shareTo: ReturnType<typeof vi.fn> };
  let http: HttpTestingController;
  let svc: ClipShareService;

  function setup(loggedIn = true) {
    cam = {
      share: vi.fn(async () => ({ completed: true, target: 'com.zhiliaoapp.musically' })),
      canShareTo: vi.fn(async () => ({ available: true })),
      shareTo: vi.fn(async () => {}),
    };
    Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(async () => {}) }, configurable: true });
    TestBed.configureTestingModule({
      providers: [
        ClipShareService,
        provideHttpClient(), provideHttpClientTesting(),
        { provide: CLIP_CAMERA, useValue: cam },
        { provide: AuthService, useValue: { isLoggedIn: () => loggedIn } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    svc = TestBed.inject(ClipShareService);
  }

  afterEach(() => TestBed.resetTestingModule());

  it('partage le FICHIER, copie la légende et compte le partage', async () => {
    setup();
    await svc.shareSystem(params);
    expect(cam.share).toHaveBeenCalledWith(expect.objectContaining({ path: 'file:///c.mp4' }));
    expect(svc.captionCopied()).toBe(true);
    const req = http.expectOne('/api/clips/events');
    expect(req.request.body).toEqual({
      track_id: 7, clip_uid: params.clipUid, mode: 'rec', action: 'shared', duration_s: 30, target: 'tiktok',
    });
    req.flush({ success: true });
  });

  it('feuille fermée sans partager : rien n\'est compté', async () => {
    setup();
    cam.share.mockResolvedValue({ completed: false });
    await svc.shareSystem(params);
    http.expectNone('/api/clips/events');
    expect(svc.shared()).toBe(false);
  });

  it('non connecté : aucun envoi', () => {
    setup(false);
    svc.track('saved', params);
    http.expectNone('/api/clips/events');
  });

  it('raccourcis masqués tant qu\'ils ne sont pas configurés', async () => {
    setup();
    await svc.loadShortcuts();
    expect(svc.shortcuts()).toEqual([]);
    expect(cam.canShareTo).not.toHaveBeenCalled();
  });
});
