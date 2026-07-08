/**
 * Tests — TrackDetailComponent : détection de licences et dialog de confirmation
 *
 * Comportements vérifiés :
 *   • ownedLicense() retourne null quand aucune licence active pour ce format
 *   • ownedLicense() retourne l'objet OwnedLicense pour un format possédé
 *   • requestBuy() navigue directement si aucune licence existante
 *   • requestBuy() ouvre le dialog de confirmation si une licence active existe
 *   • cancelBuy() ferme le dialog sans naviguer
 *   • proceedBuy() ferme le dialog et navigue vers /contract/:id/:format
 */

import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';

import { TrackDetailComponent } from './track-detail.component';
import { TrackService } from '../../services/track.service';
import { AuthService } from '../../services/auth.service';

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeTrack(ownedLicenses: Record<string, any> = {}): any {
  return {
    id: 42,
    title: 'Test Beat',
    composer_user: { id: 99, username: 'beatmaker', profile_image: null },
    stream_url: '/api/stream/tracks/42/preview',
    full_stream_url: null,
    image_file: null,
    bpm: 130,
    key: 'A minor',
    style: 'Trap',
    price_mp3: 9.99,
    price_wav: 19.99,
    price_stems: 49.99,
    file_wav: 'beat.wav',
    file_stems: 'beat.zip',
    created_at: null,
    tags: [],
    similar_artists: [],
    toplines: [],
    my_toplines: [],
    is_approved: true,
    is_exclusive_sold: false,
    playlist_count: 0,
    first_playlist_image: null,
    owned_licenses: ownedLicenses,
  };
}

const OWNED_MP3 = {
  purchase_id: 7,
  is_lifetime: false,
  duration_years: null,
  expires_at: null,
  license_status: 'active' as const,
};

// ── Setup ─────────────────────────────────────────────────────────────────────

describe('TrackDetailComponent — licences et confirmation', () => {

  let component: TrackDetailComponent;
  let router: { navigate: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    router = { navigate: vi.fn() };

    const trackSvc = {
      getTrackDetail:   vi.fn().mockReturnValue(of({ success: true, data: { track: makeTrack() } })),
      getStaticFileUrl: vi.fn().mockReturnValue(''),
      recordView:       vi.fn(),
      darkenColor:      vi.fn().mockReturnValue('#000'),
    };
    const authSvc = {
      isLoggedIn:   vi.fn().mockReturnValue(true),
      currentUser:  vi.fn().mockReturnValue({ id: 1, username: 'artist', roles: {} }),
      getToken:     vi.fn().mockReturnValue('fake-jwt'),
    };

    TestBed.configureTestingModule({
      imports: [TrackDetailComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: TrackService, useValue: trackSvc },
        { provide: AuthService,  useValue: authSvc  },
        { provide: Router,       useValue: router   },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap:      { get: () => '42' },
              queryParamMap: { get: () => null },
            },
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(TrackDetailComponent);
    component     = fixture.componentInstance;
    fixture.detectChanges();
  });

  // ── ownedLicense() ──────────────────────────────────────────────────────────

  describe('ownedLicense()', () => {

    it('retourne null quand aucune licence pour ce format', () => {
      component.track.set(makeTrack({}));
      expect(component.ownedLicense('mp3')).toBeNull();
    });

    it('retourne la licence quand le format est possédé', () => {
      component.track.set(makeTrack({ mp3: OWNED_MP3 }));
      const lic = component.ownedLicense('mp3');
      expect(lic).not.toBeNull();
      expect(lic!.purchase_id).toBe(7);
    });

    it('retourne null pour un format non possédé même si un autre l\'est', () => {
      component.track.set(makeTrack({ mp3: OWNED_MP3 }));
      expect(component.ownedLicense('wav')).toBeNull();
      expect(component.ownedLicense('stems')).toBeNull();
    });

  });

  // ── requestBuy() ────────────────────────────────────────────────────────────

  describe('requestBuy()', () => {

    it('navigue directement si aucune licence active', () => {
      component.track.set(makeTrack({}));
      component.requestBuy('mp3');
      expect(router.navigate).toHaveBeenCalledWith(['/contract', 42, 'mp3']);
      expect(component.confirmFormat()).toBeNull();
    });

    it("ouvre le dialog de confirmation si une licence active existe", () => {
      component.track.set(makeTrack({ mp3: OWNED_MP3 }));
      component.requestBuy('mp3');
      expect(component.confirmFormat()).toBe('mp3');
      expect(router.navigate).not.toHaveBeenCalled();
    });

  });

  // ── cancelBuy() ─────────────────────────────────────────────────────────────

  describe('cancelBuy()', () => {

    it('ferme le dialog sans naviguer', () => {
      component.track.set(makeTrack({ mp3: OWNED_MP3 }));
      component.confirmFormat.set('mp3');
      component.cancelBuy();
      expect(component.confirmFormat()).toBeNull();
      expect(router.navigate).not.toHaveBeenCalled();
    });

  });

  // ── proceedBuy() ────────────────────────────────────────────────────────────

  describe('proceedBuy()', () => {

    it('ferme le dialog et navigue vers /contract/:id/:format', () => {
      component.track.set(makeTrack({ mp3: OWNED_MP3 }));
      component.confirmFormat.set('mp3');
      component.proceedBuy();
      expect(component.confirmFormat()).toBeNull();
      expect(router.navigate).toHaveBeenCalledWith(['/contract', 42, 'mp3']);
    });

    it('ne navigue pas si confirmFormat est null', () => {
      component.track.set(makeTrack({ mp3: OWNED_MP3 }));
      component.confirmFormat.set(null);
      component.proceedBuy();
      expect(router.navigate).not.toHaveBeenCalled();
    });

  });

});
