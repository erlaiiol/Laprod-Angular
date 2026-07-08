import { TestBed } from '@angular/core/testing';
import {
  BeatExtenderService,
  BeatSection,
  BeatAnalysis,
} from './beat-extender.service';

// ── Helpers audio ─────────────────────────────────────────────────────────────

const SR = 44_100;

/** Onde sinusoïdale 60 Hz (dans la bande kick). */
function sineAt60Hz(length: number, amplitude = 0.5): Float32Array {
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    out[i] = amplitude * Math.sin(2 * Math.PI * 60 * i / SR);
  }
  return out;
}

/**
 * Génère un patron de kick synthétique : brève impulsion 60 Hz (décroissance
 * exponentielle) toutes les `period` samples, démarrant à `phaseS` secondes.
 * Entièrement dans la bande passe-bas 200 Hz → exploitable par _refineBeatGrid.
 */
function kickPattern(bpm: number, phaseS: number, durationS: number): Float32Array {
  const period  = Math.round((60 / bpm) * SR);
  const kickLen = Math.round(0.015 * SR);
  const phase   = Math.round(phaseS * SR);
  const out     = new Float32Array(Math.round(durationS * SR));
  for (let b = 0; phase + b * period < out.length; b++) {
    const pos = Math.round(phase + b * period);
    for (let j = 0; j < kickLen && pos + j < out.length; j++) {
      const env = Math.exp(-j / (kickLen * 0.3));
      out[pos + j] += 0.8 * env * Math.sin(2 * Math.PI * 60 * j / SR);
    }
  }
  return out;
}

