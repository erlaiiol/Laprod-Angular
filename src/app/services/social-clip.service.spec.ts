import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';

import { CLIP_FILES, CLIP_OVERLAY_RENDERER, CLIP_PLATFORM, ClipPlatform, ClipStudioContext, SocialClipService } from './social-clip.service';
import { CLIP_CAMERA } from './clip-camera-plugin';
import { PITCH_MONITOR } from './pitch-monitor-plugin';
import { MobileMaquetteService } from './mobile-maquette.service';
import { CLIP_END_CARD_SECONDS } from '../utils/clip-sync';


type Mocked = { mock: { calls: unknown[][] } };
const firstArg = (m: Mocked): unknown => m.mock.calls[0][0];
const lastArg  = (m: Mocked): unknown => m.mock.calls[m.mock.calls.length - 1][0];

function b64(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s);
}

/** 2 s de voix float32 à 1 kHz. */
function pcm(sec = 2, sr = 1000): string {
  return b64(new Uint8Array(new Float32Array(sec * sr).fill(0.2).buffer));
}

function makeCam() {
  return {
    checkPermissions:   vi.fn(async () => ({ camera: 'granted', photos: 'granted' })),
    requestPermissions: vi.fn(async () => ({ camera: 'granted', photos: 'granted' })),
    startPreview:    vi.fn(async () => {}),
    stopPreview:     vi.fn(async () => {}),
    flipCamera:      vi.fn(async () => {}),
    startRecording:  vi.fn(async () => {}),
    stopRecording:   vi.fn(async () => ({
      videoPath: 'file:///raw.mp4', firstFrameHostSec: 97.5, durationSec: 40, frameCount: 1200, timestampSource: 'host',
    })),
    cancelRecording: vi.fn(async () => {}),
    playAudio:       vi.fn(async () => {}),
    stopAudio:       vi.fn(async () => ({ anchor: { filePosSec: 0, hostSec: 50 } })),
    compose:         vi.fn(async () => ({ path: 'file:///final.mp4', durationSec: 31.5 })),
    saveToGallery:   vi.fn(async () => {}),
    share:           vi.fn(async () => ({ completed: true })),
    canShareTo:      vi.fn(async () => ({ available: false })),
    shareTo:         vi.fn(async () => {}),
    clearCache:      vi.fn(async () => {}),
    openSettings:    vi.fn(async () => {}),
    addListener:     vi.fn(async (_e: string, _h: () => void) => ({ remove: () => {} })),
    removeAllListeners: vi.fn(async () => {}),
  };
}

function makePm() {
  return {
    startSession: vi.fn(async () => ({
      nativeBeat: true, startInMs: 3000, outputLatencyMs: 10, inputLatencyMs: 5, beatStartHostSec: 100,
    })),
    stopSession: vi.fn(async () => ({ pcmBase64: pcm(), sampleRate: 1000, channels: 1, format: 'float32', firstSampleBeatSec: 0.25 })),
    setVoiceFx: vi.fn(async () => {}),
    setBeatVolume: vi.fn(async () => {}),
    checkPermission: vi.fn(async () => ({ microphone: 'granted' })),
    requestPermission: vi.fn(async () => ({ microphone: 'granted' })),
    checkHeadphones: vi.fn(async () => ({ type: 'wired' })),
    addListener: vi.fn(async () => ({ remove: () => {} })),
    removeAllListeners: vi.fn(async () => {}),
  };
}

function makeMaquette(opts: { hasTrack?: boolean; canAdd?: boolean } = {}) {
  const tracks = signal(opts.hasTrack === false ? [] : [{ id: 't1', rawBlob: new Blob(['x']) }]);
  return {
    tracks,
    canAddTrack:   vi.fn(() => opts.canAdd ?? true),
    addTrack:      vi.fn(() => 'new'),
    renameTrack:   vi.fn(),
    removeTrack:   vi.fn(),
    setRecording:  vi.fn(),
    setRecorded:   vi.fn(),
    exportMaquette: vi.fn(async () => new Blob(['wav'], { type: 'audio/wav' })),
  };
}

const CTX: ClipStudioContext = {
  trackId: 7, trackKey: 'C minor', beatmaker: 'kbeats', username: 'nina',
  beatStreamUrl: '/beat', accessToken: 'tok', beatBlob: null, maquetteSec: 120,
  headphone: 'wired', calibratedBtMs: null,
  sessionOpts: () => ({
    useMonitor: true, voiceGain: 1, fx: { lowCutHz: 150, presenceDb: 3.5, clarityDb: 3, reverbWet: 0.1, volume: 1 },
    reverbWet: 0, trackKey: 'C minor', monitorAutotune: false, retuneSpeed: 'natural',
  }),
};

