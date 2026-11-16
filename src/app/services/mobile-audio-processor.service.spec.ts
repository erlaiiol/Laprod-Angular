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

  it('fromSec > durée existing — la nouvelle prise reste à sa position, trou silencieux', async () => {
    const existing = makeF32Blob(2, 0.5);
    const newAudio = makeF32Blob(1, 0.8);

    const spliced = await svc.spliceAudio(existing, newAudio, 3);
    const data    = await readBlob(spliced);

    // 2 s d'existant + 1 s de silence + 1 s de nouvelle prise = 4 s
    expect(data.length).toBe(Math.round(4 * SR));
    expect(data[Math.round(2.5 * SR)]).toBe(0);
    expect(data[Math.round(3.5 * SR)]).toBeCloseTo(0.8, 5);
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

// ── Réglages "Boue" (coupe-bas) et "Présence" ─────────────────────────────────

describe('MobileAudioProcessorService — réglages boue / présence', () => {

  let svc: MobileAudioProcessorService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [MobileAudioProcessorService, ...testProviders] });
    svc = TestBed.inject(MobileAudioProcessorService);
  });

  function sineBlob(hz: number, sec = 1, amp = 0.05): Blob {
    const n = Math.round(sec * SR);
    const s = new Float32Array(n);
    for (let i = 0; i < n; i++) s[i] = amp * Math.sin(2 * Math.PI * hz * i / SR);
    return new Blob([s.buffer], { type: 'audio/pcm-f32' });
  }

  /** RMS sur la seconde moitié (régime établi, hors attaque du gate/compresseurs). */
  function rms(x: Float32Array): number {
    const half = x.subarray(Math.floor(x.length / 2));
    let acc = 0;
    for (const v of half) acc += v * v;
    return Math.sqrt(acc / half.length);
  }

  const base = { volume: 1, useAutotune: false, reverbWet: 0, clarityDb: 0, lowCutHz: 150, presenceDb: 3.5 };

  it('boue 220 Hz retire nettement plus de grave (100 Hz) que 80 Hz', async () => {
    const blob = sineBlob(100);
    const at80  = await svc.processVocalTrack({ blob, settings: { ...base, lowCutHz: 80 },  trackKey: '' });
    const at220 = await svc.processVocalTrack({ blob, settings: { ...base, lowCutHz: 220 }, trackKey: '' });
    expect(rms(at220)).toBeLessThan(rms(at80) * 0.5);
  });

  it('présence "Devant" (6 dB) fait ressortir 2,5 kHz par rapport à "Douce" (0 dB)', async () => {
    const blob = sineBlob(2_500);
    const soft  = await svc.processVocalTrack({ blob, settings: { ...base, presenceDb: 0 }, trackKey: '' });
    const front = await svc.processVocalTrack({ blob, settings: { ...base, presenceDb: 6 }, trackKey: '' });
    expect(rms(front)).toBeGreaterThan(rms(soft) * 1.2);
  });
});

// ── Chaîne vocale : calage temporel et écoute en direct ───────────────────────

describe('MobileAudioProcessorService — calage et chaîne temps réel', () => {

  let svc: MobileAudioProcessorService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [MobileAudioProcessorService, ...testProviders] });
    svc = TestBed.inject(MobileAudioProcessorService);
  });

  const settings = { volume: 1, useAutotune: false, reverbWet: 0, clarityDb: 0, lowCutHz: 80, presenceDb: 0 };

  /** Silence puis salve de 1 kHz démarrant exactement à `atSec`. */
  function burstBlob(atSec: number, sec = 1.5): Blob {
    const s = new Float32Array(Math.round(sec * SR));
    for (let i = Math.round(atSec * SR); i < s.length; i++) s[i] = 0.3 * Math.sin(2 * Math.PI * 1000 * i / SR);
    return new Blob([s.buffer], { type: 'audio/pcm-f32' });
  }

  function onset(x: Float32Array, threshold = 0.02): number {
    for (let i = 0; i < x.length; i++) if (Math.abs(x[i]) > threshold) return i;
    return -1;
  }

  it('la voix traitée reste calée sur la voix brute (retard des compresseurs retiré)', async () => {
    const out = await svc.processVocalTrack({ blob: burstBlob(0.5), settings, trackKey: '' });
    expect(out.length).toBe(Math.round(1.5 * SR));               // durée inchangée
    const lateMs = (onset(out) - 0.5 * SR) / SR * 1000;
    expect(Math.abs(lateMs)).toBeLessThan(3);
  });

  it('retard de la chaîne : mesuré pour la qualité fidèle, nul pour la légère', async () => {
    const full = await svc.vocalChainLatencySec('full');
    expect(full).toBeGreaterThanOrEqual(0);
    expect(full).toBeLessThan(0.1);
    expect(await svc.vocalChainLatencySec('light')).toBe(0);
  });

  it('chaîne temps réel : réglages audibles dans les deux qualités, modifiables à la volée', async () => {
    for (const quality of ['light', 'full'] as const) {
      const render = async (lowCutHz: number, live: boolean) => {
        const n   = SR;
        const ctx = new OfflineAudioContext(1, n, SR);
        const buf = ctx.createBuffer(1, n, SR);
        const d   = buf.getChannelData(0);
        for (let i = 0; i < n; i++) d[i] = 0.05 * Math.sin(2 * Math.PI * 100 * i / SR);
        const src = ctx.createBufferSource();
        src.buffer = buf;
        // `live` : la chaîne démarre à 80 Hz puis reçoit le réglage pendant le rendu.
        const chain = svc.createLiveVoiceChain(ctx, { ...settings, lowCutHz: live ? 80 : lowCutHz }, quality);
        src.connect(chain.input);
        chain.dry.connect(ctx.destination);
        chain.wet.connect(ctx.destination);
        if (live) chain.update({ ...settings, lowCutHz });
        src.start(0);
        const out  = (await ctx.startRendering()).getChannelData(0).subarray(n / 2);
        let acc = 0;
        for (const v of out) acc += v * v;
        return Math.sqrt(acc / out.length);
      };
      const at80 = await render(80, false);
      expect(await render(220, false)).toBeLessThan(at80 * 0.5);   // réglage initial entendu
      expect(await render(220, true)).toBeLessThan(at80 * 0.5);    // réglage changé en cours de lecture
    }
  });

  it('réverb partagée : convolver prêt au sample rate du contexte', async () => {
    const ctx  = new OfflineAudioContext(1, 4410, 44_100);
    const conv = await svc.createLiveReverb(ctx);
    expect(conv.buffer!.sampleRate).toBe(44_100);
    expect(conv.normalize).toBe(false);
  });

  it('autotuneOnly : voix brute sans effets (aucune réverb ni compression ajoutée)', async () => {
    const blob = burstBlob(0.2, 1);
    const out  = await svc.autotuneOnly(blob, '');
    const raw  = new Float32Array(await blob.arrayBuffer());
    expect(out.length).toBe(raw.length);
    expect(out[Math.round(0.6 * SR)]).toBeCloseTo(raw[Math.round(0.6 * SR)], 5);
  });
});
