import { TestBed } from '@angular/core/testing';
import { OfflineAudioContext, AudioBuffer } from 'node-web-audio-api';
import { MobileAudioProcessorService, OFFLINE_AUDIO_CONTEXT } from './mobile-audio-processor.service';

// jsdom n'implémente pas le Web Audio API (OfflineAudioContext...) qu'utilise
// MobileAudioProcessorService pour décoder/mixer le PCM natif iOS/Android.
// node-web-audio-api fournit une implémentation Rust fidèle (via NAPI), fournie
// ici via le token d'injection OFFLINE_AUDIO_CONTEXT — le service ne sait pas
// qu'il tourne en test, aucun global n'est modifié.
const testProviders = [{ provide: OFFLINE_AUDIO_CONTEXT, useValue: OfflineAudioContext }];

// ── Helpers ───────────────────────────────────────────────────────────────────

const SR = 48_000;

/**
 * Crée un Blob PCM Float32 rempli de la valeur `fill` sur `durationSec` secondes.
 * Surcharge avec amplitude : makeF32Blob(dur) → fill=0.1 par défaut.
 */
function makeF32Blob(durationSec: number, fill = 0.1): Blob {
  const samples = new Float32Array(Math.round(durationSec * SR)).fill(fill);
  return new Blob([samples.buffer], { type: 'audio/pcm-f32' });
}

/** Décode un Blob PCM Float32 en Float32Array directement (sans AudioContext). */
async function readBlob(blob: Blob): Promise<Float32Array> {
  return new Float32Array(await blob.arrayBuffer());
}

// ── Tests spliceAudio ─────────────────────────────────────────────────────────

describe('MobileAudioProcessorService — spliceAudio', () => {

  let svc: MobileAudioProcessorService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: testProviders });
    svc = TestBed.inject(MobileAudioProcessorService);
  });

  it('résultat a la bonne longueur (fromSec dans le milieu)', async () => {
    const existing = makeF32Blob(4, 0.3);   // 4 s, val 0.3
    const newAudio = makeF32Blob(2, 0.7);   // 2 s, val 0.7

    const spliced = await svc.spliceAudio(existing, newAudio, 2);
    const data    = await readBlob(spliced);

    // Attendu : 2 s de existing + 2 s de newAudio
    expect(data.length).toBe(Math.round(4 * SR));
  });

  it('première moitié provient de existing', async () => {
    const existing = makeF32Blob(4, 0.3);
    const newAudio = makeF32Blob(2, 0.7);

    const spliced = await svc.spliceAudio(existing, newAudio, 2);
    const data    = await readBlob(spliced);

    // Les keepSamples premiers doivent valoir ~0.3
    const keepSamples = Math.round(2 * SR);
    for (let i = 0; i < keepSamples; i += 4800) {
      expect(data[i]).toBeCloseTo(0.3, 3);
    }
  });

  it('deuxième moitié provient de newAudio', async () => {
    const existing = makeF32Blob(4, 0.3);
    const newAudio = makeF32Blob(2, 0.7);

    const spliced = await svc.spliceAudio(existing, newAudio, 2);
    const data    = await readBlob(spliced);

    const keepSamples = Math.round(2 * SR);
    for (let i = keepSamples; i < data.length; i += 4800) {
      expect(data[i]).toBeCloseTo(0.7, 3);
    }
  });

  it('fromSec = 0 retourne uniquement newAudio', async () => {
    const existing = makeF32Blob(4, 0.3);
    const newAudio = makeF32Blob(2, 0.9);

    const spliced = await svc.spliceAudio(existing, newAudio, 0);
    const data    = await readBlob(spliced);

    expect(data.length).toBe(Math.round(2 * SR));
    for (let i = 0; i < data.length; i += 4800) {
      expect(data[i]).toBeCloseTo(0.9, 3);
    }
  });

  it('fromSec > durée existing — clamp sur la fin du buffer', async () => {
    const existing = makeF32Blob(2, 0.5);
    const newAudio = makeF32Blob(1, 0.8);

    const spliced = await svc.spliceAudio(existing, newAudio, 999);
    const data    = await readBlob(spliced);

    // keepSamples clampé à existBuf.length (2 s) → total = 2 s + 1 s = 3 s
    expect(data.length).toBe(Math.round(3 * SR));
  });

  it('retourne un Blob de type audio/pcm-f32', async () => {
    const existing = makeF32Blob(2, 0.1);
    const newAudio = makeF32Blob(1, 0.2);

    const spliced = await svc.spliceAudio(existing, newAudio, 1);
    expect(spliced.type).toBe('audio/pcm-f32');
  });

  it('splice avec fromSec fractionnaire est précis à ±1 sample', async () => {
    const existing = makeF32Blob(4, 0.3);
    const newAudio = makeF32Blob(2, 0.7);

    const spliced = await svc.spliceAudio(existing, newAudio, 1.5);
    const data    = await readBlob(spliced);

    const expectedKeep = Math.round(1.5 * SR);
    const expectedLen  = expectedKeep + Math.round(2 * SR);
    expect(Math.abs(data.length - expectedLen)).toBeLessThanOrEqual(1);
  });
});