function setup(platform: ClipPlatform, maquette = makeMaquette()) {
  const cam = makeCam();
  const pm = makePm();
  let n = 0;
  const files = { write: vi.fn(async (name: string) => `file:///cache/${name}#${n++}`), webSrc: (u: string) => u };
  TestBed.configureTestingModule({
    providers: [
      SocialClipService,
      { provide: CLIP_CAMERA, useValue: cam },
      { provide: PITCH_MONITOR, useValue: pm },
      { provide: CLIP_FILES, useValue: files },
      { provide: CLIP_PLATFORM, useValue: platform },
      { provide: MobileMaquetteService, useValue: maquette },
      { provide: CLIP_OVERLAY_RENDERER, useValue: {
        overlay: async () => new Blob(['png'], { type: 'image/png' }),
        endCard: async () => new Blob(['png'], { type: 'image/png' }),
      } },
    ],
  });
  return { svc: TestBed.inject(SocialClipService), cam, pm, files, maquette };
}

/** Lance le tournage et laisse filer le décompte (horloges simulées). */
async function roll(svc: SocialClipService): Promise<void> {
  const p = svc.record();
  await vi.advanceTimersByTimeAsync(3200);
  await p;
}

describe('SocialClipService', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => { vi.useRealTimers(); TestBed.resetTestingModule(); });

  it('iOS Playback : caméra avant le son, son joué par le beat natif sans enregistrer la voix', async () => {
    const { svc, cam, pm } = setup('ios');
    await svc.open(CTX);
    await roll(svc);

    expect(svc.stage()).toBe('rolling');
    expect(cam.startRecording.mock.invocationCallOrder[0]).toBeLessThan(pm.startSession.mock.invocationCallOrder[0]);
    const opts = firstArg(pm.startSession as unknown as Mocked) as Record<string, unknown>;
    expect(opts['record']).toBe(false);
    expect(opts['useMonitor']).toBe(false);
    expect(opts['beatStartSec']).toBe(0);
    expect(opts['startDelayMs']).toBe(3000);
    expect(String(opts['beatPath'])).toContain('clip-tour-');
  });

  it('son du tournage sans réverb, rendu final avec la réverb réglée', async () => {
    const { svc, maquette } = setup('ios');
    await svc.open(CTX);
    await roll(svc);
    await svc.stop();
    const calls = (maquette.exportMaquette as unknown as Mocked).mock.calls.map(c => c[0] as Record<string, unknown>);
    expect(calls[0]['noReverb']).toBe(true);                // son joué pendant le tournage
    expect(calls[calls.length - 1]['noReverb']).toBe(false); // clip final
  });

  it('iOS Playback : la vidéo est rognée de (son entendu − 1re frame)', async () => {
    const { svc, cam, maquette } = setup('ios');
    await svc.open(CTX);
    svc.setSegment(10, 30);
    await roll(svc);
    await svc.stop();

    // Ancre 100 s + sortie 10 ms, 1re frame 97,5 s ⇒ 2,51 s à rogner.
    const c = firstArg(cam.compose as unknown as Mocked) as Record<string, number | string>;
    expect(c['videoTrimStartSec']).toBeCloseTo(2.51, 9);
    expect(c['audioSkipSec']).toBe(0);
    expect(c['durationSec']).toBeCloseTo(30, 9);
    expect(c['endCardSec']).toBe(CLIP_END_CARD_SECONDS);
    // Audio final re-rendu sur le passage réellement filmé, carte de fin incluse.
    const last = lastArg(maquette.exportMaquette as unknown as Mocked) as Record<string, unknown>;
    expect(last['segment']).toEqual({ startSec: 10, endSec: 40 });
    expect(last['tailSec']).toBe(CLIP_END_CARD_SECONDS);
    expect(last['format']).toBe('wav');
    expect(svc.stage()).toBe('ready');
    expect(svc.resultUri()).toBe('file:///final.mp4');
  });

  it('iOS Rec : la prise devient une piste, posée comme dans le studio (position + recadrage)', async () => {
    const { svc, maquette } = setup('ios');
    await svc.open(CTX);
    svc.setMode('rec');
    svc.setSegment(10, 30);
    await roll(svc);
    await svc.stop();

    expect(maquette.addTrack).toHaveBeenCalled();
    const [id, blob, , dur, start] = (maquette.setRecorded.mock.calls as unknown[][])[0] as unknown as [string, Blob, number[], number, number];
    expect(id).toBe('new');
    expect(start).toBeCloseTo(10 + 0.25, 9);              // segment + firstSampleBeatSec
    expect(dur).toBeCloseTo(2 - 0.015, 3);                 // 15 ms (sortie + entrée) retirés
    expect(blob.type).toBe('audio/pcm-f32;rate=1000');
  });

  it('Android Rec : prise posée par positionHeardAt, même fonction que la vidéo', async () => {
    const { svc, pm, cam, maquette } = setup('android');
    pm.stopSession.mockResolvedValue({ pcmBase64: pcm(), sampleRate: 1000, channels: 1, format: 'float32', firstSampleHostSec: 49.8 } as never);
    cam.stopRecording.mockResolvedValue({ videoPath: 'file:///raw.mp4', firstFrameHostSec: 47, durationSec: 40, frameCount: 1, timestampSource: 'realtime' });
    await svc.open(CTX);
    svc.setMode('rec');
    svc.setSegment(0, 30);
    await roll(svc);
    expect((firstArg(pm.startSession as unknown as Mocked) as Record<string, unknown>)['record']).toBe(true);
    expect(cam.playAudio).toHaveBeenCalledWith(expect.objectContaining({ delayMs: 3000 }));
    await svc.stop();

    // Voix captée 0,2 s avant le son : retirée, la piste démarre au début du segment.
    const [, , , dur, start] = (maquette.setRecorded.mock.calls as unknown[][])[0] as unknown as [string, Blob, number[], number, number];
    expect(start).toBeCloseTo(0, 9);
    expect(dur).toBeCloseTo(1.8, 3);
    expect((firstArg(cam.compose as unknown as Mocked) as Record<string, number>)['videoTrimStartSec']).toBeCloseTo(3, 9);
  });

  it('Rec sans piste libre : prise « clip seulement », jamais ajoutée à la maquette', async () => {
    const { svc, maquette } = setup('ios', makeMaquette({ canAdd: false }));
    await svc.open(CTX);
    svc.setMode('rec');
    await roll(svc);
    await svc.stop();
    expect(maquette.addTrack).not.toHaveBeenCalled();
    expect(svc.clipOnlyTake()).toBe(true);
    const last = lastArg(maquette.exportMaquette as unknown as Mocked) as { extraTakes: unknown[] };
    expect(last.extraTakes.length).toBe(1);
  });

  it('Rec sans casque : refusé avant tout démarrage', async () => {
    const { svc, cam, pm } = setup('ios');
    await svc.open({ ...CTX, headphone: 'none' });
    svc.setMode('rec');
    await svc.record();
    expect(svc.errorCode()).toBe('NEED_HEADPHONES');
    expect(cam.startRecording).not.toHaveBeenCalled();
    expect(pm.startSession).not.toHaveBeenCalled();
  });

  it('Playback sans voix enregistrée : refusé', async () => {
    const { svc } = setup('ios', makeMaquette({ hasTrack: false }));
    await svc.open(CTX);
    await svc.record();
    expect(svc.errorCode()).toBe('NEED_TRACK');
  });

  it('segment jamais plus long que 45 s', async () => {
    const { svc } = setup('ios');
    await svc.open(CTX);
    svc.setSegment(0, 90);
    expect(svc.segmentSec()).toBe(45);
  });

  it('iOS sans ancre d\'horloge : tournage annulé proprement', async () => {
    const { svc, pm, cam } = setup('ios');
    pm.startSession.mockResolvedValue({ nativeBeat: false } as never);
    await svc.open(CTX);
    await svc.record();
    expect(svc.errorCode()).toBe('SYNC');
    expect(cam.cancelRecording).toHaveBeenCalled();
    expect(pm.stopSession).toHaveBeenCalled();
    expect(svc.stage()).toBe('framing');
  });

  it('interruption caméra pendant le tournage : tout est coupé, la maquette reste intacte', async () => {
    const { svc, cam, pm, maquette } = setup('ios');
    let fire: (() => void) | null = null;
    cam.addListener.mockImplementation(async (e: string, h: () => void) => { if (e === 'interrupted') fire = h; return { remove: () => {} }; });
    await svc.open(CTX);
    await roll(svc);
    fire!();
    await vi.advanceTimersByTimeAsync(10);
    expect(cam.cancelRecording).toHaveBeenCalled();
    expect(pm.stopSession).toHaveBeenCalled();
    expect(svc.stage()).toBe('framing');
    expect(svc.errorCode()).toBe('INTERRUPTED');
    expect(maquette.setRecorded).not.toHaveBeenCalled();
  });

  it('arrêt automatique à la fin du passage', async () => {
    const { svc, cam } = setup('ios');
    await svc.open(CTX);
    svc.setSegment(0, 10);
    await roll(svc);
    await vi.advanceTimersByTimeAsync(10_400);
    expect(cam.stopRecording).toHaveBeenCalled();
  });

  it('caméra refusée : message dédié, aucun aperçu', async () => {
    const { svc, cam } = setup('ios');
    cam.checkPermissions.mockResolvedValue({ camera: 'denied', photos: 'granted' });
    cam.requestPermissions.mockResolvedValue({ camera: 'denied', photos: 'granted' });
    await svc.open(CTX);
    expect(svc.errorCode()).toBe('CAMERA_DENIED');
    expect(cam.startPreview).not.toHaveBeenCalled();
  });

  it('galerie refusée : message dédié', async () => {
    const { svc, cam } = setup('ios');
    cam.saveToGallery.mockRejectedValue(Object.assign(new Error('denied'), { code: 'DENIED' }));
    await svc.open(CTX);
    await roll(svc);
    await svc.stop();
    expect(await svc.saveToGallery()).toBe(false);
    expect(svc.errorCode()).toBe('PHOTOS_DENIED');
  });

  it('Recommencer en Rec : la prise du premier essai est retirée de la maquette', async () => {
    const { svc, maquette } = setup('ios');
    await svc.open(CTX);
    svc.setMode('rec');
    await roll(svc);
    await svc.stop();
    await svc.retake();
    expect(maquette.removeTrack).toHaveBeenCalledWith('new');
  });

  it('fermé pendant la demande de permission caméra : aucun aperçu ne reste allumé', async () => {
    const { svc, cam } = setup('ios');
    let grant!: (v: unknown) => void;
    cam.checkPermissions.mockResolvedValue({ camera: 'prompt', photos: 'granted' });
    cam.requestPermissions.mockReturnValue(new Promise(r => { grant = r; }) as never);
    const opening = svc.open(CTX);
    await vi.advanceTimersByTimeAsync(0);
    await svc.close();
    grant({ camera: 'granted', photos: 'granted' });
    await opening;
    expect(cam.startPreview).not.toHaveBeenCalled();
  });

  it('abandon pendant le démarrage du son : la session micro ouverte ensuite est refermée', async () => {
    const { svc, pm } = setup('ios');
    let started!: (v: unknown) => void;
    pm.startSession.mockReturnValue(new Promise(r => { started = r; }) as never);
    await svc.open(CTX);
    const p = svc.record();
    await vi.advanceTimersByTimeAsync(0);
    await svc.abort(null);
    started({ nativeBeat: true, startInMs: 3000, beatStartHostSec: 100 });
    await vi.advanceTimersByTimeAsync(0);
    await p;
    expect(pm.stopSession).toHaveBeenCalled();
  });

  it('Android Playback + Bluetooth réglé : seule la latence non rapportée est ajoutée', async () => {
    const { svc, cam } = setup('android');
    cam.stopAudio.mockResolvedValue({ anchor: { filePosSec: 0, hostSec: 50 }, reportedLatencyMs: 40, driftMs: 1 } as never);
    cam.stopRecording.mockResolvedValue({ videoPath: 'file:///raw.mp4', firstFrameHostSec: 47, durationSec: 40, frameCount: 1, timestampSource: 'realtime' });
    await svc.open({ ...CTX, headphone: 'bluetooth-a2dp', calibratedBtMs: 220 });
    await roll(svc);
    await svc.stop();
    // 50 − 47 + 0,18 s de Bluetooth non rapporté.
    expect((firstArg(cam.compose as unknown as Mocked) as Record<string, number>)['videoTrimStartSec']).toBeCloseTo(3.18, 9);
    expect(svc.driftMs()).toBe(1);
  });

  it('montage raté en Rec : la prise posée est retirée de la maquette', async () => {
    const { svc, cam, maquette } = setup('ios');
    cam.compose.mockRejectedValue(new Error('export'));
    await svc.open(CTX);
    svc.setMode('rec');
    await roll(svc);
    await svc.stop();
    expect(svc.errorCode()).toBe('FAILED');
    expect(maquette.removeTrack).toHaveBeenCalledWith('new');
  });

  it('fermeture : cache du Mode Clip vidé et aperçu coupé', async () => {
    const { svc, cam } = setup('ios');
    await svc.open(CTX);
    await svc.close();
    expect(cam.stopPreview).toHaveBeenCalled();
    expect(cam.clearCache).toHaveBeenCalledTimes(2);
  });
});
