import { describe, it, expect, beforeEach, vi } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { signal, computed } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ToplineRecorderComponent } from './topline-recorder.component';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { ToplineService } from '../../services/topline.service';
import { ToplineStatusService } from '../../services/topline-status.service';
import { GuestToplineService } from '../../services/guest-topline.service';

// Studio web : transport · timeline · barre d'outils commune avec l'app.

class PlayerStub {
  currentTrack      = signal<any>(null);
  isPlaying         = signal(false);
  currentTime       = signal(0);
  duration          = signal(0);
  volume            = signal(0.8);
  isReferenceSource = signal(false);
  audioEl = { currentTime: 0, addEventListener: vi.fn(), removeEventListener: vi.fn() } as any;
  play   = vi.fn((track: any, _src?: string, opts: any = {}) => {
    this.currentTrack.set(track);
    this.isReferenceSource.set(!!opts.referenceSource);
  });
  pause  = vi.fn(() => this.isPlaying.set(false));
  resume = vi.fn(() => this.isPlaying.set(true));
  seek   = vi.fn((t: number) => this.currentTime.set(t));
  togglePlay = vi.fn();
  setVolume  = vi.fn();
}

class AuthStub {
  user = signal<any>(null);
  currentUser = this.user;
  isLoggedIn = computed(() => this.user() !== null);
  getToken() { return 'tok'; }
}

class GuestStub {
  sessionId = signal('guest-1');
  remainingAttempts = signal(3);
  hasAttemptsLeft = computed(() => this.remainingAttempts() > 0);
}

class StatusStub {
  toplineId = signal<string | null>(null);
  status    = signal<string | null>(null);
}

const TRACK: any = { id: 7, title: 'Beat', bpm: 140, key: 'Am', image_file: null };

let player: PlayerStub;
let auth: AuthStub;

async function setup() {
  await TestBed.configureTestingModule({
    imports: [ToplineRecorderComponent],
    providers: [
      provideRouter([]),
      provideHttpClient(),
      provideHttpClientTesting(),
      { provide: PlayerService,        useFactory: () => (player = new PlayerStub()) },
      { provide: AuthService,          useFactory: () => (auth = new AuthStub()) },
      { provide: GuestToplineService,  useClass: GuestStub },
      { provide: ToplineStatusService, useClass: StatusStub },
      { provide: ToplineService,       useValue: { publishTopline: vi.fn(), unpublishTopline: vi.fn(), deleteTopline: vi.fn(), uploadTopline: vi.fn() } },
    ],
  }).compileComponents();
  const fixture = TestBed.createComponent(ToplineRecorderComponent);
  const c = fixture.componentInstance;
  c.track = TRACK;
  fixture.detectChanges();
  return { fixture, c };
}

/** Simule un clic à une fraction donnée de la largeur de la timeline. */
function clickAt(c: ToplineRecorderComponent, ratio: number, lane: 'beat' | 'voice' = 'beat') {
  c.tlContentRef = { nativeElement: { getBoundingClientRect: () => ({ left: 100, width: 600 }) } } as any;
  c.onLaneClick({ clientX: 100 + 600 * ratio } as MouseEvent, lane);
}

