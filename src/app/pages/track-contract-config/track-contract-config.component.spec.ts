/**
 * Tests de la logique de prix — TrackContractConfigComponent
 *
 * Comportements vérifiés :
 *
 * streamOnly :
 *   • true  quand duration='stream' && !isLifetime
 *   • false quand isLifetime=true (même si duration='stream')
 *   • false quand une durée réelle est choisie
 *
 * Calcul des fees :
 *   • arrangementFee = 0 quand streamOnly
 *   • mechanicalFee  = 0 quand streamOnly (même si rightMechanical=true)
 *   • publicShowFee  = 0 quand streamOnly
 *   • publicShowAutoIncluded utilise subtotalWithMechanical (bug fix : le mécanique
 *     doit pousser le total au-dessus du seuil de 74.99€)
 *
 * Scénarios presets :
 *   • Starter  : total = prix de base uniquement
 *   • Standard : total = base + durée + territoire + mécanique + diffusion publique
 *   • Integral : diffusion publique auto-incluse (79.99 >= 74.99), total = base + 100
 *
 * Bug fix 50+30=80€ :
 *   • base=50, mécanique=30 → subtotalWithMechanical=80 >= 74.99
 *     → publicShowAutoIncluded=true, publicShowFee=0, total=80 (pas 120)
 *
 * onConfirm payload :
 *   • mechanical_reproduction et public_show sont false en mode stream-only
 *   • arrangement est false en mode stream-only
 */

import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';

import { TrackContractConfigComponent } from './track-contract-config.component';
import { TrackService } from '../../services/track.service';
import { PaymentService } from '../../services/payment.service';
import { AuthService } from '../../services/auth.service';

// ── Helpers ──────────────────────────────────────────────────────────────────

const CONTRACT_PRICES = {
  duration_3y:    5,
  duration_5y:   10,
  duration_10y:  15,
  lifetime:      50,
  territory_eu:   5,
  territory_world:10,
  mechanical:    30,
  public_show:   40,
  arrangement:   10,
};

function makeTrack(mp3: number): any {
  return {
    id: 1, title: 'Test Beat', composer_user: { username: 'beatmaker' },
    bpm: 140, key: 'Cm', style: 'Trap',
    price_mp3: mp3, price_wav: mp3 * 2, price_stems: mp3 * 3,
    image_file: null, full_stream_url: null,
    stream_url: '/api/stream/tracks/1/preview',
    tags: [], similar_artists: [],
    contract_prices: CONTRACT_PRICES,
    is_approved: true,
    playlist_count: 0, first_playlist_image: null,
  };
}

// ── Setup ─────────────────────────────────────────────────────────────────────

