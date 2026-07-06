import { Injectable } from '@angular/core';

// ── Types publics ─────────────────────────────────────────────────────────────

export interface BeatSection {
  index:            number;
  name:             string;        // 'Intro', 'Couplet', 'Pré-refrain', 'Refrain', 'Pont', 'Outro'
  startSample:      number;
  lengthSamples:    number;
  startTime:        number;        // secondes
  duration:         number;        // secondes
  measures:         number;        // toujours 8
  rms:              number;        // énergie normalisée 0-1
  transientDensity: number;        // transients/seconde (indicateur drums)
  hasDrums:         boolean;
  energy:           { low: number; mid: number; high: number };
  waveform:         number[];      // 60 points amplitude [0-1] pour canvas
}

export interface BeatAnalysis {
  sections:            BeatSection[];
  sampleRate:          number;
  totalSamples:        number;
  usableSamples:       number;        // jusqu'au fade, arrondi à 8-mesures, ≤ maxDurationSamples
  fadeStartSample:     number;
  bpm:                 number;
  samplesPerMeasure:   number;
  samplesPerSection:   number;        // 8 × samplesPerMeasure
  maxDurationSamples:  number;        // plafond 3:00, multiple de samplesPerSection
  maxDurationSec:      number;        // secondes correspondantes
}

/** Mode d'insertion de la section dupliquée. */
export type InsertionMode = 'after' | 'end';

// ── Constants ─────────────────────────────────────────────────────────────────

const MEASURES_PER_SECTION  = 8;
const WAVEFORM_POINTS       = 60;
const MAX_BEAT_DURATION_S   = 180; // 3 minutes — plafond pour éviter des fichiers trop lourds

// Fondu enchaîné en fraction d'une mesure (0.5 = demi-mesure de crossfade)
const CROSSFADE_MEASURES = 0.5;

// Seuil de transient : l'énergie fenêtre doit être ≥ ce facteur × fenêtre précédente
const TRANSIENT_FACTOR = 2.5;      // ≈ +8 dB

// Fade-out détection : cherche le dernier point avant que le RMS tombe en dessous
// de ce ratio du pic maximal
const FADE_THRESHOLD = 0.35;

// Taille de la fenêtre RMS pour la détection du fade (secondes)
const FADE_WINDOW_S = 0.5;

