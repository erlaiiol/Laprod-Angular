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
  beatPhase:           number;        // sample du 1er temps réel (décalage du fichier par rapport au grid)
  samplesPerBeat:      number;        // période raffinée (autocorr. kick + interp. parabolique)
  samplesPerMeasure:   number;
  samplesPerSection:   number;        // 8 × samplesPerMeasure
  maxDurationSamples:  number;        // plafond 3:00, multiple de samplesPerSection
  maxDurationSec:      number;        // secondes correspondantes
}

/** Mode d'insertion de la section dupliquée. */
export type InsertionMode = 'after' | 'end';

/**
 * Résultat de createExtendedBeat().
 * `addedStartSample` et `addedLengthSamples` sont exprimés dans l'espace
 * du buffer résultat (pas de l'original) — utilisés pour la colorisation
 * bi-couleur de la waveform dans le studio.
 */
export interface ExtendedBeatResult {
  blob:               Blob;
  totalSamples:       number;
  sampleRate:         number;
  addedStartSample:   number;
  addedLengthSamples: number;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MEASURES_PER_SECTION  = 8;
const WAVEFORM_POINTS       = 60;
const MAX_BEAT_DURATION_S   = 180; // 3 minutes — plafond pour éviter des fichiers trop lourds

// Micro-fade anti-clic à la jonction (en millisecondes).
// Un beat bien calé est une boucle parfaite : couper sur un temps ne génère
// qu'une discontinuité d'amplitude, pas une discontinuité musicale.
// 3 ms suffisent pour éliminer le clic sans créer de doublage de mélodie.
const SPLICE_FADE_MS = 3;

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

    // ── Grille rythmique raffinée depuis les frappes de grosse caisse ────────
    // Le BPM fourni peut être inexact et le fichier peut avoir un décalage
    // (silence, intro) avant le 1er temps. On corrige les deux.
    const { samplesPerBeat, beatPhase } =
      this._refineBeatGrid(samples, sampleRate, bpm);

    const samplesPerMeasure = Math.round(samplesPerBeat * 4);
    const samplesPerSection = samplesPerMeasure * MEASURES_PER_SECTION;

    // ── Plafond 3:00 calculé depuis la phase réelle ────────────────────────
    const sectionDurationS = samplesPerSection / sampleRate;
    const maxSectionsInCap = Math.max(0, Math.floor(
      (MAX_BEAT_DURATION_S * sampleRate - beatPhase) / samplesPerSection,
    ));
    const maxDurationSamples = beatPhase + maxSectionsInCap * samplesPerSection;
    const maxDurationSec     = maxSectionsInCap * sectionDurationS;

    // ── Détection du fade anti-piratage ───────────────────────────────────
    const fadeStartSample = this._detectFadeStart(samples, sampleRate);

    // Nombre de sections complètes depuis beatPhase jusqu'au fade, plafonné
    const sectionsBeforeFade = Math.max(0, Math.floor(
      (fadeStartSample - beatPhase) / samplesPerSection,
    ));
    const numSections   = Math.min(sectionsBeforeFade, maxSectionsInCap);
    const usableSamples = beatPhase + numSections * samplesPerSection;