// ── Tests quickMix ────────────────────────────────────────────────────────────

describe('MobileAudioProcessorService — quickMix', () => {

  let svc: MobileAudioProcessorService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: testProviders });
    svc = TestBed.inject(MobileAudioProcessorService);
  });

  it('retourne un AudioBuffer', async () => {
    const beat  = makeF32Blob(2);
    const vocal = makeF32Blob(1);
    const buf   = await svc.quickMix({
      vocals: [{ blob: vocal, volume: 1.0 }],
      beatStreamUrl: '', beatGain: 0.5, accessToken: '', beatBlob: beat,
    });
    expect(buf).toBeInstanceOf(AudioBuffer);
  });

  it('longueur = min(max durée vocaux, durée beat)', async () => {
    const beat  = makeF32Blob(3);   // 3 s
    const vocal = makeF32Blob(1);   // 1 s → vocalLen=1s < beatLen=3s → total = 1 s
    const buf   = await svc.quickMix({
      vocals: [{ blob: vocal, volume: 1.0 }],
      beatStreamUrl: '', beatGain: 0.5, accessToken: '', beatBlob: beat,
    });
    expect(buf.length).toBe(Math.round(1 * SR));
  });

  it('sans piste vocale — longueur égale à la durée du beat', async () => {
    const beat = makeF32Blob(2);
    const buf  = await svc.quickMix({
      vocals: [], beatStreamUrl: '', beatGain: 1.0, accessToken: '', beatBlob: beat,
    });
    expect(buf.length).toBe(Math.round(2 * SR));
  });

  it('peak guard — aucun sample ne dépasse 1.0 en valeur absolue', async () => {
    // vocal + beat tous deux à amplitude 1.0 : sans peak guard la somme dépasse 1
    const beat  = makeF32Blob(1, 1.0);
    const vocal = makeF32Blob(1, 1.0);
    const buf   = await svc.quickMix({
      vocals: [{ blob: vocal, volume: 1.0 }],
      beatStreamUrl: '', beatGain: 1.0, accessToken: '', beatBlob: beat,
    });
    let peak = 0;
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const ch = buf.getChannelData(c);
      for (let i = 0; i < ch.length; i++) {
        if (Math.abs(ch[i]) > peak) peak = Math.abs(ch[i]);
      }
    }
    expect(peak).toBeLessThanOrEqual(1.0);
  });

  it('volume 0 sur la piste vocale — le beat reste audible', async () => {
    const beat  = makeF32Blob(1, 0.5);
    const vocal = makeF32Blob(1, 1.0);
    const buf   = await svc.quickMix({
      vocals: [{ blob: vocal, volume: 0 }],
      beatStreamUrl: '', beatGain: 1.0, accessToken: '', beatBlob: beat,
    });
    const ch        = buf.getChannelData(0);
    const hasSignal = Array.from(ch).some(v => Math.abs(v) > 0.01);
    expect(hasSignal).toBe(true);
  });

  it('deux pistes vocales sont mixées ensemble', async () => {
    const beat  = makeF32Blob(1, 0);    // beat muet pour isoler le test
    const v1    = makeF32Blob(1, 0.2);
    const v2    = makeF32Blob(1, 0.3);
    const buf   = await svc.quickMix({
      vocals: [{ blob: v1, volume: 1.0 }, { blob: v2, volume: 1.0 }],
      beatStreamUrl: '', beatGain: 0.0, accessToken: '', beatBlob: beat,
    });
    // Avec beat muet : le signal résultant doit contenir les deux voix (~0.5)
    const ch        = buf.getChannelData(0);
    const hasSignal = Array.from(ch).some(v => Math.abs(v) > 0.05);
    expect(hasSignal).toBe(true);
  });
});