describe('ToplineRecorderComponent (studio web)', () => {
  beforeEach(() => { localStorage.clear(); TestBed.resetTestingModule(); });

  it('rend la barre d\'outils commune avec les 4 boutons de l\'app', async () => {
    const { fixture } = await setup();
    const labels = [...fixture.nativeElement.querySelectorAll('.stb-label')].map((e: Element) => e.textContent!.trim());
    expect(labels).toEqual(['Enregistrer', 'Micro & monito', 'Publier', 'Télécharger']);
  });

  it('affiche l\'incitation à installer l\'app et ses limites dépliables', async () => {
    const { fixture, c } = await setup();
    const el: HTMLElement = fixture.nativeElement;
    expect(el.querySelector('.ws-app-head')?.textContent).toContain('app LaProd');
    expect(el.querySelector('.ws-app-list')).toBeNull();
    c.showAppInfo.set(true);
    fixture.detectChanges();
    expect(el.querySelectorAll('.ws-app-list li').length).toBe(5);
    expect(el.querySelectorAll('.ws-store').length).toBeGreaterThan(0);
  });

  it('clic au milieu de la piste avant chargement : lance la référence et garde la fraction cliquée', async () => {
    const { c } = await setup();
    clickAt(c, 0.5);
    expect(player.play).toHaveBeenCalledWith(TRACK, 'home', { referenceSource: true });
    expect(c.source()).toBe('beat');
    // la durée réelle arrive au chargement → position = 50 % de 60 s, pas de la timeline provisoire
    player.duration.set(60);
    TestBed.tick();
    expect(player.seek).toHaveBeenLastCalledWith(30);
  });

  it('clic dans la piste quand le beat est chargé : seek + lecture immédiate', async () => {
    const { c } = await setup();
    clickAt(c, 0.1);
    player.duration.set(60);
    TestBed.tick();
    player.play.mockClear();
    clickAt(c, 0.25, 'voice');
    expect(player.play).not.toHaveBeenCalled();
    expect(player.seek).toHaveBeenLastCalledWith(15);
    expect(player.resume).toHaveBeenCalled();
    expect(c.selectedLane()).toBe('voice');
  });

  it('« Début » relit depuis 0', async () => {
    const { c } = await setup();
    clickAt(c, 0.5);
    player.duration.set(60);
    TestBed.tick();
    c.playFromStart();
    expect(player.seek).toHaveBeenLastCalledWith(0);
  });

  it('libellé du bouton d\'enregistrement suit l\'état', async () => {
    const { c } = await setup();
    expect(c.recordLabel()).toBe('Enregistrer');
    c.state.set('recording');
    expect(c.recordLabel()).toBe('Terminer');
    expect(c.recordDisabled()).toBe(false);
    c.state.set('processing');
    expect(c.recordDisabled()).toBe(true);
    c.state.set('result');
    expect(c.recordLabel()).toBe('Réenregistrer');
  });

  it('enregistrement désactivé sans token ou sans essai invité', async () => {
    const { c } = await setup();
    c.micState.set('granted');   // jsdom n'a pas de micro : on neutralise ce blocage-là
    const guest = TestBed.inject(GuestToplineService) as unknown as GuestStub;
    guest.remainingAttempts.set(0);
    expect(c.recordDisabled()).toBe(true);
    auth.user.set({ topline_tokens: 0 });
    expect(c.recordDisabled()).toBe(true);
    auth.user.set({ topline_tokens: 3 });
    expect(c.recordDisabled()).toBe(false);
  });

  it('pendant la prise, la timeline et le transport ne relancent rien', async () => {
    const { c } = await setup();
    c.state.set('recording');
    clickAt(c, 0.5);
    c.togglePlay();
    c.playFromStart();
    expect(player.play).not.toHaveBeenCalled();
    expect(player.seek).not.toHaveBeenCalled();
  });

  it('Publier : invité → demande de compte, connecté → publication', async () => {
    const { c } = await setup();
    const svc = TestBed.inject(ToplineService) as any;
    svc.publishTopline.mockReturnValue({ subscribe: vi.fn() });
    c.state.set('result');
    c.resultTopline.set({ id: 9, stream_url: '/api/stream/toplines/9' } as any);
    c.onPublishPressed();
    expect(c.showGuestGate()).toBe(true);
    expect(svc.publishTopline).not.toHaveBeenCalled();
    auth.user.set({ topline_tokens: 3 });
    c.showGuestGate.set(false);
    c.onPublishPressed();
    expect(svc.publishTopline).toHaveBeenCalledWith(9);
  });

  it('le clip de voix est posé là où le beat en était à l\'enregistrement', async () => {
    const { c } = await setup();
    clickAt(c, 0);
    player.duration.set(100);
    TestBed.tick();
    c.voiceStartSec.set(20);
    c.voiceDurSec.set(30);
    expect(c.voiceClip()).toEqual({ left: 20, width: 30 });
  });
});