    // ── Analyse de chaque section alignée sur le grid réel ────────────────
    const sections: BeatSection[] = [];
    for (let i = 0; i < numSections; i++) {
      const start  = beatPhase + i * samplesPerSection;
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
        beatPhase,
        samplesPerBeat,
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
   * Un micro-fade anti-clic de SPLICE_FADE_MS ms est appliqué à chaque jonction.
   * Le beat étant une boucle, un point de coupe sur un bon temps est musicalement
   * continu — seule la discontinuité d'amplitude nécessite ce fade imperceptible.
   */
  createExtendedBeat(
    rawSamples:   Float32Array,
    sampleRate:   number,
    analysis:     BeatAnalysis,
    sectionIndex: number,
    mode:         InsertionMode,
  ): ExtendedBeatResult {
    const section      = analysis.sections[sectionIndex];
    // Micro-fade anti-clic uniquement (≈ 132 samples @ 44 100 Hz = imperceptible)
    const xfade        = Math.round(SPLICE_FADE_MS * 0.001 * sampleRate);
    const sectionSlice = rawSamples.slice(
      section.startSample,
      section.startSample + section.lengthSamples,
    );
    // usable = audio propre, fin de fade-out exclue, aligné sur 8 mesures
    const usable = rawSamples.slice(0, analysis.usableSamples);

    let extended: Float32Array;
    let addedStart: number;
    const addedLen = sectionSlice.length;  // longueur brute avant éventuel trim

    if (mode === 'after') {
      // [avant (incl. section originale)] × xfade ∩ [section dupliquée] × xfade ∩ [après]
      const before = usable.slice(0, section.startSample + section.lengthSamples);
      const after  = usable.slice(section.startSample + section.lengthSamples);
      const mid    = this._crossfade(before, sectionSlice, xfade);
      extended     = this._crossfade(mid, after, xfade);
      // La section dupliquée commence là où `before` commence à s'effacer dans le xfade
      addedStart = before.length - xfade;
    } else {
      // [usable jusqu'au seuil fade original] × xfade ∩ [section dupliquée en fin]
      // Note : usable ne contient PAS le fade-out anti-piratage — il s'arrête au
      // dernier multiple de 8 mesures avant fadeStartSample.
      extended   = this._crossfade(usable, sectionSlice, xfade);
      addedStart = usable.length - xfade;
    }

    // Plafonner à 3:00 — trim + fade-out d'une mesure pour éviter une coupure nette
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

    return {
      blob:               this._encodeWav(extended, sampleRate),
      totalSamples:       extended.length,
      sampleRate,
      addedStartSample:   Math.min(addedStart, extended.length),
      addedLengthSamples: Math.min(addedLen, Math.max(0, extended.length - addedStart)),
    };
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

  // ── Raffinement de la grille rythmique ──────────────────────────────────────

  /**
   * Détecte le BPM précis et la phase du 1er temps à partir des onsets de
   * basse fréquence (kick / grosse caisse).
   *
   * Pipeline :
   *   1. Filtre passe-bas 200 Hz → bande "kick"
   *   2. ODF par fenêtre de 5 ms (flux spectral positif = augmentation d'énergie)
   *   3. Autocorrélation de l'ODF → pic dominant → BPM raffiné (interpolation parabolique)
   *   4. Phase grid scoring → offset p tel que le grid p, p+lag, p+2lag… maximise l'ODF
   *   5. Affinement au sample près du premier temps dans la fenêtre ±HOP/2
   *   6. Fallback : si écart > 5 % du nominal, BPM nominal conservé mais phase détectée
   */
  private _refineBeatGrid(
    samples:    Float32Array,
    sampleRate: number,
    nominalBpm: number,
  ): { samplesPerBeat: number; beatPhase: number } {
    const HOP   = Math.round(0.005 * sampleRate);   // 5 ms par frame
    const bass  = this._lowpass(samples, sampleRate, 200);
    const nHops = Math.floor(bass.length / HOP);

    // ── ODF : énergie par frame → flux positif ───────────────────────────────
    const odf = new Float32Array(nHops);
    let prevE = 0;
    for (let f = 0; f < nHops; f++) {
      let e = 0;
      const base = f * HOP;
      for (let i = base; i < base + HOP && i < bass.length; i++) e += bass[i] * bass[i];
      e /= HOP;
      odf[f] = Math.max(0, e - prevE);
      prevE  = e;
    }

    // ── Autocorrélation sur la plage ±12 % du lag nominal ───────────────────
    const nomLag   = (60 / nominalBpm) * sampleRate / HOP;  // lag en frames
    const lagMin   = Math.max(1, Math.round(nomLag * 0.88));
    const lagMax   = Math.round(nomLag * 1.12);
    let   bestCorr = -Infinity;
    let   bestLag  = Math.round(nomLag);

    for (let lag = lagMin; lag <= lagMax; lag++) {
      let corr = 0;
      const n  = nHops - lag;
      if (n <= 0) continue;
      for (let f = 0; f < n; f++) corr += odf[f] * odf[f + lag];
      if (corr > bestCorr) { bestCorr = corr; bestLag = lag; }
    }

    // ── Interpolation parabolique pour affiner le lag au sous-frame ─────────
    const y0 = bestLag > lagMin     ? this._corrAt(odf, bestLag - 1) : bestCorr;
    const y1 = bestCorr;
    const y2 = bestLag < lagMax     ? this._corrAt(odf, bestLag + 1) : bestCorr;
    const denom = y0 - 2 * y1 + y2;
    const fracLag = denom !== 0
      ? bestLag - 0.5 * (y2 - y0) / denom
      : bestLag;
    const refinedSPB = Math.round(fracLag * HOP);

    // ── Phase grid scoring : trouver le meilleur offset de départ ───────────
    let bestScore  = -Infinity;
    let bestPhaseF = 0;
    for (let p = 0; p < bestLag; p++) {
      let score = 0;
      for (let f = p; f < nHops; f += bestLag) score += odf[f];
      if (score > bestScore) { bestScore = score; bestPhaseF = p; }
    }

    // ── Affinement au sample du premier temps ────────────────────────────────
    const centerSample = bestPhaseF * HOP;
    const halfWin      = Math.round(HOP / 2);
    const searchStart  = Math.max(0, centerSample - halfWin);
    const searchEnd    = Math.min(bass.length - 1, centerSample + halfWin);
    let   peakVal      = -Infinity;
    let   peakSample   = centerSample;
    for (let i = searchStart; i <= searchEnd; i++) {
      const v = bass[i] * bass[i];
      if (v > peakVal) { peakVal = v; peakSample = i; }
    }

    // Contraindre beatPhase à max 2 mesures (8 temps) depuis le début
    const maxPhase    = Math.round(refinedSPB * 8);
    const beatPhase   = Math.min(peakSample, maxPhase);

    // ── Fallback si le BPM raffiné dévie > 5 % du nominal ──────────────────
    const nominalSPB  = Math.round((60 / nominalBpm) * sampleRate);
    const deviation   = Math.abs(refinedSPB - nominalSPB) / nominalSPB;
    const samplesPerBeat = deviation <= 0.05 ? refinedSPB : nominalSPB;

    return { samplesPerBeat, beatPhase };
  }

  /** Calcule la corrélation de l'ODF à un lag donné (helper parabolique). */
  private _corrAt(odf: Float32Array, lag: number): number {
    let corr = 0;
    const n  = odf.length - lag;
    if (n <= 0) return 0;
    for (let f = 0; f < n; f++) corr += odf[f] * odf[f + lag];
    return corr;
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