/** Construit une BeatAnalysis minimale cohérente avec l'interface complète. */
function mockAnalysis(samplesPerSection: number, numSections: number): BeatAnalysis {
  const samplesPerBeat    = Math.round(samplesPerSection / 32);
  const samplesPerMeasure = Math.round(samplesPerSection / 8);
  const sections: BeatSection[] = Array.from({ length: numSections }, (_, i) => ({
    index:            i,
    name:             i === 0 ? 'Intro' : i === numSections - 1 ? 'Outro' : 'Couplet',
    startSample:      i * samplesPerSection,
    lengthSamples:    samplesPerSection,
    startTime:        (i * samplesPerSection) / SR,
    duration:         samplesPerSection / SR,
    measures:         8,
    rms:              0.4,
    transientDensity: 3,
    hasDrums:         true,
    energy:           { low: 0.1, mid: 0.3, high: 0.05 },
    waveform:         Array<number>(60).fill(0.5),
  }));
  const sectionDurationS   = samplesPerSection / SR;
  const maxSectionCount    = Math.floor(180 / sectionDurationS);
  const maxDurationSamples = maxSectionCount * samplesPerSection;
  return {
    sections,
    sampleRate:        SR,
    totalSamples:      numSections * samplesPerSection,
    usableSamples:     numSections * samplesPerSection,
    fadeStartSample:   numSections * samplesPerSection,
    bpm:               120,
    beatPhase:         0,
    samplesPerBeat,
    samplesPerMeasure,
    samplesPerSection,
    maxDurationSamples,
    maxDurationSec:    maxSectionCount * sectionDurationS,
  };
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('BeatExtenderService', () => {

  let svc: BeatExtenderService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [BeatExtenderService] });
    svc = TestBed.inject(BeatExtenderService);
  });

  // ── _rmsOf ──────────────────────────────────────────────────────────────────

  describe('_rmsOf()', () => {
    it('retourne 0 pour un buffer silencieux', () => {
      expect(svc['_rmsOf'](new Float32Array(100))).toBeCloseTo(0, 5);
    });

    it('retourne 0.5 pour un signal constant à 0.5', () => {
      expect(svc['_rmsOf'](new Float32Array(100).fill(0.5))).toBeCloseTo(0.5, 4);
    });

    it('retourne 1/√2 pour une onde sinusoïdale d\'amplitude 1', () => {
      const sine = new Float32Array(SR);
      for (let i = 0; i < sine.length; i++) sine[i] = Math.sin(2 * Math.PI * 440 * i / SR);
      expect(svc['_rmsOf'](sine)).toBeCloseTo(1 / Math.sqrt(2), 2);
    });

    it('ne lève pas d\'erreur sur un buffer vide', () => {
      expect(() => svc['_rmsOf'](new Float32Array(0))).not.toThrow();
    });
  });

  // ── _miniWaveform ────────────────────────────────────────────────────────────

  describe('_miniWaveform()', () => {
    it('retourne exactement `points` barres', () => {
      expect(svc['_miniWaveform'](sineAt60Hz(4_096), 60).length).toBe(60);
    });

    it('toutes les valeurs sont dans [0, 1]', () => {
      for (const v of svc['_miniWaveform'](sineAt60Hz(4_096, 0.8), 60)) {
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(1);
      }
    });

    it('la valeur max normalisée est 1', () => {
      expect(Math.max(...svc['_miniWaveform'](sineAt60Hz(4_096, 0.7), 60))).toBeCloseTo(1, 2);
    });

    it('fonctionne avec points = 1', () => {
      const wf = svc['_miniWaveform'](sineAt60Hz(1_000), 1);
      expect(wf.length).toBe(1);
      expect(wf[0]).toBeCloseTo(1, 2);
    });
  });

  // ── _countTransients ─────────────────────────────────────────────────────────

  describe('_countTransients()', () => {
    it('retourne 0 pour un signal constant', () => {
      expect(svc['_countTransients'](new Float32Array(4_000).fill(0.3), SR)).toBe(0);
    });

    it('retourne 0 pour un buffer silencieux', () => {
      expect(svc['_countTransients'](new Float32Array(4_000), SR)).toBe(0);
    });

    it('détecte les transients dans un signal par impulsions', () => {
      const winSize = Math.round(10 * SR / 1_000);
      const samples = new Float32Array(winSize * 10);
      for (let w = 0; w < 10; w += 3) samples.fill(0.9, w * winSize, (w + 1) * winSize);
      expect(svc['_countTransients'](samples, SR)).toBeGreaterThan(0);
    });
  });

  // ── _detectFadeStart ─────────────────────────────────────────────────────────

  describe('_detectFadeStart()', () => {
    it('retourne samples.length quand le niveau est constant', () => {
      const s = sineAt60Hz(SR);
      expect(svc['_detectFadeStart'](s, SR)).toBe(s.length);
    });

    it('détecte un fade-out en fin de fichier', () => {
      const total   = SR * 4;
      const samples = new Float32Array(total);
      for (let i = 0; i < SR * 3; i++) samples[i] = 0.8;
      for (let i = SR * 3; i < total; i++) samples[i] = 0.8 * (1 - (i - SR * 3) / SR);
      const fade = svc['_detectFadeStart'](samples, SR);
      expect(fade).toBeLessThan(total);
      expect(fade).toBeGreaterThan(SR * 2);
    });
  });

  // ── _crossfade ────────────────────────────────────────────────────────────────

  describe('_crossfade()', () => {
    it('longueur de sortie = a.length + b.length - xfade', () => {
      expect(svc['_crossfade'](sineAt60Hz(1_000), sineAt60Hz(800, 0.3), 100).length).toBe(1_700);
    });

    it('les premiers samples (hors zone fade) reflètent `a`', () => {
      const a   = new Float32Array(500).fill(0.7);
      const out = svc['_crossfade'](a, new Float32Array(500).fill(0.2), 50);
      expect(out[0]).toBeCloseTo(0.7, 3);
    });

    it('le milieu du fade est une transition douce (ni 0 ni max)', () => {
      const out = svc['_crossfade'](new Float32Array(200).fill(1.0), new Float32Array(200).fill(0), 100);
      const mid = out[150];
      expect(mid).toBeGreaterThan(0);
      expect(mid).toBeLessThan(1);
    });

    it('micro-fade 3 ms (≈ 132 samples) : ne lève pas d\'erreur', () => {
      const xfade = Math.round(0.003 * SR);
      const out   = svc['_crossfade'](sineAt60Hz(SR), sineAt60Hz(SR, 0.4), xfade);
      expect(out.length).toBe(SR + SR - xfade);
    });

    it('xfade > min(a, b) : ne lève pas d\'erreur', () => {
      expect(() => svc['_crossfade'](sineAt60Hz(100), sineAt60Hz(50, 0.3), 80)).not.toThrow();
    });
  });

  // ── _lowpass / _highpass ─────────────────────────────────────────────────────

  describe('_lowpass()', () => {
    it('retourne un buffer de même longueur', () => {
      expect(svc['_lowpass'](sineAt60Hz(1_000), SR, 300).length).toBe(1_000);
    });

    it('préserve quasi-intégralement un signal 60 Hz (sous la coupure 200 Hz)', () => {
      const sig = sineAt60Hz(SR, 1.0);
      const raw = svc['_rmsOf'](sig.slice(200));
      const out = svc['_rmsOf'](svc['_lowpass'](sig, SR, 200).slice(200));
      expect(out).toBeGreaterThan(raw * 0.8);
    });

    it('atténue fortement un signal à sr/4 (bien au-dessus de 200 Hz)', () => {
      const hf = new Float32Array(4_096);
      for (let i = 0; i < hf.length; i++) hf[i] = Math.sin(2 * Math.PI * i / 4);
      const raw = svc['_rmsOf'](hf);
      expect(svc['_rmsOf'](svc['_lowpass'](hf, SR, 200))).toBeLessThan(raw * 0.3);
    });
  });

  describe('_highpass()', () => {
    it('retourne un buffer de même longueur', () => {
      expect(svc['_highpass'](sineAt60Hz(1_000), SR, 3_000).length).toBe(1_000);
    });

    it('atténue un signal 60 Hz (sous la coupure 3 kHz)', () => {
      const sig = sineAt60Hz(SR, 0.8);
      const raw = svc['_rmsOf'](sig.slice(200));
      expect(svc['_rmsOf'](svc['_highpass'](sig, SR, 3_000).slice(200))).toBeLessThan(raw * 0.3);
    });
  });

  // ── _corrAt ──────────────────────────────────────────────────────────────────

  describe('_corrAt()', () => {
    it('au lag 0 : retourne la somme des carrés', () => {
      const odf = new Float32Array([1, 2, 3, 4]);
      expect(svc['_corrAt'](odf, 0)).toBeCloseTo(30, 4); // 1+4+9+16
    });

    it('retourne 0 si lag ≥ odf.length', () => {
      expect(svc['_corrAt'](new Float32Array([1, 2, 3]), 5)).toBe(0);
    });

    it('retourne 0 sur un buffer vide', () => {
      expect(svc['_corrAt'](new Float32Array(0), 1)).toBe(0);
    });

    it('corrélation max au lag de la période pour un signal périodique', () => {
      const period = 10;
      const odf    = new Float32Array(100);
      for (let i = 0; i < 100; i += period) odf[i] = 1;
      expect(svc['_corrAt'](odf, period)).toBeGreaterThan(svc['_corrAt'](odf, period + 3));
    });
  });

  // ── _refineBeatGrid ──────────────────────────────────────────────────────────

  describe('_refineBeatGrid()', () => {
    it('ne lève pas d\'erreur sur un buffer silencieux', () => {
      expect(() => svc['_refineBeatGrid'](new Float32Array(SR * 5), SR, 120)).not.toThrow();
    });

    it('beatPhase est toujours dans [0, 8 beats]', () => {
      const bpm = 120;
      const { samplesPerBeat, beatPhase } = svc['_refineBeatGrid'](kickPattern(bpm, 0.1, 10), SR, bpm);
      expect(beatPhase).toBeGreaterThanOrEqual(0);
      expect(beatPhase).toBeLessThanOrEqual(samplesPerBeat * 8);
    });

    it('samplesPerBeat ± 15 % du nominal à 120 BPM', () => {
      const bpm     = 120;
      const nominal = Math.round((60 / bpm) * SR);
      const { samplesPerBeat } = svc['_refineBeatGrid'](kickPattern(bpm, 0, 10), SR, bpm);
      expect(samplesPerBeat).toBeGreaterThan(nominal * 0.85);
      expect(samplesPerBeat).toBeLessThan(nominal * 1.15);
    });

    it('samplesPerBeat ± 15 % du nominal à 80 BPM', () => {
      const bpm     = 80;
      const nominal = Math.round((60 / bpm) * SR);
      const { samplesPerBeat } = svc['_refineBeatGrid'](kickPattern(bpm, 0, 15), SR, bpm);
      expect(samplesPerBeat).toBeGreaterThan(nominal * 0.85);
      expect(samplesPerBeat).toBeLessThan(nominal * 1.15);
    });

    it('détecte une phase de 250 ms à ±50 ms près', () => {
      const bpm    = 120;
      const phaseS = 0.25;
      const { beatPhase } = svc['_refineBeatGrid'](kickPattern(bpm, phaseS, 10), SR, bpm);
      expect(Math.abs(beatPhase - Math.round(phaseS * SR))).toBeLessThan(Math.round(0.050 * SR));
    });

    it('fallback BPM nominal si signal trop bruité (écart > 5 %)', () => {
      const noise = new Float32Array(SR * 5);
      for (let i = 0; i < noise.length; i++) noise[i] = (Math.random() - 0.5) * 5e-4;
      const bpm     = 120;
      const nominal = Math.round((60 / bpm) * SR);
      const { samplesPerBeat } = svc['_refineBeatGrid'](noise, SR, bpm);
      expect(samplesPerBeat).toBeGreaterThanOrEqual(nominal * 0.95);
      expect(samplesPerBeat).toBeLessThanOrEqual(nominal * 1.05);
    });
  });

  // ── _assignNames ─────────────────────────────────────────────────────────────

  describe('_assignNames()', () => {
    function section(override: Partial<BeatSection> = {}): BeatSection {
      return {
        index: 0, name: '', startSample: 0, lengthSamples: SR,
        startTime: 0, duration: 1, measures: 8, rms: 0.4,
        transientDensity: 3, hasDrums: true,
        energy: { low: 0.1, mid: 0.3, high: 0.05 }, waveform: [],
        ...override,
      };
    }

    it('liste vide : ne lève pas d\'erreur', () => {
      expect(() => svc['_assignNames']([])).not.toThrow();
    });

    it('première section = Intro', () => {
      const secs = [section({ index: 0 }), section({ index: 1 }), section({ index: 2 })];
      svc['_assignNames'](secs);
      expect(secs[0].name).toBe('Intro');
    });

    it('dernière section = Outro', () => {
      const secs = [section({ index: 0 }), section({ index: 1 }), section({ index: 2 })];
      svc['_assignNames'](secs);
      expect(secs[2].name).toBe('Outro');
    });

    it('section rms max + densité max = Refrain', () => {
      const secs = [
        section({ index: 0, rms: 0.3, transientDensity: 2 }),
        section({ index: 1, rms: 1.0, transientDensity: 10 }),
        section({ index: 2, rms: 0.2, transientDensity: 1 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[1].name).toBe('Refrain');
    });

    it('double Refrain → Refrain 1 / Refrain 2', () => {
      const secs = [
        section({ index: 0, rms: 0.3, transientDensity: 2 }),
        section({ index: 1, rms: 1.0, transientDensity: 10 }),
        section({ index: 2, rms: 1.0, transientDensity: 10 }),
        section({ index: 3, rms: 0.2, transientDensity: 1 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[1].name).toBe('Refrain 1');
      expect(secs[2].name).toBe('Refrain 2');
    });

    it('section sans drums + faible volume = Pont', () => {
      const secs = [
        section({ index: 0, rms: 0.5, transientDensity: 4 }),
        section({ index: 1, rms: 0.05, transientDensity: 0.5, hasDrums: false }),
        section({ index: 2, rms: 0.3, transientDensity: 3 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[1].name).toBe('Pont');
    });
  });

  // ── createExtendedBeat ────────────────────────────────────────────────────────

  describe('createExtendedBeat()', () => {
    const SEC  = SR;       // 1 s par section
    const NSEC = 4;        // 4 sections

    it('retourne un Blob audio/wav', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'end');
      expect(result.blob.type).toBe('audio/wav');
      expect(result.blob.size).toBeGreaterThan(44);
    });

    it('mode=end : la sortie est plus longue que l\'original', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'end');
      expect(result.blob.size).toBeGreaterThan(44 + NSEC * SEC * 2);
    });

    it('mode=end : la sortie ne dépasse pas original + 1 section complète', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'end');
      expect(result.blob.size).toBeLessThan(44 + (NSEC * SEC + SEC) * 2);
    });

    it('mode=after : la sortie est plus longue que l\'original', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'after');
      expect(result.blob.size).toBeGreaterThan(44 + NSEC * SEC * 2);
    });

    it('commence par les 4 octets RIFF (WAV valide)', async () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 0, 'end');
      const view     = new DataView(await result.blob.arrayBuffer());
      const riff     = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
      expect(riff).toBe('RIFF');
    });

    it('addedStartSample est dans [0, totalSamples]', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'end');
      expect(result.addedStartSample).toBeGreaterThanOrEqual(0);
      expect(result.addedStartSample).toBeLessThanOrEqual(result.totalSamples);
    });

    it('addedStartSample + addedLengthSamples ≤ totalSamples', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'after');
      expect(result.addedStartSample + result.addedLengthSamples).toBeLessThanOrEqual(result.totalSamples);
    });

    it('totalSamples = (blob.size - 44) / 2 (WAV 16-bit mono)', async () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const result   = svc.createExtendedBeat(sineAt60Hz(NSEC * SEC), SR, analysis, 1, 'end');
      const ab       = await result.blob.arrayBuffer();
      expect(ab.byteLength).toBe(44 + result.totalSamples * 2);
    });

    it('micro-fade 3 ms est beaucoup plus court qu\'une mesure (pas de doublage musical)', () => {
      const analysis = mockAnalysis(SEC, NSEC);
      const xfade    = Math.round(0.003 * SR);
      expect(xfade).toBeLessThan(analysis.samplesPerMeasure);
    });
  });
});
