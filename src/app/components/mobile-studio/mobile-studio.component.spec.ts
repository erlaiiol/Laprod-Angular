import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { TestBed }                            from '@angular/core/testing';
import { signal }                             from '@angular/core';
import { MobileStudioComponent }              from './mobile-studio.component';
import { MobileMaquetteService }              from '../../services/mobile-maquette.service';
import { MobileAudioProcessorService }        from '../../services/mobile-audio-processor.service';
import { LatencyCalibrationService }          from '../../services/latency-calibration.service';
import { DraftSaveService }                   from '../../services/draft-save.service';
import { ToplineService }                     from '../../services/topline.service';
import { ToplineStatusService }               from '../../services/topline-status.service';
import { PlayerService }                      from '../../services/player.service';
import { AuthService }                        from '../../services/auth.service';
import { TrackDetail }                        from '../../services/track.service';
import { PITCH_MONITOR, PitchMonitorPlugin }  from '../../services/pitch-monitor-plugin';

// ── PitchMonitor mock ─────────────────────────────────────────────────────────
// vi.mock() for relative paths is blocked by @angular/build:unit-test.
// We use an InjectionToken (PITCH_MONITOR) so TestBed can provide a mock.

function makePmMock(): PitchMonitorPlugin {
  return {
    checkHeadphones:    vi.fn().mockResolvedValue({ type: 'none' }),
    checkPermission:    vi.fn().mockResolvedValue({ microphone: 'granted' }),
    requestPermission:  vi.fn().mockResolvedValue({ microphone: 'granted' }),
    startSession:       vi.fn().mockResolvedValue(undefined),
    stopSession:        vi.fn().mockResolvedValue({
      pcmBase64: btoa('FAKE'), sampleRate: 48000, channels: 1, format: 'float32',
    }),
    addListener:        vi.fn().mockResolvedValue({ remove: vi.fn() }),
    removeAllListeners: vi.fn().mockResolvedValue(undefined),
    setBeatVolume:      vi.fn().mockResolvedValue(undefined),
    setVoiceFx:         vi.fn().mockResolvedValue(undefined),
  } as unknown as PitchMonitorPlugin;
}

// ── Stubs services ────────────────────────────────────────────────────────────

function makeMaquetteStub() {
  const tracks = signal<any[]>([]);
  return {
    tracks,
    isExporting:       signal(false),
    exportPct:         signal(0),
    exportStep:        signal(''),
    extendedBeatBlob:  signal(null),
    focusedTrackId:    signal<string | null>(null),
    focusTrack:        vi.fn(),
    canAddTrack:       vi.fn().mockReturnValue(true),
    addTrack:          vi.fn().mockImplementation(() => {
      const id = `t${Date.now()}`;
      tracks.update(ts => [...ts, {
        id, name: 'Voix 1', rawBlob: null, processedBlob: null,
        waveform: [], duration: 0, beatStartSec: 0, settings: {}, trackState: 'empty',
      }]);
      return id;
    }),
    removeTrack:        vi.fn().mockImplementation((id: string) => {
      tracks.update(ts => ts.filter(t => t.id !== id));
    }),
    setRecording:       vi.fn(),
    setRecorded:        vi.fn(),
    cancelRecording:    vi.fn(),
    hasUndoFor:         vi.fn().mockReturnValue(false),
    undoLastTake:       vi.fn().mockReturnValue(true),
    updateSettings:     vi.fn(),
    renameTrack:        vi.fn(),
    ensureAutotune:     vi.fn().mockResolvedValue(undefined),
    setExtendedBeat:    vi.fn(),
    clearExtendedBeat:  vi.fn(),
    exportMaquette:     vi.fn().mockResolvedValue(new Blob(['mp3'])),
    reset:              vi.fn(),
  };
}

class ProcessorStub {
  async processVocalTrack() { return new Float32Array(100); }
  async mixAndExport()      { return new Blob(['mp3']); }
  async quickMix()          { return new AudioBuffer({ numberOfChannels: 1, length: 100, sampleRate: 48000 }); }
  async decodeBlob()        { return new AudioBuffer({ numberOfChannels: 1, length: 100, sampleRate: 48000 }); }
  async spliceAudio(a: Blob) { return a; }
  // Écoute en direct : chaîne d'effets factice par piste + réverb partagée.
  chains: Array<{ settings: any; quality: string; update: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }> = [];
  latencySec = 0;
  async decodeVoiceForPlayback() { return new AudioBuffer({ numberOfChannels: 1, length: 100, sampleRate: 48000 }); }
  async vocalChainLatencySec(q: string) { return q === 'full' ? this.latencySec : 0; }
  async createLiveReverb() { return { connect: vi.fn() }; }
  createLiveVoiceChain(_ctx: unknown, settings: any, quality: string) {
    const node = () => ({ connect: vi.fn() });
    const chain = { input: node(), dry: node(), wet: node(), settings, quality, update: vi.fn(), dispose: vi.fn() };
    this.chains.push(chain);
    return chain;
  }
}

