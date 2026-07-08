import { computeWaveform, spliceWaveform, resampleWaveform } from './waveform.utils';

describe('waveform.utils', () => {

  // ── computeWaveform ──────────────────────────────────────────────────────────

  describe('computeWaveform()', () => {
    it('retourne un tableau de longueur n', () => {
      expect(computeWaveform([0.1, 0.5, 0.8, 0.3], 4).length).toBe(4);
    });

    it('retourne Array(n).fill(0.1) pour un tableau vide', () => {
      expect(computeWaveform([], 5)).toEqual([0.1, 0.1, 0.1, 0.1, 0.1]);
    });

    it('normalise au pic maximal (max = 1)', () => {
      const wf = computeWaveform([0.2, 0.4, 0.8, 0.6], 4);
      expect(Math.max(...wf)).toBeCloseTo(1, 5);
    });

    it('toutes les valeurs sont dans [0, 1]', () => {
      const wf = computeWaveform([0.1, 0.9, 0.5, 0.3, 0.7], 5);
      for (const v of wf) {
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(1);
      }
    });

    it('fonctionne quand rms est plus court que n (upsample)', () => {
      const wf = computeWaveform([1, 0.5], 10);
      expect(wf.length).toBe(10);
    });

    it('fonctionne quand rms est plus long que n (downsample)', () => {
      const long = Array.from({ length: 500 }, (_, i) => (i % 10) / 10);
      expect(computeWaveform(long, 60).length).toBe(60);
    });
  });

  // ── spliceWaveform ───────────────────────────────────────────────────────────

  describe('spliceWaveform()', () => {
    it('retourne newWf si existing est vide', () => {
      const newWf  = [0.1, 0.5, 0.9];
      expect(spliceWaveform([], 0, 2, newWf, 3)).toEqual(newWf);
    });

    it('longueur de sortie = points', () => {
      const existing = Array<number>(120).fill(0.3);
      const newWf    = Array<number>(60).fill(0.7);
      expect(spliceWaveform(existing, 1, 2, newWf, 120).length).toBe(120);
    });

    it('fromSec = 0 : utilise uniquement newWf (rien à conserver)', () => {
      const newWf = Array<number>(4).fill(0.9);
      const out   = spliceWaveform([0.1, 0.2, 0.3, 0.4], 0, 4, newWf, 4);
      expect(out.length).toBe(4);
    });

    it('fromSec = totalSec : conserve tout l\'existant', () => {
      const existing = [0.1, 0.2, 0.3, 0.4];
      const out      = spliceWaveform(existing, 4, 4, [0.9, 0.8, 0.7, 0.6], 4);
      expect(out.slice(0, 4)).toEqual(existing);
    });

    it('fusionne proportionnellement au ratio fromSec/totalSec', () => {
      // fromSec=1, totalSec=2 → ratio=0.5 → keepN=2, newN=2 sur points=4
      const existing = [0.1, 0.2, 0.3, 0.4];
      const newWf    = [0.9, 0.8];
      const out      = spliceWaveform(existing, 1, 2, newWf, 4);
      expect(out.slice(0, 2)).toEqual([0.1, 0.2]);
      expect(out.length).toBe(4);
    });
  });

  // ── resampleWaveform ─────────────────────────────────────────────────────────

  describe('resampleWaveform()', () => {
    it('retourne un tableau vide si targetLen <= 0', () => {
      expect(resampleWaveform([1, 2, 3], 0)).toEqual([]);
      expect(resampleWaveform([1, 2, 3], -1)).toEqual([]);
    });

    it('retourne une copie si targetLen === wf.length', () => {
      const wf  = [0.1, 0.5, 0.9];
      const out = resampleWaveform(wf, 3);
      expect(out).toEqual(wf);
      expect(out).not.toBe(wf); // copie, pas référence
    });

    it('upsample : longueur correcte', () => {
      expect(resampleWaveform([0, 1], 8).length).toBe(8);
    });

    it('downsample : longueur correcte', () => {
      const long = Array.from({ length: 120 }, (_, i) => i / 120);
      expect(resampleWaveform(long, 60).length).toBe(60);
    });

    it('valeurs dans [0, 1] pour un signal dans [0, 1]', () => {
      const wf  = Array.from({ length: 10 }, (_, i) => i / 9);
      const out = resampleWaveform(wf, 25);
      for (const v of out) {
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(1);
      }
    });
  });
});
