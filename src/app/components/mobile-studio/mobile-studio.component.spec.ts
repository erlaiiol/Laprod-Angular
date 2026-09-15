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
    canAddTrack:       vi.fn().mockReturnValue(true),
    addTrack:          vi.fn().mockImplementation(() => {
      const id = `t${Date.now()}`;
      tracks.update(ts => [...ts, {
        id, name: 'Voix 1', rawBlob: null, processedBlob: null,
        waveform: [], duration: 0, settings: {}, trackState: 'empty',
      }]);
      return id;
    }),
    removeTrack:        vi.fn().mockImplementation((id: string) => {
      tracks.update(ts => ts.filter(t => t.id !== id));
    }),
    setRecording:       vi.fn(),
    setRecorded:        vi.fn(),
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

class AuthStub   { isPremium = () => false; getToken = () => 'tok'; }
class CalibStub  { hasCalibration = () => false; latencyMs = 0; save = vi.fn(); }
class DraftStub  { saveMp3 = vi.fn().mockResolvedValue(undefined); pruneOld = vi.fn().mockResolvedValue(undefined); }
class ToplineStub { uploadProcessed = vi.fn().mockReturnValue({ subscribe: vi.fn() }); }
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

  // ── toggleMonitorAutotune — pipeline de messages d'erreur casque ──────────────
  //
  // Zéro couverture avant cette passe alors que c'est la logique qui décide, pour de vrai,
  // ce que l'utilisateur voit s'afficher selon son casque — voir docs/roadmap.md, chantier 3
  // (§3.6.4 : le monitoring Bluetooth n'était en réalité jamais activé avant la correction de
  // cette passe, un bug qu'un test ici aurait détecté immédiatement).

  describe('toggleMonitorAutotune', () => {

    it('filaire : active le monitoring directement, sans message', async () => {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'wired' });
      const { component } = await createComponent(pm);

      await component.toggleMonitorAutotune();

      expect(component.monitorAutotune()).toBe(true);
      expect(component.errorMsg()).toBeNull();
      expect(component.showCalibration()).toBe(false);
    });

    it('aucun casque : message invitant à en brancher un, monitoring reste éteint', async () => {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'none' });
      const { component } = await createComponent(pm);

      await component.toggleMonitorAutotune();

      expect(component.monitorAutotune()).toBe(false);
      expect(component.errorMsg()).toContain('filaires');
    });

    it('casque Bluetooth A2DP : message explicite (pas une erreur générique), monitoring reste éteint', async () => {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'bluetooth-a2dp' });
      const { component } = await createComponent(pm);

      await component.toggleMonitorAutotune();

      expect(component.monitorAutotune()).toBe(false);
      expect(component.errorMsg()).toContain('A2DP');
    });

    it('casque Bluetooth (HFP/SCO) : ouvre la calibration, n\'active PAS encore le monitoring', async () => {
      const pm = makePmMock();
      (pm.checkHeadphones as any).mockResolvedValue({ type: 'bluetooth' });
      const { component } = await createComponent(pm);

      await component.toggleMonitorAutotune();

      expect(component.showCalibration()).toBe(true);
      // Le monitoring ne doit s'activer qu'après calibration explicite (onCalibrationDone) —
      // jamais silencieusement à l'ouverture de la sheet.
      expect(component.monitorAutotune()).toBe(false);
    });

    it('bascule à false sans re-vérifier le casque quand déjà actif', async () => {
      const pm = makePmMock();
      const { component } = await createComponent(pm);
      component.monitorAutotune.set(true);
      // ngOnInit appelle déjà checkHeadphones() une fois (détection initiale, § plus haut) —
      // on isole l'appel (éventuel) déclenché spécifiquement par le toggle lui-même.
      const callsBeforeToggle = (pm.checkHeadphones as any).mock.calls.length;

      await component.toggleMonitorAutotune();

      expect(component.monitorAutotune()).toBe(false);
      expect((pm.checkHeadphones as any).mock.calls.length).toBe(callsBeforeToggle);
    });
  });

  // ── onCalibrationDone — active réellement le monitoring Bluetooth ─────────────
  //
  // Avant la correction de cette passe, calibrer un casque Bluetooth sauvegardait la latence
  // mais n'activait jamais le monitoring live — l'utilisateur ne s'entendait jamais malgré un
  // texte ("Export et monitoring alignés") qui laissait croire le contraire.

  describe('onCalibrationDone', () => {

    it('active le monitoring, efface le message d\'erreur, ferme la sheet', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('bluetooth');
      component.errorMsg.set('un message précédent');
      component.showCalibration.set(true);

      component.onCalibrationDone(120);

      expect(component.monitorAutotune()).toBe(true);
      expect(component.errorMsg()).toBeNull();
      expect(component.showCalibration()).toBe(false);
    });

    it('sauvegarde la latence mesurée avec le type de casque courant', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('bluetooth');

      component.onCalibrationDone(85);

      expect(component.calibration.save).toHaveBeenCalledWith(85, 'bluetooth');
    });
  });

  // ── _btAheadMs — compensation de sync (à ne pas confondre avec la latence de monitoring
  //     live, voir docs/roadmap.md §3.8.7) ────────────────────────────────────────────────────

  describe('_btAheadMs', () => {

    it('nulle sur casque filaire, même si une calibration existe', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('wired');
      component.calibration.hasCalibration = () => true;
      (component.calibration as any).latencyMs = 150;

      expect((component as any)._btAheadMs()).toBe(0);
    });

    it('nulle sur Bluetooth non calibré', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('bluetooth');
      component.calibration.hasCalibration = () => false;

      expect((component as any)._btAheadMs()).toBe(0);
    });

    it('égale à la latence mesurée sur Bluetooth calibré', async () => {
      const { component } = await createComponent();
      component.headphoneType.set('bluetooth');
      component.calibration.hasCalibration = () => true;
      (component.calibration as any).latencyMs = 130;

      expect((component as any)._btAheadMs()).toBe(130);
    });
  });
});