// Taille des fenêtres pour la détection de transients (millisecondes)
const TRANSIENT_WIN_MS = 10;

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class BeatExtenderService {

  // ── Analyse principale ────────────────────────────────────────────────────────

  /**
   * Télécharge et analyse le beat.
   * Retourne l'analyse + les samples bruts pour usage ultérieur (création du beat étendu).
   */
  async analyzeBeat(
    beatUrl:     string,
    bpm:         number,
    accessToken: string,
  ): Promise<{ analysis: BeatAnalysis; rawSamples: Float32Array; sampleRate: number }> {
    const { samples, sampleRate } = await this._fetchAndDecode(beatUrl, accessToken);

    const samplesPerBeat    = (60 / bpm) * sampleRate;
    const samplesPerMeasure = Math.round(samplesPerBeat * 4);
    const samplesPerSection = samplesPerMeasure * MEASURES_PER_SECTION;

    // Plafond 3:00 — nombre max de sections de 8 mesures tenant dans MAX_BEAT_DURATION_S
    const sectionDurationS   = samplesPerSection / sampleRate;
    const maxSectionCount    = Math.floor(MAX_BEAT_DURATION_S / sectionDurationS);
    const maxDurationSamples = maxSectionCount * samplesPerSection;
    const maxDurationSec     = maxSectionCount * sectionDurationS;

    // Détecter le fade anti-piratage
    const fadeStartSample = this._detectFadeStart(samples, sampleRate);

    // Revenir au dernier multiple de 8 mesures avant le fade, plafonné à 3:00
    const usableSamples = Math.min(
      Math.floor(fadeStartSample / samplesPerSection) * samplesPerSection,
      maxDurationSamples,
    );

    // Analyser chaque section de 8 mesures
    const numSections = Math.floor(usableSamples / samplesPerSection);
    const sections: BeatSection[] = [];

    for (let i = 0; i < numSections; i++) {
      const start  = Math.round(i * samplesPerSection);
      const length = Math.min(samplesPerSection, samples.length - start);
      const slice  = samples.slice(start, start + length);

      sections.push(
        this._analyzeSection(slice, sampleRate, i, start, length, samplesPerMeasure, bpm),
      );
    }

    this._assignNames(sections);

    return {
      analysis: {
        sections,
        sampleRate,
        totalSamples:      samples.length,
        usableSamples,
        fadeStartSample,
        bpm,
        samplesPerMeasure,
        samplesPerSection,
        maxDurationSamples,
        maxDurationSec,
      },
      rawSamples: samples,
      sampleRate,
    };
  }

  // ── Création du beat étendu ────────────────────────────────────────────────────

  /**
   * Duplique la section choisie et l'insère dans l'audio.
   *   - mode='after' : immédiatement après cette section
   *   - mode='end'   : à la fin (avant que le fade original ait commencé)
   *
   * Un fondu enchaîné de `CROSSFADE_MEASURES` mesures est appliqué à chaque jointure.
   */
  createExtendedBeat(
    rawSamples:    Float32Array,
    sampleRate:    number,
    analysis:      BeatAnalysis,
    sectionIndex:  number,
    mode:          InsertionMode,
  ): Blob {
    const section     = analysis.sections[sectionIndex];
    const xfadeSamples = Math.round(analysis.samplesPerMeasure * CROSSFADE_MEASURES);

    const sectionSlice = rawSamples.slice(
      section.startSample,
      section.startSample + section.lengthSamples,
    );
    const usable = rawSamples.slice(0, analysis.usableSamples);

    let extended: Float32Array;

    if (mode === 'after') {
      // [partie avant la section] + [section] ×2 + [partie après]
      const before = usable.slice(0, section.startSample + section.lengthSamples);
      const after  = usable.slice(section.startSample + section.lengthSamples);
      const mid    = this._crossfade(before, sectionSlice, xfadeSamples);
      extended     = this._crossfade(mid, after, xfadeSamples);
    } else {
      // [audio complet jusqu'au fade] + [section]
      extended = this._crossfade(usable, sectionSlice, xfadeSamples);
    }

    // Plafonner à 3:00 — trim + fade-out 1 mesure pour éviter une coupure nette
    const maxSamples = analysis.maxDurationSamples;
    if (extended.length > maxSamples) {
      const trimmed     = new Float32Array(maxSamples);
      trimmed.set(extended.subarray(0, maxSamples));
      const fadeSamples = Math.min(analysis.samplesPerMeasure, maxSamples);
      const fadeStart   = maxSamples - fadeSamples;
      for (let i = 0; i < fadeSamples; i++) {
        trimmed[fadeStart + i] *= (fadeSamples - 1 - i) / fadeSamples;
      }
      extended = trimmed;
    }

    return this._encodeWav(extended, sampleRate);
  }

  // ── Détection du fade anti-piratage ──────────────────────────────────────────

  /**
   * Détecte où le fade-out Python commence.
   * Stratégie : fenêtres RMS de 0.5 s — on cherche le dernier moment où le niveau
   * est encore ≥ FADE_THRESHOLD × pic maximal.
   */
  private _detectFadeStart(samples: Float32Array, sampleRate: number): number {
    const winSize   = Math.round(FADE_WINDOW_S * sampleRate);
    const numWins   = Math.floor(samples.length / winSize);
    const rms       = new Float32Array(numWins);

    for (let w = 0; w < numWins; w++) {
      let sq = 0;
      const base = w * winSize;
      for (let i = base; i < base + winSize; i++) sq += samples[i] * samples[i];
      rms[w] = Math.sqrt(sq / winSize);
    }

    const peak = Math.max(...rms);
    const threshold = peak * FADE_THRESHOLD;

    // Remonter depuis la fin pour trouver le dernier window au-dessus du seuil
    for (let w = numWins - 1; w >= 0; w--) {
      if (rms[w] >= threshold) {
        // Le fade commence dans la fenêtre suivante
        return Math.min((w + 1) * winSize, samples.length);
      }
    }
    return samples.length;
  }

  // ── Analyse d'une section ─────────────────────────────────────────────────────

  private _analyzeSection(
    slice:            Float32Array,
    sampleRate:       number,
    index:            number,
    startSample:      number,
    lengthSamples:    number,
    samplesPerMeasure: number,
    bpm:              number,
  ): BeatSection {
    const durationS = lengthSamples / sampleRate;

    // RMS global
    let sq = 0;
    for (const s of slice) sq += s * s;
    const rms = Math.sqrt(sq / slice.length);

    // Séparation bandes via filtres IIR passe-bas / passe-haut
    const lowBand  = this._lowpass(slice, sampleRate, 200);
    const highBand = this._highpass(slice, sampleRate, 3_000);

    const energyLow  = this._rmsOf(lowBand);
    const energyHigh = this._rmsOf(highBand);
    const energyMid  = Math.max(0, rms - energyLow * 0.5 - energyHigh * 0.5);

    // Densité de transients (indicateur drums)
    const transientDensity = this._countTransients(slice, sampleRate) / durationS;
    const hasDrums = transientDensity > 2.0;   // > 2 coups/s = section rythmée

    // Mini waveform (60 barres)
    const waveform = this._miniWaveform(slice, WAVEFORM_POINTS);

    return {
      index,
      name:      '',   // rempli par _assignNames
      startSample,
      lengthSamples,
      startTime:  startSample / sampleRate,
      duration:   durationS,
      measures:   MEASURES_PER_SECTION,
      rms,
      transientDensity,
      hasDrums,
      energy:    { low: energyLow, mid: energyMid, high: energyHigh },
      waveform,
    };
  }

  // ── Attribution des noms de section ───────────────────────────────────────────

  private _assignNames(sections: BeatSection[]): void {
    if (sections.length === 0) return;

    const maxRms     = Math.max(...sections.map(s => s.rms), 0.001);
    const avgRms     = sections.reduce((a, s) => a + s.rms, 0) / sections.length;
    const maxDensity = Math.max(...sections.map(s => s.transientDensity), 0.001);

    sections.forEach((s, i) => {
      if (i === 0) {
        s.name = 'Intro';
      } else if (i === sections.length - 1) {
        s.name = 'Outro';
      } else if (s.rms >= maxRms * 0.88 && s.transientDensity >= maxDensity * 0.75) {
        // Niveau maximal + beaucoup de transients → refrain
        s.name = 'Refrain';
      } else if (s.hasDrums && s.rms >= avgRms * 1.05) {
        // Rythmé, niveau au-dessus de la moyenne → couplet
        s.name = 'Couplet';
      } else if (s.hasDrums && s.rms >= avgRms * 0.85) {
        // Drums présentes mais niveau modéré → pré-refrain ou pont
        s.name = 'Pré-refrain';
      } else {
        // Peu de drums ou volume faible → pont / break
        s.name = 'Pont';
      }
    });

    // Numéroter les doublons (ex: "Couplet 1", "Couplet 2")
    const counts: Record<string, number> = {};
    for (const s of sections) counts[s.name] = (counts[s.name] ?? 0) + 1;

    const seen: Record<string, number> = {};
    for (const s of sections) {
      const skip = s.name === 'Intro' || s.name === 'Outro';
      if (!skip && counts[s.name] > 1) {
        seen[s.name] = (seen[s.name] ?? 0) + 1;
        s.name = `${s.name} ${seen[s.name]}`;
      }
    }
  }

  // ── Fondu enchaîné (crossfade linéaire) ─────────────────────────────────────

  /**
   * Stitch `a` et `b` avec un crossfade de `xfadeSamples` échantillons.
   * La sortie a une longueur de a.length + b.length - xfadeSamples.
   */
  private _crossfade(
    a: Float32Array,
    b: Float32Array,
    xfadeSamples: number,
  ): Float32Array {
    const xf     = Math.min(xfadeSamples, a.length, b.length);
    const outLen = a.length + b.length - xf;
    const out    = new Float32Array(outLen);

    // Copie de a avec fade-out sur les xf derniers samples
    for (let i = 0; i < a.length; i++) {
      const gain = i >= a.length - xf ? (a.length - i) / xf : 1.0;
      out[i] += a[i] * gain;
    }

    // Copie de b avec fade-in sur les xf premiers samples
    const offset = a.length - xf;
    for (let i = 0; i < b.length; i++) {
      const gain = i < xf ? i / xf : 1.0;
      out[offset + i] += b[i] * gain;
    }

    return out;
  }

  // ── DSP helpers ───────────────────────────────────────────────────────────────

  /** Filtre passe-bas IIR du 1er ordre via décimation exponentielle. */
  private _lowpass(samples: Float32Array, sr: number, cutHz: number): Float32Array {
    const alpha = Math.min(1, (2 * Math.PI * cutHz) / sr);
    const out   = new Float32Array(samples.length);
    let y = 0;
    for (let i = 0; i < samples.length; i++) {
      y = alpha * samples[i] + (1 - alpha) * y;
      out[i] = y;
    }
    return out;
  }

  /** Filtre passe-haut IIR du 1er ordre. */
  private _highpass(samples: Float32Array, sr: number, cutHz: number): Float32Array {
    const alpha = Math.min(1, (2 * Math.PI * cutHz) / sr);
    const out   = new Float32Array(samples.length);
    let xPrev = 0, yPrev = 0;
    const k = 1 - alpha;
    for (let i = 0; i < samples.length; i++) {
      out[i] = k * (yPrev + samples[i] - xPrev);
      xPrev  = samples[i];
      yPrev  = out[i];
    }
    return out;
  }

  /** RMS d'un buffer. */
  private _rmsOf(samples: Float32Array): number {
    let sq = 0;
    for (const s of samples) sq += s * s;
    return Math.sqrt(sq / (samples.length || 1));
  }

  /**
   * Compte les transients (sauts d'énergie) dans un buffer.
   * Un transient = l'énergie d'une fenêtre de 10 ms est ≥ TRANSIENT_FACTOR × la précédente.
   */
  private _countTransients(samples: Float32Array, sampleRate: number): number {
    const winSize  = Math.max(1, Math.round(TRANSIENT_WIN_MS * sampleRate / 1000));
    let count      = 0;
    let prevEnergy: number | null = null;

    for (let i = 0; i + winSize <= samples.length; i += winSize) {
      let e = 0;
      for (let j = i; j < i + winSize; j++) e += samples[j] * samples[j];
      e /= winSize;
      // prevEnergy est null sur la première fenêtre — pas de "précédente" à comparer,
      // donc pas de transient possible (sinon tout signal non silencieux en comptait
      // un dès la première fenêtre, y compris un signal parfaitement constant).
      if (prevEnergy !== null && e > prevEnergy * TRANSIENT_FACTOR && e > 1e-6) count++;
      prevEnergy = e;
    }
    return count;
  }

  /** Waveform réduite à `points` barres, normalisée [0-1]. */
  private _miniWaveform(samples: Float32Array, points: number): number[] {
    const step = samples.length / points;
    const wf: number[] = [];
    let max = 1e-6;

    for (let i = 0; i < points; i++) {
      const start = Math.floor(i * step);
      const end   = Math.floor((i + 1) * step);
      let peak    = 0;
      for (let j = start; j < end && j < samples.length; j++) {
        peak = Math.max(peak, Math.abs(samples[j]));
      }
      wf.push(peak);
      if (peak > max) max = peak;
    }
    return wf.map(v => v / max);
  }

  // ── Fetch + decode ────────────────────────────────────────────────────────────

  private async _fetchAndDecode(
    url:   string,
    token: string,
  ): Promise<{ samples: Float32Array; sampleRate: number }> {
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) throw new Error(`Beat fetch: HTTP ${resp.status}`);

    const ab  = await resp.arrayBuffer();
    const ctx = new OfflineAudioContext(1, 1, 44_100);
    const buf = await ctx.decodeAudioData(ab);

    // Mixdown mono si stéréo
    const sr   = buf.sampleRate;
    const mono = new Float32Array(buf.length);
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const ch = buf.getChannelData(c);
      for (let i = 0; i < ch.length; i++) mono[i] += ch[i] / buf.numberOfChannels;
    }

    return { samples: mono, sampleRate: sr };
  }

  // ── Encodage WAV PCM 16-bit ───────────────────────────────────────────────────

  /**
   * Encode un Float32Array mono en fichier WAV 16-bit little-endian.
   * Le blob résultant peut être passé directement à `MixAndExportOptions.beatBlob`.
   */
  private _encodeWav(samples: Float32Array, sampleRate: number): Blob {
    const numCh       = 1;
    const bitsPerSamp = 16;
    const dataSize    = samples.length * 2;
    const buf         = new ArrayBuffer(44 + dataSize);
    const view        = new DataView(buf);

    const str = (off: number, s: string) => {
      for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i));
    };

    str(0, 'RIFF');
    view.setUint32(4,  36 + dataSize,          true);
    str(8, 'WAVE');
    str(12, 'fmt ');
    view.setUint32(16, 16,                     true);  // PCM
    view.setUint16(20, 1,                      true);  // format PCM
    view.setUint16(22, numCh,                  true);
    view.setUint32(24, sampleRate,             true);
    view.setUint32(28, sampleRate * numCh * 2, true);  // byte rate
    view.setUint16(32, numCh * 2,              true);  // block align
    view.setUint16(34, bitsPerSamp,            true);
    str(36, 'data');
    view.setUint32(40, dataSize,               true);

    let offset = 44;
    for (const s of samples) {
      const clamped = Math.max(-1, Math.min(1, s));
      view.setInt16(offset, clamped < 0 ? clamped * 32768 : clamped * 32767, true);
      offset += 2;
    }

    return new Blob([buf], { type: 'audio/wav' });
  }
}