class PlayerStub {
  // Surface complète consommée par mobile-studio (ngOnInit charge le beat via
  // src/load/addEventListener ; ngOnDestroy remet studioOpen/loop à zéro).
  // Un membre manquant fait jeter les hooks → rejections non gérées qui
  // polluent tous les fichiers de spec du même worker Vitest.
  audioEl = {
    play:                vi.fn().mockResolvedValue(undefined),
    pause:               vi.fn(),
    load:                vi.fn(),
    addEventListener:    vi.fn(),
    removeEventListener: vi.fn(),
    currentTime: 0,
    duration:    0,
    volume:      1,
    loop:        false,
    src:         '',
  };
  studioOpen = signal(false);
  pause = vi.fn();
}

class AuthStub   { isPremium = () => false; getToken = () => 'tok'; isLoggedIn = () => false; canMakeClips = () => false; currentUser = () => null; }
class CalibStub  {
  entry: { latencyMs: number; deviceType: string; ts: number } | null = null;
  getEntry = () => this.entry;
  hasCalibration = () => this.entry !== null;
  get latencyMs() { return this.entry?.latencyMs ?? 0; }
  save = vi.fn();
}

/** PCM float32 base64 de `sec` secondes (valeur constante `v`). */
function pcmF32Base64(sec: number, sampleRate = 48000, v = 0.25): string {
  const bytes = new Uint8Array(new Float32Array(Math.round(sec * sampleRate)).fill(v).buffer);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}
class DraftStub  {
  saveMp3 = vi.fn().mockResolvedValue(undefined);
  pruneOld = vi.fn().mockResolvedValue(undefined);
  listDraftsForTrack = vi.fn().mockResolvedValue([]);
  readDraft = vi.fn().mockResolvedValue(new Blob());
}
class ToplineStub {
  uploadProcessed = vi.fn().mockReturnValue({ subscribe: vi.fn() });
  startMobileSession = vi.fn().mockReturnValue({ subscribe: vi.fn() });
  getOpenMobileSession = vi.fn().mockReturnValue({ subscribe: vi.fn() });
}
class StatusStub { openForUpload = vi.fn(); setDoneWithId = vi.fn(); stopPolling = vi.fn(); }

// ── Track de test ─────────────────────────────────────────────────────────────

const FAKE_TRACK: TrackDetail = {
  id: 1, title: 'Test Beat', key: 'C major', bpm: 120,
  image_file: null, user_id: 1, description: '', created_at: '',
} as any;

// ── TestBed setup ─────────────────────────────────────────────────────────────

