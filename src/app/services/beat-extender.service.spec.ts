import { TestBed } from '@angular/core/testing';
import { BeatExtenderService, BeatSection, BeatAnalysis } from './beat-extender.service';

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Génère un buffer de samples sinusoïdaux normalisés. */
function sineWave(length: number, amplitude = 0.5): Float32Array {
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    out[i] = amplitude * Math.sin(2 * Math.PI * i / 128);
  }
  return out;
}

/** Construit une BeatAnalysis minimale pour les tests de createExtendedBeat. */
function mockAnalysis(
  sampleRate:        number,
  samplesPerSection: number,
  numSections:       number,
): BeatAnalysis {
  const samplesPerMeasure = samplesPerSection / 8;
  const sections: BeatSection[] = Array.from({ length: numSections }, (_, i) => ({
    index:            i,
    name:             i === 0 ? 'Intro' : i === numSections - 1 ? 'Outro' : 'Couplet',
    startSample:      i * samplesPerSection,
    lengthSamples:    samplesPerSection,
    startTime:        (i * samplesPerSection) / sampleRate,
    duration:         samplesPerSection / sampleRate,
    measures:         8,
    rms:              0.4,
    transientDensity: 3,
    hasDrums:         true,
    energy:           { low: 0.1, mid: 0.3, high: 0.05 },
    waveform:         Array(60).fill(0.5),
  }));

  const sectionDurationS   = samplesPerSection / sampleRate;
  const maxSectionCount    = Math.floor(180 / sectionDurationS);
  const maxDurationSamples = maxSectionCount * samplesPerSection;

  return {
    sections,
    sampleRate,
    totalSamples:      numSections * samplesPerSection,
    usableSamples:     numSections * samplesPerSection,
    fadeStartSample:   numSections * samplesPerSection,
    bpm:               120,
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
      const r = svc['_rmsOf'](new Float32Array(100));
      expect(r).toBeCloseTo(0, 5);
    });

    it('retourne le RMS correct pour des samples constants', () => {
      const samples = new Float32Array(100).fill(0.5);
      expect(svc['_rmsOf'](samples)).toBeCloseTo(0.5, 4);
    });

    it('ne lève pas d\'erreur sur un buffer vide', () => {
      expect(() => svc['_rmsOf'](new Float32Array(0))).not.toThrow();
    });
  });

  // ── _miniWaveform ────────────────────────────────────────────────────────────

  describe('_miniWaveform()', () => {
    it('retourne exactement `points` barres', () => {
      const wf = svc['_miniWaveform'](sineWave(4_096), 60);
      expect(wf.length).toBe(60);
    });

    it('toutes les valeurs sont dans [0, 1]', () => {
      const wf = svc['_miniWaveform'](sineWave(4_096, 0.8), 60);
      for (const v of wf) {
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(1);
      }
    });

    it('la valeur max normalisée est 1', () => {
      const wf = svc['_miniWaveform'](sineWave(4_096, 0.7), 60);
      expect(Math.max(...wf)).toBeCloseTo(1, 2);
    });
  });

  // ── _countTransients ─────────────────────────────────────────────────────────

  describe('_countTransients()', () => {
    it('retourne 0 pour un signal constant (pas de transient)', () => {
      const samples = new Float32Array(4_000).fill(0.3);
      expect(svc['_countTransients'](samples, 44_100)).toBe(0);
    });

    it('détecte les transients dans un signal par impulsions', () => {
      const sr      = 44_100;
      const winSize = Math.round(10 * sr / 1000); // 10 ms
      const samples = new Float32Array(winSize * 10);
      // Impulsion forte toutes les 3 fenêtres
      for (let w = 0; w < 10; w += 3) {
        samples.fill(0.9, w * winSize, (w + 1) * winSize);
      }
      const count = svc['_countTransients'](samples, sr);
      expect(count).toBeGreaterThan(0);
    });
  });

  // ── _detectFadeStart ─────────────────────────────────────────────────────────

  describe('_detectFadeStart()', () => {
    it('retourne samples.length quand il n\'y a pas de fade', () => {
      const samples = sineWave(44_100, 0.5);   // 1 s constant
      const result  = svc['_detectFadeStart'](samples, 44_100);
      expect(result).toBe(samples.length);
    });

    it('détecte un fade-out en fin de fichier', () => {
      const sr    = 44_100;
      const total = sr * 4;  // 4 s
      const samples = new Float32Array(total);

      // 3 s de signal fort
      for (let i = 0; i < sr * 3; i++) samples[i] = 0.8;
      // Dernière seconde : fade progressif vers 0
      for (let i = sr * 3; i < total; i++) {
        const t = (i - sr * 3) / sr;
        samples[i] = 0.8 * (1 - t);
      }

      const fade = svc['_detectFadeStart'](samples, sr);
      // Le fade commence dans la 4e seconde — le point détecté doit être avant la fin
      expect(fade).toBeLessThan(total);
      expect(fade).toBeGreaterThan(sr * 2);
    });
  });

  // ── _crossfade ────────────────────────────────────────────────────────────────

  describe('_crossfade()', () => {
    it('la longueur de sortie est a.length + b.length - xfadeSamples', () => {
      const a  = sineWave(1_000);
      const b  = sineWave(800, 0.3);
      const xf = 100;
      const out = svc['_crossfade'](a, b, xf);
      expect(out.length).toBe(1_000 + 800 - 100);
    });

    it('le début de la sortie coïncide avec a (hors zone crossfade)', () => {
      const a  = new Float32Array(500).fill(0.7);
      const b  = new Float32Array(500).fill(0.2);
      const out = svc['_crossfade'](a, b, 50);
      // Les premiers samples (loin du crossfade) doivent être ≈ 0.7
      expect(out[0]).toBeCloseTo(0.7, 3);
    });

    it('le milieu du crossfade est une transition douce (≠ a, ≠ b)', () => {
      const a  = new Float32Array(200).fill(1.0);
      const b  = new Float32Array(200).fill(0.0);
      const xf = 100;
      const out = svc['_crossfade'](a, b, xf);
      // Au milieu du fade-out (sample a.length - xf/2 = 150) :
      // gain ≈ 0.5 → valeur ≈ 0.5
      const midSample = out[150];
      expect(midSample).toBeGreaterThan(0);
      expect(midSample).toBeLessThan(1);
    });

    it('xfade limité à min(a,b).length pour éviter les accès hors-borne', () => {
      const a  = sineWave(100);
      const b  = sineWave(50, 0.3);
      // xfadeSamples > b.length → doit fonctionner sans erreur
      expect(() => svc['_crossfade'](a, b, 80)).not.toThrow();
    });
  });

  // ── _assignNames ─────────────────────────────────────────────────────────────

  describe('_assignNames()', () => {
    function buildSection(override: Partial<BeatSection> = {}): BeatSection {
      return {
        index:            0,
        name:             '',
        startSample:      0,
        lengthSamples:    44_100,
        startTime:        0,
        duration:         1,
        measures:         8,
        rms:              0.4,
        transientDensity: 3,
        hasDrums:         true,
        energy:           { low: 0.1, mid: 0.3, high: 0.05 },
        waveform:         [],
        ...override,
      };
    }

    it('première section = Intro', () => {
      const secs = [
        buildSection({ index: 0, rms: 0.5 }),
        buildSection({ index: 1, rms: 0.4 }),
        buildSection({ index: 2, rms: 0.3 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[0].name).toBe('Intro');
    });

    it('dernière section = Outro', () => {
      const secs = [
        buildSection({ index: 0, rms: 0.5 }),
        buildSection({ index: 1, rms: 0.4 }),
        buildSection({ index: 2, rms: 0.3 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[2].name).toBe('Outro');
    });

    it('section avec rms max + densité max = Refrain', () => {
      const secs = [
        buildSection({ index: 0, rms: 0.3, transientDensity: 2 }),           // Intro
        buildSection({ index: 1, rms: 1.0, transientDensity: 10, hasDrums: true }),  // Refrain
        buildSection({ index: 2, rms: 0.2, transientDensity: 1 }),           // Outro
      ];
      svc['_assignNames'](secs);
      expect(secs[1].name).toBe('Refrain');
    });

    it('double Refrain → Refrain 1, Refrain 2', () => {
      const secs = [
        buildSection({ index: 0, rms: 0.3, transientDensity: 2 }),
        buildSection({ index: 1, rms: 1.0, transientDensity: 10 }),
        buildSection({ index: 2, rms: 1.0, transientDensity: 10 }),
        buildSection({ index: 3, rms: 0.2, transientDensity: 1 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[1].name).toBe('Refrain 1');
      expect(secs[2].name).toBe('Refrain 2');
    });

    it('section sans drums + faible volume = Pont', () => {
      const secs = [
        buildSection({ index: 0, rms: 0.5, transientDensity: 4 }),
        buildSection({ index: 1, rms: 0.05, transientDensity: 0.5, hasDrums: false }),
        buildSection({ index: 2, rms: 0.3, transientDensity: 3 }),
      ];
      svc['_assignNames'](secs);
      expect(secs[1].name).toBe('Pont');
    });

    it('ne lève pas d\'erreur sur une liste vide', () => {
      expect(() => svc['_assignNames']([])).not.toThrow();
    });
  });

  // ── _lowpass / _highpass ─────────────────────────────────────────────────────

  describe('_lowpass()', () => {
    it('atténue les hautes fréquences (énergie réduite)', () => {
      // Signal haute fréquence (quart de Nyquist à 44100 → ~11 kHz)
      const sr     = 44_100;
      const hf     = new Float32Array(4_096);
      for (let i = 0; i < hf.length; i++) hf[i] = 0.8 * Math.sin(2 * Math.PI * i / 4);
      const raw    = svc['_rmsOf'](hf);
      const filtered = svc['_lowpass'](hf, sr, 200);
      expect(svc['_rmsOf'](filtered)).toBeLessThan(raw * 0.5);
    });

    it('retourne un buffer de même longueur', () => {
      const input = sineWave(1_000);
      expect(svc['_lowpass'](input, 44_100, 300).length).toBe(1_000);
    });
  });

  describe('_highpass()', () => {
    it('atténue les basses fréquences (énergie réduite sur signal LF)', () => {
      const sr  = 44_100;
      const lf  = new Float32Array(4_096);
      // Très basse fréquence (1 Hz → 44100 samples/cycle)
      for (let i = 0; i < lf.length; i++) lf[i] = 0.8 * Math.sin(2 * Math.PI * i / 44_100);
      const raw      = svc['_rmsOf'](lf);
      const filtered = svc['_highpass'](lf, sr, 3_000);
      expect(svc['_rmsOf'](filtered)).toBeLessThan(raw * 0.5);
    });

    it('retourne un buffer de même longueur', () => {
      const input = sineWave(1_000);
      expect(svc['_highpass'](input, 44_100, 3_000).length).toBe(1_000);
    });
  });

  // ── createExtendedBeat ────────────────────────────────────────────────────────

  describe('createExtendedBeat()', () => {
    const SR             = 44_100;
    const SAMPLES_PER_SEC = SR;

    // 4 sections de 1 s chacune
    const NUM_SECTIONS    = 4;
    const SAMPLES_PER_SEC_SECTION = SAMPLES_PER_SEC;

    it('retourne un Blob de type audio/wav', () => {
      const samples  = sineWave(NUM_SECTIONS * SAMPLES_PER_SEC_SECTION);
      const analysis = mockAnalysis(SR, SAMPLES_PER_SEC_SECTION, NUM_SECTIONS);
      const blob     = svc.createExtendedBeat(samples, SR, analysis, 1, 'end');
      expect(blob.type).toBe('audio/wav');
      expect(blob.size).toBeGreaterThan(44);  // au moins l'en-tête WAV
    });

    it('mode=end : la sortie est plus longue que l\'audio original (1 section ajoutée)', async () => {
      const origLen  = NUM_SECTIONS * SAMPLES_PER_SEC_SECTION;
      const samples  = sineWave(origLen);
      const analysis = mockAnalysis(SR, SAMPLES_PER_SEC_SECTION, NUM_SECTIONS);
      const blob     = svc.createExtendedBeat(samples, SR, analysis, 1, 'end');

      // WAV header = 44 bytes, data = samples × 2 bytes
      // La sortie doit avoir plus de samples que l'original (crossfade réduit légèrement)
      const xfade     = Math.round(analysis.samplesPerMeasure * 0.5);
      const expectedSamples = origLen + SAMPLES_PER_SEC_SECTION - xfade;
      const expectedBytes   = 44 + expectedSamples * 2;
      expect(blob.size).toBe(expectedBytes);
    });

    it('mode=after section 1 : la sortie contient une section supplémentaire', async () => {
      const origLen  = NUM_SECTIONS * SAMPLES_PER_SEC_SECTION;
      const samples  = sineWave(origLen);
      const analysis = mockAnalysis(SR, SAMPLES_PER_SEC_SECTION, NUM_SECTIONS);

      const blobEnd   = svc.createExtendedBeat(samples, SR, analysis, 1, 'end');
      const blobAfter = svc.createExtendedBeat(samples, SR, analysis, 1, 'after');
      // Les deux modes produisent des blobs de tailles comparables (une section dupliquée)
      expect(blobAfter.size).toBeGreaterThan(44);
      // mode='after' crée deux jointures crossfade vs une seule pour 'end'
      expect(blobAfter.size).toBeLessThan(blobEnd.size + SAMPLES_PER_SEC_SECTION * 2 * 2);
    });

    it('commence avec les 4 octets "RIFF" attendus d\'un WAV valide', async () => {
      const samples  = sineWave(NUM_SECTIONS * SAMPLES_PER_SEC_SECTION);
      const analysis = mockAnalysis(SR, SAMPLES_PER_SEC_SECTION, NUM_SECTIONS);
      const blob     = svc.createExtendedBeat(samples, SR, analysis, 0, 'end');
      const ab       = await blob.arrayBuffer();
      const view     = new DataView(ab);
      const riff = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
      expect(riff).toBe('RIFF');
    });
  });
});