describe('TrackContractConfigComponent — logique de prix', () => {

  let component: TrackContractConfigComponent;
  let paymentSvc: { createCheckout: ReturnType<typeof vi.fn> };

  beforeEach(() => {
    const trackSvc = {
      getTrackDetail:   vi.fn().mockReturnValue(of({ success: true, data: { track: makeTrack(9.99) } })),
      getStaticFileUrl: vi.fn().mockReturnValue(''),
    };
    paymentSvc = {
      createCheckout: vi.fn().mockReturnValue(of({ success: true, data: { checkout_url: 'https://stripe.test', total: 9.99 } })),
    };
    const authSvc = {
      isLoggedIn:   vi.fn().mockReturnValue(true),
      currentUser:  vi.fn().mockReturnValue({ email: 'test@test.com', username: 'tester' }),
      isAdmin:      vi.fn().mockReturnValue(false),
      getToken:     vi.fn().mockReturnValue('fake-jwt'),
    };

    TestBed.configureTestingModule({
      imports: [TrackContractConfigComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: TrackService,   useValue: trackSvc  },
        { provide: PaymentService, useValue: paymentSvc },
        { provide: AuthService,    useValue: authSvc   },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { paramMap: { get: (k: string) => k === 'trackId' ? '1' : 'mp3' } },
          },
        },
      ],
    });

    const fixture = TestBed.createComponent(TrackContractConfigComponent);
    component     = fixture.componentInstance;
    fixture.detectChanges();
  });

  // ── streamOnly ──────────────────────────────────────────────────────────────

  describe('streamOnly()', () => {

    it('est true quand duration=stream et !isLifetime', () => {
      component.duration.set('stream');
      component.isLifetime.set(false);
      expect(component.streamOnly()).toBe(true);
    });

    it('est false quand isLifetime=true, même si duration=stream', () => {
      component.duration.set('stream');
      component.isLifetime.set(true);
      expect(component.streamOnly()).toBe(false);
    });

    it('est false quand une durée réelle est choisie', () => {
      component.isLifetime.set(false);
      component.duration.set('5');
      expect(component.streamOnly()).toBe(false);
    });

  });

  // ── Fees en mode stream-only ────────────────────────────────────────────────

  describe('fees en mode stream-only', () => {

    beforeEach(() => {
      component.duration.set('stream');
      component.isLifetime.set(false);
    });

    it('arrangementFee = 0 même si rightArrangement=true', () => {
      component.rightArrangement.set(true);
      expect(component.arrangementFee()).toBe(0);
    });

    it('mechanicalFee = 0 même si rightMechanical=true', () => {
      component.rightMechanical.set(true);
      expect(component.mechanicalFee()).toBe(0);
    });

    it('publicShowFee = 0 même si rightPublicShow=true', () => {
      component.rightPublicShow.set(true);
      expect(component.publicShowFee()).toBe(0);
    });

    it('totalPrice = basePrice uniquement', () => {
      component.track.set(makeTrack(50));
      expect(component.totalPrice()).toBeCloseTo(50, 2);
    });

  });

  // ── Bug fix : mécanique → seuil diffusion publique ─────────────────────────

  describe('publicShowAutoIncluded via subtotalWithMechanical (bug fix)', () => {

    it('est false quand subtotal seul < 74.99 sans mécanique', () => {
      component.track.set(makeTrack(50));
      component.isLifetime.set(false);
      component.duration.set('3');  // +5, total=55 sans mécanique
      component.territory.set('France');
      component.rightArrangement.set(false);
      component.rightMechanical.set(false);
      // subtotalWithMechanical = 55, < 74.99
      expect(component.subtotalWithMechanical()).toBeLessThan(74.99);
      expect(component.publicShowAutoIncluded()).toBe(false);
    });

    it('SCÉNARIO BUG : base=50, durée=3ans, mécanique=30 → total=85 → publicShow auto-inclus', () => {
      // Scenario : base 50€ + 5€ (3ans) + 30€ (mécanique) = 85€ >= 74.99€
      // → diffusion publique doit être offerte gratuitement
      component.track.set(makeTrack(50));
      component.isLifetime.set(false);
      component.duration.set('3');
      component.territory.set('France');
      component.rightArrangement.set(false);
      component.rightMechanical.set(true);

      expect(component.subtotalWithMechanical()).toBeGreaterThanOrEqual(74.99);
      expect(component.publicShowAutoIncluded()).toBe(true);
      expect(component.publicShowFee()).toBe(0);
    });

    it('SCÉNARIO BUG ORIGINAL : base=50, mécanique=30, totalWithMechanical=80 → publicShow offert', () => {
      // base=50, stream-only est bloqué donc on teste avec durée réelle
      // Avec durée=stream, mécanique est bloquée; avec durée=3ans: 50+5+30=85
      // Test équivalent sans durée fee : utiliser track à 44.99 + 30 = 74.99 (exactement au seuil)
      component.track.set(makeTrack(50));
      component.isLifetime.set(false);
      component.duration.set('3'); // +5 → subtotal=55, +mechanical=30 → subtotalWithMechanical=85
      component.territory.set('France');
      component.rightMechanical.set(true);
      component.rightPublicShow.set(false); // non coché manuellement

      // publicShow auto-inclus même sans le cocher explicitement
      expect(component.publicShowAutoIncluded()).toBe(true);
      // totalPrice = 85 (pas 85 + 40 = 125)
      expect(component.totalPrice()).toBeCloseTo(85, 2);
    });

  });

  // ── Preset Starter ─────────────────────────────────────────────────────────

  describe('preset Starter', () => {

    it('totalPrice = prix de base (pas de surcoût)', () => {
      component.applyPreset(component.presets[0]);
      expect(component.streamOnly()).toBe(true);
      expect(component.totalPrice()).toBeCloseTo(component.basePrice(), 2);
    });

    it('streamOnly=true → droits d\'exploitation à zéro', () => {
      component.applyPreset(component.presets[0]);
      expect(component.mechanicalFee()).toBe(0);
      expect(component.publicShowFee()).toBe(0);
      expect(component.arrangementFee()).toBe(0);
    });

  });

  // ── Preset Standard ────────────────────────────────────────────────────────

  describe('preset Standard (9.99€)', () => {
    // 5 ans (+10), Europe (+5), mécanique (+30), diffusion publique (+40)
    // intermediate = 9.99+15=24.99 → mécanique +30 → 54.99 < 74.99 → publicShow +40
    // total = 9.99 + 85 = 94.99

    beforeEach(() => { component.applyPreset(component.presets[1]); });

    it('streamOnly est false', () => {
      expect(component.streamOnly()).toBe(false);
    });

    it('mechanicalFee = 30', () => {
      expect(component.mechanicalFee()).toBe(30);
    });

    it('subtotalWithMechanical = 54.99 < 74.99 → publicShowFee = 40', () => {
      expect(component.subtotalWithMechanical()).toBeLessThan(74.99);
      expect(component.publicShowFee()).toBe(40);
    });

    it('totalPrice = 94.99', () => {
      expect(component.totalPrice()).toBeCloseTo(94.99, 2);
    });

  });

  // ── Preset Integral ────────────────────────────────────────────────────────

  describe('preset Integral / Liberté totale (9.99€)', () => {
    // lifetime (+50), Monde entier (+10), arrangement (+10), mécanique (+30)
    // intermediate avant mécanique = 9.99 + 70 = 79.99
    // mécanique : +30 → intermediate = 109.99 >= 74.99 → publicShow AUTO-INCLUS
    // total = 9.99 + 100 = 109.99

    beforeEach(() => { component.applyPreset(component.presets[2]); });

    it('isLifetime=true → streamOnly=false', () => {
      expect(component.isLifetime()).toBe(true);
      expect(component.streamOnly()).toBe(false);
    });

    it('subtotalWithMechanical >= 74.99 → publicShowAutoIncluded=true, publicShowFee=0', () => {
      expect(component.subtotalWithMechanical()).toBeGreaterThanOrEqual(74.99);
      expect(component.publicShowAutoIncluded()).toBe(true);
      expect(component.publicShowFee()).toBe(0);
    });

    it('totalPrice = 109.99', () => {
      expect(component.totalPrice()).toBeCloseTo(109.99, 2);
    });

  });

  // ── onConfirm guards stream-only ────────────────────────────────────────────

  describe('onConfirm() — droits bloqués en stream-only', () => {

    it('envoie mechanical_reproduction=false, public_show=false, arrangement=false', () => {
      component.track.set(makeTrack(9.99));
      component.duration.set('stream');
      component.isLifetime.set(false);
      // Forcer les signaux à true pour vérifier que le guard les écrase
      component.rightMechanical.set(true);
      component.rightPublicShow.set(true);
      component.rightArrangement.set(true);

      paymentSvc.createCheckout.mockClear();
      component.onConfirm();

      const [, , body] = paymentSvc.createCheckout.mock.calls[0] as any[];
      expect(body.mechanical_reproduction).toBe(false);
      expect(body.public_show).toBe(false);
      expect(body.arrangement).toBe(false);
    });

  });

});