async function createComponent(pmMock?: PitchMonitorPlugin) {
  let maquetteStub: ReturnType<typeof makeMaquetteStub>;

  TestBed.overrideComponent(MobileStudioComponent, {
    set: { imports: [], template: '<div></div>' },
  });

  await TestBed.configureTestingModule({
    imports: [MobileStudioComponent],
    providers: [
      { provide: PITCH_MONITOR,                 useValue:   pmMock ?? makePmMock()        },
      { provide: MobileMaquetteService,         useFactory: () => { maquetteStub = makeMaquetteStub(); return maquetteStub; } },
      { provide: MobileAudioProcessorService,   useClass:   ProcessorStub   },
      { provide: PlayerService,                 useClass:   PlayerStub      },
      { provide: AuthService,                   useClass:   AuthStub        },
      { provide: LatencyCalibrationService,     useClass:   CalibStub       },
      { provide: DraftSaveService,              useClass:   DraftStub       },
      { provide: ToplineService,                useClass:   ToplineStub     },
      { provide: ToplineStatusService,          useClass:   StatusStub      },
    ],
  }).compileComponents();

  const fixture   = TestBed.createComponent(MobileStudioComponent);
  const component = fixture.componentInstance;
  component.track = FAKE_TRACK;
  fixture.detectChanges();

  return { fixture, component, maquette: maquetteStub! };
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('MobileStudioComponent', () => {

  afterEach(() => {
    vi.clearAllMocks();
    TestBed.resetTestingModule();
  });

  // ── Mode Clip : réservé aux membres Premium connectés ─────────────────────────

  describe('bouton Clip (Premium)', () => {
    function forceNative(c: MobileStudioComponent): void {
      Object.defineProperty(c, 'clipAvailable', { value: true });
    }

    it('invité : bulle d\'aide, le Mode Clip ne s\'ouvre pas', async () => {
      const { component } = await createComponent();
      forceNative(component);
      await component.openClip();
      expect(component.clipHint()).toBe(true);
      expect(component.studioState()).toBe('idle');
      expect(component.clipCtx()).toBeNull();
    });

    it('connecté non Premium : verrouillé, bulle d\'aide', async () => {
      const { component } = await createComponent();
      forceNative(component);
      const auth = TestBed.inject(AuthService) as unknown as AuthStub;
      auth.isLoggedIn = () => true;
      expect(component.clipLocked()).toBe(true);
      await component.openClip();
      expect(component.clipHint()).toBe(true);
      expect(component.studioState()).toBe('idle');
    });

    it('Premium connecté : déverrouillé, le Mode Clip s\'ouvre', async () => {
      const { component } = await createComponent();
      forceNative(component);
      const auth = TestBed.inject(AuthService) as unknown as AuthStub;
      auth.isLoggedIn = () => true;
      auth.canMakeClips = () => true;
      expect(component.clipLocked()).toBe(false);
      component.beatDuration.set(120);
      await component.openClip();
      expect(component.clipHint()).toBe(false);
      expect(component.studioState()).toBe('clip');
      expect(component.clipCtx()).not.toBeNull();
    });

    it('la bulle se ferme seule après quelques secondes', async () => {
      vi.useFakeTimers();
      const { component } = await createComponent();
      component.showClipHint();
      vi.advanceTimersByTime(6100);
      expect(component.clipHint()).toBe(false);
      vi.useRealTimers();
    });
  });

  // ── clipWarning ─────────────────────────────────────────────────────────────

  describe('clipWarning', () => {

    it('est false quand le signal est faible', async () => {
      const { component } = await createComponent();
      component.recordRms.set(0.3);
      component.micGain.set(1.0);
      expect(component.clipWarning()).toBe(false);
    });

    it('est true quand rms * gain > 0.85', async () => {
      const { component } = await createComponent();
      component.recordRms.set(0.9);
      component.micGain.set(1.0);
      expect(component.clipWarning()).toBe(true);
    });

    it('tient compte du gain micro', async () => {
      const { component } = await createComponent();
      component.recordRms.set(0.5);
      component.micGain.set(2.0); // 0.5 × 2 = 1.0 → sature
      expect(component.clipWarning()).toBe(true);
    });

    it('est false si gain réduit compense un signal fort', async () => {
      const { component } = await createComponent();
      component.recordRms.set(0.8);
      component.micGain.set(0.5); // 0.8 × 0.5 = 0.4 → ok
      expect(component.clipWarning()).toBe(false);
    });
  });

  // ── nearEnd ─────────────────────────────────────────────────────────────────

  describe('nearEnd', () => {

    it('commence à false', async () => {
      const { component } = await createComponent();
      expect(component.nearEnd()).toBe(false);
    });

    it('reste false si pas encore dans la zone critique', async () => {
      const { component } = await createComponent();
      // nearEnd est contrôlé par le timer interne — on vérifie l'état initial
      component.recordTimer.set(150); // 150s < MAX(180) - 15 = 165
      expect(component.nearEnd()).toBe(false);
    });
  });

  // ── Interruption audio ───────────────────────────────────────────────────────

  describe('_handleInterrupted', () => {

    it('passe studioState à idle après une interruption', async () => {
      const { component, maquette } = await createComponent();

      const id = maquette.addTrack();
      component.activeRecordingId.set(id);
      component.studioState.set('recording');
      component.recordTimer.set(10);
      (component as any)._isFinalizingRec = false;

      const partialResult = {
        pcmBase64: btoa('FAKE'), sampleRate: 48000, channels: 1,
        format: 'float32' as const, partial: true as const,
      };

      await (component as any)._handleInterrupted(partialResult);

      expect(component.studioState()).toBe('idle');
      expect(component.activeRecordingId()).toBeNull();
    });

    it('affiche un message d\'interruption (pas une erreur générique)', async () => {
      const { component, maquette } = await createComponent();

      const id = maquette.addTrack();
      component.activeRecordingId.set(id);
      component.studioState.set('recording');
      component.recordTimer.set(10);
      (component as any)._isFinalizingRec = false;

      await (component as any)._handleInterrupted({
        pcmBase64: btoa('X'), sampleRate: 48000, channels: 1,
        format: 'float32' as const, partial: true as const,
      });

      expect(component.errorMsg()).toContain('interrompu');
    });

    it('ne traite pas une 2ème interruption si déjà en cours de finalisation', async () => {
      const { component, maquette } = await createComponent();
      const id = maquette.addTrack();
      component.activeRecordingId.set(id);
      (component as any)._isFinalizingRec = true;

      await (component as any)._handleInterrupted({
        pcmBase64: btoa('X'), sampleRate: 48000, channels: 1,
        format: 'float32' as const, partial: true as const,
      });

      expect(maquette.setRecorded).not.toHaveBeenCalled();
    });

    it('ne supprime pas la piste en cas d\'interruption', async () => {
      const { component, maquette } = await createComponent();
      const id = maquette.addTrack();
      component.activeRecordingId.set(id);
      component.recordTimer.set(8);
      (component as any)._isFinalizingRec = false;

      await (component as any)._handleInterrupted({
        pcmBase64: btoa('X'), sampleRate: 48000, channels: 1,
        format: 'float32' as const, partial: true as const,
      });

      expect(maquette.removeTrack).not.toHaveBeenCalled();
    });
  });

  // ── _stopRecordingListeners ──────────────────────────────────────────────────

  describe('_stopRecordingListeners', () => {

    it('réinitialise nearEnd et detectedNote', async () => {
      const { component } = await createComponent();
      component.nearEnd.set(true);
      component.detectedNote.set('A4');

      (component as any)._stopRecordingListeners();

      expect(component.nearEnd()).toBe(false);
      expect(component.detectedNote()).toBeNull();
    });
  });

  // ── toggleMonitorVoice — "m'entendre chanter", filaire comme Bluetooth ──────

  describe('toggleMonitorVoice', () => {

    it('filaire : active le retour voix directement, sans message', async () => {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'wired' });
      const { component } = await createComponent(pm);

      await component.toggleMonitorVoice();

      expect(component.monitorVoice()).toBe(true);
      expect(component.errorMsg()).toBeNull();
      expect(component.showCalibration()).toBe(false);
    });

    it('aucun casque : message invitant à en brancher un, retour voix reste éteint', async () => {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'none' });
      const { component } = await createComponent(pm);

      await component.toggleMonitorVoice();

      expect(component.monitorVoice()).toBe(false);
      expect(component.errorMsg()).toContain('casque');
    });

    for (const type of ['bluetooth', 'bluetooth-a2dp'] as const) {
      it(`${type} non réglé : ouvre le réglage au métronome, active le retour voix ensuite`, async () => {
        const pm = makePmMock();
        (pm.checkHeadphones as any).mockResolvedValue({ type });
        const { component } = await createComponent(pm);
        component.showCalibration.set(false);   // proposition auto du 1er usage

        await component.toggleMonitorVoice();

        expect(component.showCalibration()).toBe(true);
        expect(component.monitorVoice()).toBe(false);
        expect(component.errorMsg()).toBeNull();

        component.onCalibrationDone(160);
        expect(component.monitorVoice()).toBe(true);
      });

      it(`${type} déjà réglé : active le retour voix directement`, async () => {
        const pm = makePmMock();
        (pm.checkHeadphones as any).mockResolvedValue({ type });
        const { component } = await createComponent(pm);
        (component.calibration as any).entry = { latencyMs: 180, deviceType: type, ts: 0 };
        component.showCalibration.set(false);

        await component.toggleMonitorVoice();

        expect(component.monitorVoice()).toBe(true);
        expect(component.showCalibration()).toBe(false);
      });
    }

    it('bascule à false sans re-vérifier le casque quand déjà actif', async () => {
      const pm = makePmMock();
      const { component } = await createComponent(pm);
      component.monitorVoice.set(true);
      const callsBeforeToggle = (pm.checkHeadphones as any).mock.calls.length;

      await component.toggleMonitorVoice();

      expect(component.monitorVoice()).toBe(false);
      expect((pm.checkHeadphones as any).mock.calls.length).toBe(callsBeforeToggle);
    });

    it('autotune live : sans effet tant que le retour voix est éteint', async () => {
      const { component } = await createComponent();
      component.toggleMonitorAutotune();
      expect(component.monitorAutotune()).toBe(false);

      component.monitorVoice.set(true);
      component.toggleMonitorAutotune();
      expect(component.monitorAutotune()).toBe(true);
    });
  });

  // ── onCalibrationDone ────────────────────────────────────────────────────────

  describe('onCalibrationDone', () => {

    it('"Refaire" depuis les réglages : sauvegarde sans activer le retour voix', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('bluetooth-a2dp');
      component.errorMsg.set('un message précédent');
      component.openCalibration();

      component.onCalibrationDone(85);

      expect(component.calibration.save).toHaveBeenCalledWith(85, 'bluetooth-a2dp');
      expect(component.monitorVoice()).toBe(false);
      expect(component.errorMsg()).toBeNull();
      expect(component.showCalibration()).toBe(false);
    });
  });

  // ── _takeLatencyMs — latence retirée du début de chaque prise ─────────────────

  describe('_takeLatencyMs', () => {

    it('Bluetooth réglé au métronome : la mesure de l\'utilisateur', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('bluetooth-a2dp');
      (component.calibration as any).entry = { latencyMs: 190, deviceType: 'bluetooth', ts: 0 };

      expect((component as any)._takeLatencyMs({ outputLatencyMs: 140, inputLatencyMs: 5 })).toBe(190);
    });

    it('sinon : latences rapportées par le système (sortie + entrée)', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('wired');
      (component.calibration as any).entry = { latencyMs: 190, deviceType: 'bluetooth', ts: 0 };

      expect((component as any)._takeLatencyMs({ outputLatencyMs: 8, inputLatencyMs: 3 })).toBe(11);
    });

    it('sans info système (Android) ni réglage : 0', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('wired');
      expect((component as any)._takeLatencyMs(null)).toBe(0);
    });
  });

  // ── _finalizeRecording — la voix est posée là où elle a été chantée ───────────

  describe('_finalizeRecording (alignement)', () => {

    async function setupTake(take: object, punch?: { beatStartSec: number; punchSec: number }) {
      const env = await createComponent();
      const id  = env.maquette.addTrack();
      if (punch) {
        env.maquette.tracks.update(ts => ts.map(t => t.id === id
          ? { ...t, rawBlob: new Blob([new Float32Array(48000 * 5)]), beatStartSec: punch.beatStartSec, waveform: [] }
          : t));
        env.component.punchInSec.set(punch.punchSec);
      }
      env.component.activeRecordingId.set(id);
      (env.component as any)._take = take;
      return { ...env, id };
    }

    it('iOS (beat natif) : piste démarrée à la position mesurée, latence retirée du début', async () => {
      const { component, maquette, id } = await setupTake({ beatStartSec: 0, nativeBeat: true, latencyMs: 100, leadSec: 0 });

      await (component as any)._finalizeRecording({
        pcmBase64: pcmF32Base64(1), sampleRate: 48000, channels: 1, format: 'float32',
        firstSampleBeatSec: 0.004,
      });

      const [calledId, blob, , duration, beatStartSec] = maquette.setRecorded.mock.calls[0];
      expect(calledId).toBe(id);
      expect(blob.size).toBe((48000 - 4800) * 4);   // 100 ms retirés
      expect(duration).toBeCloseTo(0.9, 5);
      expect(beatStartSec).toBeCloseTo(0.004, 6);
      expect(component.studioState()).toBe('idle');
    });

    it('Android (<audio>) : retire la voix captée avant le départ du beat + la latence', async () => {
      const { component, maquette } = await setupTake({ beatStartSec: 0, nativeBeat: false, latencyMs: 50, leadSec: 0.05 });

      await (component as any)._finalizeRecording({
        pcmBase64: pcmF32Base64(1, 44100), sampleRate: 44100, channels: 1, format: 'float32',
      });

      const [, blob, , , beatStartSec] = maquette.setRecorded.mock.calls[0];
      expect(blob.size).toBe((44100 - 4410) * 4);
      expect(beatStartSec).toBe(0);
    });

    it('punch-in : la nouvelle prise est collée à sa position réelle sur le beat', async () => {
      const { component, maquette } = await setupTake(
        { beatStartSec: 2.01, nativeBeat: true, latencyMs: 0, leadSec: 0 },
        { beatStartSec: 0.01, punchSec: 2 },
      );
      const processor = TestBed.inject(MobileAudioProcessorService);
      const splice    = vi.spyOn(processor, 'spliceAudio');

      await (component as any)._finalizeRecording({
        pcmBase64: pcmF32Base64(1), sampleRate: 48000, channels: 1, format: 'float32',
        firstSampleBeatSec: 2.012,
      });

      expect(splice.mock.calls[0][2]).toBeCloseTo(2.002, 6);   // 2.012 − 0.01
      const [, , , duration, beatStartSec] = maquette.setRecorded.mock.calls[0];
      expect(beatStartSec).toBe(0.01);                          // la piste ne bouge pas
      expect(duration).toBeCloseTo(3.002, 6);
    });

    it('prise vide (arrêt immédiat) : pas de piste fantôme, état restauré', async () => {
      const { component, maquette, id } = await setupTake({ beatStartSec: 0, nativeBeat: true, latencyMs: 0, leadSec: 0 });

      await (component as any)._finalizeRecording({
        pcmBase64: '', sampleRate: 48000, channels: 1, format: 'float32',
      });

      expect(maquette.setRecorded).not.toHaveBeenCalled();
      expect(maquette.cancelRecording).toHaveBeenCalledWith(id);
      expect(component.studioState()).toBe('idle');
    });
  });

  // ── ngOnDestroy — ne laisse jamais une session native ouverte ────────────────

  describe('ngOnDestroy', () => {

    it('referme la session native encore ouverte (sinon la suivante est refusée)', async () => {
      const pm = makePmMock();
      const { component, fixture } = await createComponent(pm);
      (component as any)._nativeSessionOpen = true;

      fixture.destroy();

      expect(pm.stopSession).toHaveBeenCalled();
    });

    it('ne touche pas au natif sans session ouverte', async () => {
      const pm = makePmMock();
      const { fixture } = await createComponent(pm);

      fixture.destroy();

      expect(pm.stopSession).not.toHaveBeenCalled();
    });
  });

  // ── Retour casque : réglages entendus en direct ──────────────────────────────

  describe('retour casque en direct', () => {

    const flush = async (fixture: any) => {
      for (let i = 0; i < 4; i++) { fixture.detectChanges(); await new Promise(r => setTimeout(r)); }
    };

    async function withWiredMonitor() {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'wired' });
      const env = await createComponent(pm);
      env.component.permState.set('granted');
      await env.component.toggleMonitorVoice();
      await flush(env.fixture);
      return { ...env, pm };
    }

    it('"M\'entendre chanter" ouvre aussitôt le micro dans le studio, sans rien enregistrer', async () => {
      const { pm } = await withWiredMonitor();
      expect(pm.startSession).toHaveBeenCalledTimes(1);
      const opts = (pm.startSession as any).mock.calls[0][0];
      expect(opts.record).toBe(false);
      expect(opts.useMonitor).toBe(true);
      expect(opts.fx).toEqual({ lowCutHz: 150, presenceDb: 3.5, clarityDb: 3, reverbWet: 0.12, volume: 1 });
    });

    it('un réglage de piste est poussé immédiatement au natif', async () => {
      const { component, maquette, fixture, pm } = await withWiredMonitor();
      const id = maquette.tracks()[0].id;
      maquette.tracks.update(ts => ts.map(t => t.id === id
        ? { ...t, settings: { volume: 0.5, lowCutHz: 220, presenceDb: 6, clarityDb: 7, reverbWet: 0.2 } } : t));
      maquette.focusedTrackId.set(id);
      component.micGain.set(2);
      await flush(fixture);

      expect((pm.setVoiceFx as any).mock.calls.at(-1)[0])
        .toEqual({ lowCutHz: 220, presenceDb: 6, clarityDb: 7, reverbWet: 0.2, volume: 1 });
    });

    it('le micro se referme en quittant l\'écran principal et se rouvre au retour', async () => {
      const { component, fixture, pm } = await withWiredMonitor();

      component.studioState.set('exporting');
      await flush(fixture);
      expect(pm.stopSession).toHaveBeenCalledTimes(1);

      component.studioState.set('idle');
      await flush(fixture);
      expect(pm.startSession).toHaveBeenCalledTimes(2);
    });

    it('désactiver "M\'entendre chanter" referme le micro', async () => {
      const { component, fixture, pm } = await withWiredMonitor();
      await component.toggleMonitorVoice();
      await flush(fixture);
      expect(pm.stopSession).toHaveBeenCalledTimes(1);
    });

    it('jamais de micro ouvert sans casque', async () => {
      const pm = makePmMock();
      const { component, fixture } = await createComponent(pm);
      component.permState.set('granted');
      component.monitorVoice.set(true);           // casque 'none'
      await flush(fixture);
      expect(pm.startSession).not.toHaveBeenCalled();
    });
  });

  // ── Transport : lecture du mix complet, voix calées sur l'instrumentale ──────

  describe('transport (lecture du mix)', () => {

    /** AudioContext factice : enregistre les start(when, offset) de chaque source. */
    class FakeSource {
      buffer: any = null;
      onended: (() => void) | null = null;
      start      = vi.fn();
      stop       = vi.fn();
      connect    = vi.fn((n: any) => n);
      disconnect = vi.fn();
    }
    class FakeCtx {
      static last: FakeCtx | null = null;
      currentTime = 10;
      destination = {};
      sources: FakeSource[] = [];
      gains: Array<{ gain: { value: number } }> = [];
      closed = false;
      constructor() { FakeCtx.last = this; }
      createBufferSource() { const s = new FakeSource(); this.sources.push(s); return s; }
      createGain() {
        const g = { gain: { value: 1 }, connect: vi.fn((n: any) => n), disconnect: vi.fn() };
        this.gains.push(g);
        return g;
      }
      createDynamicsCompressor() {
        const p = () => ({ value: 0 });
        return { threshold: p(), knee: p(), ratio: p(), attack: p(), release: p(), connect: vi.fn() };
      }
      resume = vi.fn().mockResolvedValue(undefined);
      close  = vi.fn().mockImplementation(async () => { this.closed = true; });
    }

    const LEAD = 0.08;
    const BEAT_SEC = 60;

    /** Studio avec un beat de 60 s et des voix { start, dur } déjà enregistrées. */
    async function setup(voices: Array<{ start: number; dur: number; volume?: number }>) {
      vi.stubGlobal('AudioContext', FakeCtx);
      vi.stubGlobal('requestAnimationFrame', vi.fn().mockReturnValue(1));
      vi.stubGlobal('cancelAnimationFrame', vi.fn());
      const env = await createComponent();
      const { component, maquette } = env;

      const beatBlob = new Blob(['beat']);
      (component as any)._beatBlob.set(beatBlob);
      const durations = new Map<Blob, number>([[beatBlob, BEAT_SEC]]);
      const tracks = voices.map((v, i) => {
        const rawBlob = new Blob([`voice${i}`]);
        durations.set(rawBlob, v.dur);
        return {
          id: `v${i}`, name: `Voix ${i + 1}`, rawBlob, processedBlob: null, waveform: [],
          duration: v.dur, beatStartSec: v.start, trackState: 'recorded',
          settings: { volume: v.volume ?? 1, useAutotune: false },
        };
      });
      maquette.tracks.set(tracks);
      const processor = TestBed.inject(MobileAudioProcessorService) as unknown as ProcessorStub;
      const fake = async (b: Blob) => ({ duration: durations.get(b) }) as AudioBuffer;
      vi.spyOn(processor, 'decodeBlob').mockImplementation(fake as any);
      vi.spyOn(processor, 'decodeVoiceForPlayback').mockImplementation(fake as any);
      return { ...env, tracks, processor };
    }

    /** Sources créées : [beat, ...voix effectivement planifiées]. */
    const sources = () => FakeCtx.last!.sources;

    afterEach(() => vi.unstubAllGlobals());

    it('"Lire du début" lance l\'instrumentale et toutes les voix sur le même instant', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }, { start: 12.5, dur: 8 }, { start: 30, dur: 5 }]);

      await (component as any)._playMixAt(0);

      const t0 = 10 + LEAD;
      const [beat, v0, v1, v2] = sources();
      expect(sources().length).toBe(4);                       // beat + 3 voix
      expect(beat.start).toHaveBeenCalledWith(t0, 0);
      expect(v0.start).toHaveBeenCalledWith(t0, 0);           // voix posée à 0 s
      expect(v1.start).toHaveBeenCalledWith(t0 + 12.5, 0);    // démarre 12,5 s après le beat
      expect(v2.start).toHaveBeenCalledWith(t0 + 30, 0);
      expect(component.isPlayingPreview()).toBe(true);
    });

    it('départ au milieu : chaque voix reste à sa position d\'enregistrement', async () => {
      const { component } = await setup([
        { start: 2,  dur: 10 },   // entamée à 5 s → reprise à 3 s dans la piste
        { start: 8,  dur: 4  },   // pas encore commencée → planifiée 3 s plus tard
        { start: 0,  dur: 1  },   // déjà terminée → non jouée
      ]);

      await (component as any)._playMixAt(5);

      const t0 = 10 + LEAD;
      const [beat, v0, v1] = sources();
      expect(sources().length).toBe(3);
      expect(beat.start).toHaveBeenCalledWith(t0, 5);
      expect(v0.start).toHaveBeenCalledWith(t0, 3);
      expect(v1.start).toHaveBeenCalledWith(t0 + 3, 0);
      expect(component.beatCurrentTime()).toBe(5);
    });

    it('chaque voix passe par sa chaîne d\'effets, le beat garde la balance de l\'export', async () => {
      const { component, processor } = await setup([{ start: 0, dur: 20, volume: 0.5 }, { start: 3, dur: 5 }]);

      await (component as any)._playMixAt(0);

      expect(FakeCtx.last!.gains[0].gain.value).toBeCloseTo(0.355);
      expect(processor.chains.length).toBe(2);
      expect(processor.chains[0].settings.volume).toBe(0.5);
      expect(processor.chains[0].quality).toBe('full');
    });

    it('un réglage modifié pendant la lecture s\'applique en direct, sans relancer le mix', async () => {
      const { component, fixture, maquette, processor } = await setup([{ start: 0, dur: 20 }]);
      await (component as any)._playMixAt(0);
      const play = vi.spyOn(component as any, '_playMixAt');

      maquette.tracks.update(ts => ts.map(t => ({ ...t, settings: { ...t.settings, reverbWet: 0.2, lowCutHz: 220 } })));
      fixture.detectChanges();
      await fixture.whenStable();

      expect(processor.chains[0].update).toHaveBeenCalledWith(expect.objectContaining({ reverbWet: 0.2, lowCutHz: 220 }));
      expect(play).not.toHaveBeenCalled();
      expect(sources().length).toBe(2);                       // aucune source recréée
    });

    it('le retard de la chaîne d\'effets est compensé : la voix part d\'autant plus tôt', async () => {
      const { component, processor } = await setup([{ start: 2, dur: 10 }, { start: 8, dur: 4 }]);
      processor.latencySec = 0.012;

      await (component as any)._playMixAt(5);

      const t0 = 10 + LEAD;
      const [beat, v0, v1] = sources();
      expect(beat.start).toHaveBeenCalledWith(t0, 5);
      expect(v0.start.mock.calls[0][0]).toBe(t0);
      expect(v0.start.mock.calls[0][1]).toBeCloseTo(3.012);   // déjà entamée : 12 ms plus loin
      expect(v1.start.mock.calls[0][0]).toBeCloseTo(t0 + 3 - 0.012);   // à venir : 12 ms plus tôt
    });

    it('qualité "Légère" : chaînes allégées, sans retard à compenser', async () => {
      const { component, processor } = await setup([{ start: 2, dur: 10 }]);
      processor.latencySec = 0.012;
      component.setPreviewQuality('light');

      await (component as any)._playMixAt(5);

      expect(processor.chains[0].quality).toBe('light');
      expect(sources()[1].start).toHaveBeenCalledWith(10 + LEAD, 3);
    });

    it('toucher une piste la sélectionne et lance le mix à l\'instant touché', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }]);
      component.beatDuration.set(BEAT_SEC);
      component.pxPerSec.set(10);
      (component as any).tlContentRef = { nativeElement: { getBoundingClientRect: () => ({ left: -200 }) } };
      const play = vi.spyOn(component as any, '_playMixAt');

      component.onLaneTap({ clientX: 100 } as MouseEvent, 'v0');   // (100 + 200) px / 10 px·s⁻¹ = 30 s

      expect(component.selectedLane()).toBe('v0');
      expect(play).toHaveBeenCalledWith(30);
    });

    it('glisser la tête de lecture : son coupé pendant le geste, reprise à la position relâchée', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }]);
      await (component as any)._playMixAt(0);
      component.pxPerSec.set(10);
      (component as any).tlContentRef = { nativeElement: { getBoundingClientRect: () => ({ left: 0 }) } };
      const first = [...sources()];
      const ev = (clientX: number) => ({
        clientX, pointerId: 1, preventDefault() {}, stopPropagation() {}, currentTarget: {},
      }) as unknown as PointerEvent;

      component.onScrubStart(ev(50));
      for (const s of first) expect(s.stop).toHaveBeenCalled();
      component.onScrubMove(ev(120));
      expect(component.beatCurrentTime()).toBe(12);

      const play = vi.spyOn(component as any, '_playMixAt');
      component.onScrubEnd(ev(120));
      expect(play).toHaveBeenCalledWith(12);
    });

    it('un nouveau départ coupe les sources précédentes (jamais deux mix superposés)', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }]);

      await (component as any)._playMixAt(0);
      const first = [...sources()];
      await (component as any)._playMixAt(30);

      for (const s of first) expect(s.stop).toHaveBeenCalled();
      expect(sources().length).toBe(3);                       // 2 anciennes + beat seul (voix terminée à 30 s)
      expect(sources()[2].start).toHaveBeenCalledWith(10 + LEAD, 30);
    });

    it('Stop arrête tout et ramène la tête de lecture au début', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }]);
      await (component as any)._playMixAt(7);
      const ctx = FakeCtx.last!;

      component.stopMix();

      for (const s of ctx.sources) expect(s.stop).toHaveBeenCalled();
      expect(ctx.close).toHaveBeenCalled();
      expect(component.isPlayingPreview()).toBe(false);
      expect(component.beatCurrentTime()).toBe(0);
    });

    it('pause puis reprise : repart de la position atteinte', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }]);
      await (component as any)._playMixAt(4);
      FakeCtx.last!.currentTime = 10 + LEAD + 6;              // 6 s de lecture

      component.toggleMixPlayback();                          // pause
      expect(component.isPlayingPreview()).toBe(false);
      expect(component.beatCurrentTime()).toBeCloseTo(10);

      const play = vi.spyOn(component as any, '_playMixAt');
      component.toggleMixPlayback();                          // reprise
      expect(play.mock.calls[0][0]).toBeCloseTo(10);
    });

    it('ne lance rien hors de l\'écran principal (enregistrement, export…)', async () => {
      const { component } = await setup([{ start: 0, dur: 20 }]);
      FakeCtx.last = null;
      component.studioState.set('recording');

      await (component as any)._playMixAt(0);

      expect(FakeCtx.last).toBeNull();
      expect(component.isPlayingPreview()).toBe(false);
    });
  });
});
