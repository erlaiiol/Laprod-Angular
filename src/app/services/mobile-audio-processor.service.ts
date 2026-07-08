/**
 * MobileAudioProcessorService — Pipeline de production vocale entièrement côté client.
 *
 * Chaîne de traitement (inspirée studio professionnel) :
 *   Decode → Mono → Gate → HPF → LA-2A (optique) → Presence EQ → Air shelf @12kHz
 *   → 1176 (FET) → De-esser → Gain → Tanh limiter → Plate reverb → [Autotune]
 *   → Mix beat → Peak guard → MP3
 *
 * Références techniques :
 *   - HPF Butterworth CBS Q values : Zölzer, DAFX 2e éd., §2.2
 *   - De-esser split-band : Reiss & McPherson, Audio Effects, §7.3
 *   - Noise gate one-pole : Välimäki, IEEE Signal Processing Magazine 2016
 *   - Schroeder reverb → plate IR via filtered noise : gskinner.com/blog 2019
 *   - Pitch detection YIN : de Cheveigné & Kawahara, J. Acoust. Soc. Am. 2002
 *   - SoundTouchJS WSOLA : Söderström, TUT, Finland 1993
 *   - LA-2A / 1176 : Katz, Mastering Audio 3e éd., ch. 6
 */

import { Injectable, InjectionToken, inject } from '@angular/core';
// @ts-ignore — pas de typings officiels pour soundtouchjs
import { SoundTouch, SimpleFilter } from 'soundtouchjs';
import { PitchDetector } from 'pitchy';
import { Mp3Encoder } from '@breezystack/lamejs';

/**
 * Constructeur d'OfflineAudioContext, injecté plutôt que référencé en dur.
 * jsdom (environnement de test) n'implémente pas le Web Audio API — ce token
 * permet aux tests de fournir une vraie implémentation (ex. node-web-audio-api)
 * sans toucher au global ni au service. En prod (navigateur/WebView), la factory
 * retourne exactement la classe native : comportement inchangé.
 * Même pattern que PITCH_MONITOR (pitch-monitor-plugin.ts) pour l'abstraction natif/plateforme.
 *
 * La factory par défaut doit rester sûre même quand le global n'existe pas :
 * ce champ est résolu dès la construction du service (injection de champ), et
 * MobileAudioProcessorService est lui-même injecté par d'autres services
 * (ex. MobileMaquetteService) dans des tests qui ne touchent jamais l'audio —
 * référencer le global sans garde ferait échouer CES tests-là aussi, alors
 * qu'ils n'appellent jamais une méthode de décodage/mixage.
 */
export const OFFLINE_AUDIO_CONTEXT = new InjectionToken<typeof OfflineAudioContext>(
  'OfflineAudioContext',
  {
    factory: () =>
      (typeof OfflineAudioContext !== 'undefined' ? OfflineAudioContext : undefined) as typeof OfflineAudioContext,
  },
);

// ── DSP constants ─────────────────────────────────────────────────────────────
// Regroupés ici pour faciliter le tuning sans chercher dans le code.

const SR = 48_000;

// Noise gate — élimine le souffle et le silence entre les phrases
const GATE_THRESHOLD_DB =  -50;  // dBFS, seuil d'ouverture
const GATE_ATTACK_MS    =    5;  // ms — montée rapide (pas de pump à l'ouverture)
const GATE_RELEASE_MS   =  120;  // ms — descente lente (évite les coupures abruptes)

// HPF ordre 4 Butterworth via deux sections 2nd-ordre en cascade (Cascaded Biquad Sections)
// Q_k = 1 / (2·cos(π·(2k−1) / (2n))) pour n=4
// k=1 → Q = 0.5412,  k=2 → Q = 1.3066
const HPF_FREQ = 160;    // Hz — coupe les rumbles et proximité de micro
const HPF_Q1   = 0.5412;
const HPF_Q2   = 1.3066;

// LA-2A — compresseur optique : colle la voix, égalise les dynamiques sans pompage
// Knee très doux = compression progressive, caractère "transparent/gluey"
const LA2A_THRESHOLD = -22;   // dBFS
const LA2A_KNEE      =  14;   // dB — très doux (optique)
const LA2A_RATIO     =   3;   // :1
const LA2A_ATTACK    = 0.030; // s — 30ms, laisse les consonnes passer
const LA2A_RELEASE   = 0.350; // s — programme-dépendant approché

// 1176 — compresseur FET : punch, transitoires, solidification post-EQ
// Knee dur + ratio élevé = caractère "snap", pas de punch perdu
const C1176_THRESHOLD = -18;  // dBFS
const C1176_KNEE      =   2;  // dB — dur (FET)
const C1176_RATIO     =   8;  // :1
const C1176_ATTACK    = 0.001; // s — 1ms (min réaliste Web Audio)
const C1176_RELEASE   = 0.180; // s

// De-esser split-band — sidechain centré sur le cluster de sibilance
// Positionné APRÈS la compression : le compresseur relève les sibilances
// par rapport aux voyelles, le de-esser les rattrape plus précisément ici.
// 5 472 Hz : centre médical du pic de sibilance vocale en microphone cardioïde
const DEESS_FREQ      = 5_472;  // Hz
const DEESS_BW_Q      =   2.7;  // Q du bandpass sibilant
const DEESS_THRESHOLD =   -22;  // dBFS — légèrement relevé post-compression
const DEESS_RATIO     =    10;  // compression agressive sur la bande (de-esser ≈ gate fréq.)
const DEESS_ATTACK    = 0.004;  // s — rapide pour attraper les transients
const DEESS_RELEASE   = 0.050;  // s

// EQ vocal
const PRESENCE_FREQ = 2_500;  // Hz — boost d'intelligibilité (consonnes, attaque)
const PRESENCE_GAIN =   3.5;  // dB
const PRESENCE_Q    =   1.0;
const AIR_FREQ      = 12_000; // Hz — Pultec-style "air" shelf (12kHz = ouverture sans agressivité)
const AIR_GAIN      =   4.0;  // dB — valeur par défaut; clarityDb le remplace si spécifié

// Tanh soft limiter — protège contre les inter-sample peaks après le gain staging
// Fonction : y = tanh(x · drive / ceiling) · ceiling
const LIMITER_CEILING   = 0.891;  // linéaire ≈ -1 dBFS
const LIMITER_DRIVE     = 1.5;    // légère saturation harmonique (2e harmonique prédominante)
const LIMITER_CURVE_RES = 512;    // résolution de la lookup table

// Plate reverb IR — plus courte et plus dense qu'une réverb hall
// Profil : HP 400 Hz (enlève le bas-médium boueux), LP 6 000 Hz (damping air)
const PLATE_DECAY_S = 1.8;    // s — durée de la queue de réverb
const PLATE_HP_HZ   =  400;   // Hz
const PLATE_LP_HZ   = 6_000;  // Hz

// Autotune (correction de hauteur globale + lissage)
const PITCH_FRAME    = 2048;  // samples — fenêtre YIN (~43 ms @ 48kHz)
const PITCH_HOP      =  256;  // samples — pas d'analyse (~5 ms)
const PITCH_CLARITY  =  0.80; // seuil de confiance YIN (0→1, 1=parfait)
const PITCH_HZ_MIN   =   80;  // Hz — limite basse (voix basse masculine)
const PITCH_HZ_MAX   = 1_200; // Hz — limite haute (voix soprano)
const PITCH_SMOOTH_K =    5;  // longueur du filtre médian glissant (frames)
const AUTOTUNE_CLAMP =    3;  // semitones max de correction (≥3s = erreur de détection)

// Encodage
const MP3_KBPS = 192;

// ── Interfaces publiques ──────────────────────────────────────────────────────

export interface MixParameters {
  /** Taux de réverb dry/wet. 0 = totalement sec, 1 = 100% wet. */
  reverbWet: number;
  /** Gain de la voix après EQ. 1.0 = 0 dB, 2.0 = +6 dB, 0.5 = -6 dB. */
  voiceGain: number;
  /** Gain du beat dans le mix. 0.355 ≈ -9 dB (valeur par défaut). */
  beatGain: number;
  useAutotune: boolean;
  trackKey: string;
  /** Décalage en ms pour compenser la latence d'écoute casque / BT. */
  latencyHintMs: number;
  /** Hi-shelf @ 10kHz : clarté vocale. 2–10 dB. Défaut = AIR_GAIN (2.5 dB). */
  clarityDb?: number;
}

export interface ProcessToplineOptions {
  voiceBlob:    Blob;
  beatStreamUrl: string;
  accessToken:  string;
  params:       MixParameters;
  /** Appelé à chaque étape pour mettre à jour l'UI. */
  onProgress?:  (step: string, pct: number) => void;
}

/** Paramètres par piste pour le studio multi-pistes. */
export interface TrackSettings {
  volume:      number;   // 0–2 (1 = 0 dB)
  useAutotune: boolean;
  reverbWet:   number;   // 0–1
  clarityDb:   number;   // 0–10 dB hi-shelf @ 10kHz
}

export interface ProcessVocalTrackOptions {
  blob:          Blob;
  settings:      TrackSettings;
  trackKey:      string;
  latencyHintMs?: number;
  onProgress?:   (step: string, pct: number) => void;
}

export interface MixAndExportOptions {
  vocals:        Array<{ samples: Float32Array; settings: TrackSettings }>;
  beatStreamUrl: string;
  beatGain:      number;
  accessToken:   string;
  latencyHintMs?: number;
  /** Blob WAV du beat étendu — si fourni, il est décodé directement sans fetch. */
  beatBlob?:     Blob;
  onProgress?:   (step: string, pct: number) => void;
}

export interface QuickMixOptions {
  vocals:        Array<{ blob: Blob; volume: number }>;
  beatStreamUrl: string;
  beatGain:      number;
  accessToken:   string;
  /** Si fourni, décodé directement — évite un fetch réseau (beat étendu). */
  beatBlob?:     Blob;
}

/** Valeurs par défaut exposées pour initialiser les sliders de l'UI. */
export const DEFAULT_MIX: Pick<MixParameters, 'reverbWet' | 'voiceGain' | 'beatGain'> = {
  reverbWet: 0.15,
  voiceGain: 1.0,
  beatGain:  0.355,
};

export const DEFAULT_TRACK_SETTINGS: TrackSettings = {
  volume:      1.0,
  useAutotune: false,
  reverbWet:   0.12,  // preset "Réaliste"
  clarityDb:   3.0,   // preset "Medium"
};

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class MobileAudioProcessorService {

  private readonly offlineCtx = inject(OFFLINE_AUDIO_CONTEXT);

  /** Cache de l'IR plate — généré une seule fois par session. */
  private _plateIRCache: Promise<AudioBuffer> | null = null;

  // ── Entrée principale ────────────────────────────────────────────────────────

  async processTopline(opts: ProcessToplineOptions): Promise<Blob> {
    const prog = opts.onProgress ?? (() => {});

    prog('Décodage audio…', 5);
    const [voiceRaw, beatRaw] = await Promise.all([
      this.decodeBlob(opts.voiceBlob),
      this._fetchAndDecode(opts.beatStreamUrl, opts.accessToken),
    ]);

    prog('Préparation de la voix…', 18);
    const voiceMono = this._toMono(voiceRaw);

    // Le gate doit précéder le convolver : sans ça, le silence entre les phrases
    // déclenche une longue queue de réverb qui noie le mix.
    prog('Nettoyage du silence…', 28);
    const voiceGated = this._applyNoiseGate(voiceMono);

    prog('Effets vocaux…', 38);
    const voiceFx = await this._applyVocalChain(voiceGated, opts.params);

    prog('Correction de hauteur…', 62);
    const voiceTuned = opts.params.useAutotune && opts.params.trackKey
      ? await this._applyAutotune(voiceFx, opts.params.trackKey)
      : voiceFx;

    prog('Mixage voix + beat…', 78);
    const mixed = await this._mixVoiceAndBeat(voiceTuned, beatRaw, opts.params);

    prog('Encodage MP3…', 92);
    const mp3 = this._encodeToMp3(mixed);

    prog('Terminé', 100);
    return mp3;
  }

  // ── Entrées multi-pistes ─────────────────────────────────────────────────────

  /**
   * Traite une seule piste vocale : décode → effets → [autotune].
   * Retourne le PCM mono 48kHz sans volume appliqué (le volume est géré au mix).
   */
  async processVocalTrack(opts: ProcessVocalTrackOptions): Promise<Float32Array> {
    const prog = opts.onProgress ?? (() => {});
    const { blob, settings, trackKey, latencyHintMs = 0 } = opts;

    prog('Décodage…', 5);
    const raw  = await this.decodeBlob(blob);
    const mono = this._toMono(raw);

    prog('Nettoyage du silence…', 20);
    const gated = this._applyNoiseGate(mono);

    // Compensation de latence
    const cropSamples = Math.min(
      Math.max(0, Math.floor(latencyHintMs * SR / 1000)),
      gated.length - Math.floor(0.5 * SR),
    );
    const cropped = cropSamples > 0
      ? (() => {
          const ctx = new this.offlineCtx(1, gated.length - cropSamples, SR);
          const buf = ctx.createBuffer(1, gated.length - cropSamples, SR);
          buf.getChannelData(0).set(gated.getChannelData(0).subarray(cropSamples));
          return buf;
        })()
      : gated;

    prog('Effets vocaux…', 40);
    const chainParams: MixParameters = {
      reverbWet:    settings.reverbWet,
      voiceGain:    1.0,  // volume appliqué pendant le mix, pas ici
      beatGain:     0,
      useAutotune:  false,
      trackKey,
      latencyHintMs: 0,
      clarityDb:    settings.clarityDb,
    };
    const withFx = await this._applyVocalChain(cropped, chainParams);

    prog('Correction de hauteur…', 70);
    const tuned = settings.useAutotune && trackKey
      ? await this._applyAutotune(withFx, trackKey)
      : withFx;

    prog('Terminé', 100);
    return tuned.getChannelData(0).slice();
  }

  /**
   * Mixe N pistes vocales traitées + beat → MP3 Blob.
   */
  async mixAndExport(opts: MixAndExportOptions): Promise<Blob> {
    const prog = opts.onProgress ?? (() => {});
    const { vocals, beatStreamUrl, beatGain, accessToken } = opts;

    prog('Chargement du beat…', 5);
    const beatRaw = opts.beatBlob
      ? await this.decodeBlob(opts.beatBlob)
      : await this._fetchAndDecode(beatStreamUrl, accessToken);

    // Durée du mix : minimum(toutes pistes vocales, beat)
    const vocalLen = vocals.length > 0
      ? Math.max(...vocals.map(v => v.samples.length))
      : beatRaw.length;
    const totalFrames = Math.min(vocalLen, beatRaw.length);

    prog('Mixage…', 30);
    const ctx = new this.offlineCtx(2, totalFrames, SR);

    // Beat
    const beatSrc = ctx.createBufferSource();
    beatSrc.buffer = beatRaw;
    const beatG = ctx.createGain(); beatG.gain.value = beatGain;
    beatSrc.connect(beatG).connect(ctx.destination);
    beatSrc.start(0);

    // Pistes vocales
    for (const { samples, settings } of vocals) {
      const len = Math.min(samples.length, totalFrames);
      const vBuf = ctx.createBuffer(1, len, SR);
      vBuf.getChannelData(0).set(samples.subarray(0, len));
      const vSrc = ctx.createBufferSource();
      vSrc.buffer = vBuf;
      const vGain = ctx.createGain(); vGain.gain.value = settings.volume;
      vSrc.connect(vGain).connect(ctx.destination);
      vSrc.start(0);
    }

    const mixed = await ctx.startRendering();

    prog('Pic guard…', 80);
    const guarded = this._peakGuard(mixed);

    prog('Encodage MP3…', 92);
    const mp3 = this._encodeToMp3(guarded);

    prog('Terminé', 100);
    return mp3;
  }

  // ── Preview rapide ───────────────────────────────────────────────────────────

  /**
   * Mix instantané sans DSP ni WSOLA — pour la prévisualisation avant export.
   * Décode tous les blobs en parallèle, applique uniquement les volumes de piste,
   * retourne un AudioBuffer prêt à jouer (typiquement < 1 s pour 2 pistes de 3 min).
   */
  async quickMix(opts: QuickMixOptions): Promise<AudioBuffer> {
    const { vocals, beatStreamUrl, beatGain, accessToken, beatBlob } = opts;

    const beatPromise = beatBlob
      ? this.decodeBlob(beatBlob)
      : this._fetchAndDecode(beatStreamUrl, accessToken);

    const [beatRaw, ...vocalBufs] = await Promise.all([
      beatPromise,
      ...vocals.map(v => this.decodeBlob(v.blob)),
    ]);

    // Durée du mix = min(plus long vocal, beat) — cohérent avec mixAndExport
    const vocalLen  = vocalBufs.length > 0
      ? Math.max(...vocalBufs.map(b => b.length))
      : beatRaw.length;
    const totalLen  = Math.min(vocalLen, beatRaw.length);

    const ctx = new this.offlineCtx(2, totalLen, SR);

    const beatSrc = ctx.createBufferSource();
    beatSrc.buffer = beatRaw;
    const beatG = ctx.createGain();
    beatG.gain.value = beatGain;
    beatSrc.connect(beatG).connect(ctx.destination);
    beatSrc.start(0);

    for (let i = 0; i < vocalBufs.length; i++) {
      const mono  = this._toMono(vocalBufs[i]);
      const len   = Math.min(mono.length, totalLen);
      const vBuf  = ctx.createBuffer(1, len, SR);
      vBuf.getChannelData(0).set(mono.getChannelData(0).subarray(0, len));
      const vSrc  = ctx.createBufferSource();
      vSrc.buffer = vBuf;
      const vGain = ctx.createGain();
      vGain.gain.value = vocals[i].volume;
      vSrc.connect(vGain).connect(ctx.destination);
      vSrc.start(0);
    }

    const mixed = await ctx.startRendering();
    return this._peakGuard(mixed);
  }

  // ── Punch-in ─────────────────────────────────────────────────────────────────

  /**
   * Assemble deux blobs PCM : conserve les `fromSec` premières secondes de
   * `existing`, puis y colle `newAudio` bout à bout.
   * Les deux blobs sont normalisés à 48kHz mono avant l'assemblage.
   */
  async spliceAudio(existing: Blob, newAudio: Blob, fromSec: number): Promise<Blob> {
    const [existBuf, newBuf] = await Promise.all([
      this.decodeBlob(existing),
      this.decodeBlob(newAudio),
    ]);

    const keepSamples  = Math.min(Math.max(0, Math.floor(fromSec * SR)), existBuf.length);
    const totalSamples = keepSamples + newBuf.length;
    const result       = new Float32Array(totalSamples);

    result.set(existBuf.getChannelData(0).subarray(0, keepSamples), 0);
    result.set(newBuf.getChannelData(0), keepSamples);

    return new Blob([result.buffer as ArrayBuffer], { type: 'audio/pcm-f32' });
  }

  // ── Décodage ─────────────────────────────────────────────────────────────────

  /**
   * Décode n'importe quel blob audio en AudioBuffer normalisé 48kHz mono.
   * Gère les formats natifs PCM (iOS float32, Android int16) et les containers
   * encodés (WebM, OGG, MP4) — contrairement à `AudioContext.decodeAudioData`
   * qui rejette le PCM brut sans headers.
   */
  async decodeBlob(blob: Blob): Promise<AudioBuffer> {
    const ab = await blob.arrayBuffer();

    // PCM Float32 natif iOS (AVAudioEngine installTap)
    if (blob.type.startsWith('audio/pcm-f32')) {
      return this._pcmToCanonicalRate(new Float32Array(ab), this._nativeRate(blob.type));
    }

    // PCM Int16 natif Android (AudioRecord)
    if (blob.type.startsWith('audio/pcm-i16')) {
      const i16 = new Int16Array(ab);
      const f32 = new Float32Array(i16.length);
      for (let i = 0; i < i16.length; i++) f32[i] = i16[i] / 32768;
      return this._pcmToCanonicalRate(f32, this._nativeRate(blob.type));
    }

    // WebM/OGG/MP4 (enregistrement web bureau)
    const ctx = new this.offlineCtx(2, SR, SR);
    return ctx.decodeAudioData(ab);
  }

  /**
   * Extrait le sample rate natif encodé par le plugin dans le MIME type
   * (ex. "audio/pcm-i16;rate=44100") — Android capture à 44,1 kHz alors qu'iOS
   * suit le sample rate matériel (souvent 48 kHz mais pas garanti). Sans ce tag,
   * un enregistrement Android serait décodé comme s'il était à 48 kHz : vitesse
   * et hauteur décalées d'~8,8 %, et tous les filtres du pipeline (calés sur SR)
   * appliqués à la mauvaise fréquence. Défaut à SR pour les blobs déjà normalisés
   * (sortie de spliceAudio/autotune/export, qui sont toujours au sample rate canonique).
   */
  private _nativeRate(mimeType: string): number {
    const m = /;rate=(\d+)/.exec(mimeType);
    return m ? parseInt(m[1], 10) : SR;
  }

  /** Ramène un PCM brut capturé à `srcRate` au sample rate canonique du pipeline (SR). */
  private async _pcmToCanonicalRate(samples: Float32Array, srcRate: number): Promise<AudioBuffer> {
    if (srcRate === SR) {
      const ctx = new this.offlineCtx(1, samples.length, SR);
      const buf = ctx.createBuffer(1, samples.length, SR);
      buf.getChannelData(0).set(samples);
      return buf;
    }

    // Resampling via le moteur Web Audio : un AudioBufferSourceNode est rééchantillonné
    // automatiquement vers le sample rate du contexte de destination au rendu.
    const srcCtx = new this.offlineCtx(1, samples.length, srcRate);
    const srcBuf = srcCtx.createBuffer(1, samples.length, srcRate);
    srcBuf.getChannelData(0).set(samples);

    const targetLength = Math.max(1, Math.ceil(samples.length * SR / srcRate));
    const dstCtx = new this.offlineCtx(1, targetLength, SR);
    const src    = dstCtx.createBufferSource();
    src.buffer   = srcBuf;
    src.connect(dstCtx.destination);
    src.start();
    return dstCtx.startRendering();
  }

  private async _fetchAndDecode(url: string, token: string): Promise<AudioBuffer> {
    const resp = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!resp.ok) throw new Error(`Beat fetch: HTTP ${resp.status}`);
    const ab  = await resp.arrayBuffer();
    const ctx = new this.offlineCtx(2, SR, SR);
    return ctx.decodeAudioData(ab);
  }

  // ── Mono mix ─────────────────────────────────────────────────────────────────

  private _toMono(buf: AudioBuffer): AudioBuffer {
    const len = buf.length;
    const out = new Float32Array(len);
    const nCh = buf.numberOfChannels;
    for (let c = 0; c < nCh; c++) {
      const ch = buf.getChannelData(c);
      for (let i = 0; i < len; i++) out[i] += ch[i] / nCh;
    }
    const ctx    = new this.offlineCtx(1, len, SR);
    const result = ctx.createBuffer(1, len, SR);
    result.getChannelData(0).set(out);
    return result;
  }

  // ── Noise gate ───────────────────────────────────────────────────────────────
  // Filtre one-pole avec suivi d'enveloppe asymétrique attack/release.
  // Le gain du gate est lui-même lissé pour éviter les clics à l'ouverture/fermeture.

  private _applyNoiseGate(buf: AudioBuffer): AudioBuffer {
    const threshold = Math.pow(10, GATE_THRESHOLD_DB / 20);
    // τ = -1/ln(coeff) ⟹ coeff = exp(-1 / (sr · t))
    const atCoeff  = Math.exp(-1 / (SR * GATE_ATTACK_MS  / 1000));
    const relCoeff = Math.exp(-1 / (SR * GATE_RELEASE_MS / 1000));

    const src = buf.getChannelData(0);
    const out = new Float32Array(src.length);
    let env  = 0;
    let gate = 0;

    for (let i = 0; i < src.length; i++) {
      const level = Math.abs(src[i]);
      env = level > env
        ? atCoeff  * env + (1 - atCoeff)  * level
        : relCoeff * env + (1 - relCoeff) * level;

      const target = env > threshold ? 1.0 : 0.0;
      gate += (target - gate) * (target > gate ? (1 - atCoeff) : (1 - relCoeff));
      out[i] = src[i] * gate;
    }

    const ctx    = new this.offlineCtx(1, buf.length, SR);
    const result = ctx.createBuffer(1, buf.length, SR);
    result.getChannelData(0).set(out);
    return result;
  }

  // ── Chaîne d'effets vocaux ────────────────────────────────────────────────────

  private async _applyVocalChain(voice: AudioBuffer, params: MixParameters): Promise<AudioBuffer> {
    const len = voice.length;
    const ctx = new this.offlineCtx(1, len, SR);

    const src = ctx.createBufferSource();
    src.buffer = voice;

    // ── HPF ordre 4 Butterworth (deux sections 2nd-ordre en cascade) ─────────────
    const hp1 = ctx.createBiquadFilter();
    hp1.type = 'highpass'; hp1.frequency.value = HPF_FREQ; hp1.Q.value = HPF_Q1;
    const hp2 = ctx.createBiquadFilter();
    hp2.type = 'highpass'; hp2.frequency.value = HPF_FREQ; hp2.Q.value = HPF_Q2;
    src.connect(hp1).connect(hp2);

    // ── LA-2A (compresseur optique) ───────────────────────────────────────────────
    // Knee très doux = caractère transparent, programme-dépendant.
    // Rôle : colle la voix, compense les variations de distance micro, prépare l'EQ.
    const la2a = ctx.createDynamicsCompressor();
    la2a.threshold.value = LA2A_THRESHOLD;
    la2a.knee.value      = LA2A_KNEE;
    la2a.ratio.value     = LA2A_RATIO;
    la2a.attack.value    = LA2A_ATTACK;
    la2a.release.value   = LA2A_RELEASE;
    hp2.connect(la2a);

    // ── EQ vocal (Presence + Pultec Air) ─────────────────────────────────────────
    // Presence : boost d'intelligibilité (consonnes, attaque des syllabes)
    const presence = ctx.createBiquadFilter();
    presence.type = 'peaking'; presence.frequency.value = PRESENCE_FREQ;
    presence.gain.value = PRESENCE_GAIN; presence.Q.value = PRESENCE_Q;
    la2a.connect(presence);

    // Pultec-style air shelf @12kHz : clarityDb pilote le gain (défaut = AIR_GAIN)
    const air = ctx.createBiquadFilter();
    air.type = 'highshelf'; air.frequency.value = AIR_FREQ;
    air.gain.value = params.clarityDb ?? AIR_GAIN;
    presence.connect(air);

    // ── 1176 (compresseur FET) ────────────────────────────────────────────────────
    // Knee dur + attaque très rapide = "snap" et solidification des transitoires.
    // Positionné après l'EQ : le shelf d'air a relevé le haut du spectre, le 1176
    // le maîtrise sans altérer l'image de brillance acquise.
    const c1176 = ctx.createDynamicsCompressor();
    c1176.threshold.value = C1176_THRESHOLD;
    c1176.knee.value      = C1176_KNEE;
    c1176.ratio.value     = C1176_RATIO;
    c1176.attack.value    = C1176_ATTACK;
    c1176.release.value   = C1176_RELEASE;
    air.connect(c1176);

    // ── De-esser : sidechain split-band (après compression) ──────────────────────
    // La compression relève les sibilances par rapport aux voyelles → le de-esser
    // ici est plus précis qu'en amont. Formule : signal_desessé = dry + comp(sib) − sib
    const dry = ctx.createGain(); dry.gain.value = 1;
    c1176.connect(dry);

    const sib = ctx.createBiquadFilter();
    sib.type = 'bandpass'; sib.frequency.value = DEESS_FREQ; sib.Q.value = DEESS_BW_Q;
    c1176.connect(sib);

    const sibComp = ctx.createDynamicsCompressor();
    sibComp.threshold.value = DEESS_THRESHOLD;
    sibComp.ratio.value     = DEESS_RATIO;
    sibComp.attack.value    = DEESS_ATTACK;
    sibComp.release.value   = DEESS_RELEASE;
    sibComp.knee.value      = 4;
    sib.connect(sibComp);

    const sibNeg = ctx.createGain(); sibNeg.gain.value = -1;
    sib.connect(sibNeg);

    const deessMerge = ctx.createGain();
    dry.connect(deessMerge);
    sibComp.connect(deessMerge);
    sibNeg.connect(deessMerge);

    // ── Gain utilisateur ──────────────────────────────────────────────────────────
    const gainNode = ctx.createGain();
    gainNode.gain.value = params.voiceGain;
    deessMerge.connect(gainNode);

    // ── Tanh soft limiter ─────────────────────────────────────────────────────────
    const limiter = this._createTanhLimiter(ctx);
    gainNode.connect(limiter);

    // ── Plate reverb ──────────────────────────────────────────────────────────────
    const ir   = await this._getPlateIR();
    const conv = ctx.createConvolver();
    const irBuf = ctx.createBuffer(1, ir.length, SR);
    irBuf.getChannelData(0).set(ir.getChannelData(0));
    conv.buffer    = irBuf;
    conv.normalize = false;

    const dryG = ctx.createGain(); dryG.gain.value = 1 - params.reverbWet;
    const wetG = ctx.createGain(); wetG.gain.value = params.reverbWet;
    limiter.connect(dryG);
    limiter.connect(conv); conv.connect(wetG);

    const reverbOut = ctx.createGain();
    dryG.connect(reverbOut); wetG.connect(reverbOut);
    reverbOut.connect(ctx.destination);

    src.start(0);
    return ctx.startRendering();
  }

  // ── Tanh soft limiter ─────────────────────────────────────────────────────────

  private _createTanhLimiter(ctx: BaseAudioContext): WaveShaperNode {
    const curve = new Float32Array(LIMITER_CURVE_RES);
    for (let i = 0; i < LIMITER_CURVE_RES; i++) {
      const x  = (i * 2) / LIMITER_CURVE_RES - 1;
      curve[i] = Math.tanh(x * LIMITER_DRIVE / LIMITER_CEILING) * LIMITER_CEILING;
    }
    const node      = ctx.createWaveShaper();
    node.curve      = curve;
    // 4x oversampling : supprime les alias harmoniques que tanh introduit au-delà de Nyquist
    node.oversample = '4x';
    return node;
  }

  // ── Plate reverb IR ───────────────────────────────────────────────────────────
  // IR synthétique par bruit exponentiel filtré.
  // Caractère "plate" : densité modale élevée, pas de flutter echo, rolloff HF naturel.
  // Fade-in raised-cosine sur 20 ms pour éviter le click à l'onset de l'IR.

  private _getPlateIR(): Promise<AudioBuffer> {
    if (!this._plateIRCache) {
      this._plateIRCache = this._generatePlateIR();
    }
    return this._plateIRCache;
  }

  private async _generatePlateIR(): Promise<AudioBuffer> {
    const len     = Math.floor(PLATE_DECAY_S * SR);
    const offline = new this.offlineCtx(1, len, SR);

    const noise  = offline.createBuffer(1, len, SR);
    const d      = noise.getChannelData(0);
    const fadeIn = Math.floor(0.02 * SR); // 20 ms raised-cosine

    for (let i = 0; i < len; i++) {
      const fade = i < fadeIn ? 0.5 - 0.5 * Math.cos(Math.PI * i / fadeIn) : 1;
      d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 1.5) * fade;
    }

    const src = offline.createBufferSource();
    src.buffer = noise;

    const hp = offline.createBiquadFilter();
    hp.type = 'highpass'; hp.frequency.value = PLATE_HP_HZ; hp.Q.value = 0.7;
    const lp = offline.createBiquadFilter();
    lp.type = 'lowpass';  lp.frequency.value = PLATE_LP_HZ; lp.Q.value = 0.5;

    src.connect(hp).connect(lp).connect(offline.destination);
    src.start(0);
    return offline.startRendering();
  }

  // ── Autotune ──────────────────────────────────────────────────────────────────
  // Approche "global median shift" améliorée :
  //   1. Détection YIN frame par frame (pitchy)
  //   2. Lissage par médiane glissante (5 frames) → élimine les spike d'octave
  //   3. Rejet des valeurs aberrantes (>1 octave de la médiane globale)
  //   4. Correction clamped à ±AUTOTUNE_CLAMP semitones
  //   5. Pitch shift via SoundTouch WSOLA (préserve la durée)

  private async _applyAutotune(buffer: AudioBuffer, trackKey: string): Promise<AudioBuffer> {
    const data  = buffer.getChannelData(0);
    const scale = this.buildScaleNotes(trackKey);
    if (!scale.length) return buffer;

    const detector  = PitchDetector.forFloat32Array(PITCH_FRAME);
    const rawFrames: number[] = [];

    for (let i = 0; i + PITCH_FRAME < data.length; i += PITCH_HOP) {
      const frame = data.subarray(i, i + PITCH_FRAME);
      const [hz, clarity] = detector.findPitch(frame, SR);
      if (clarity >= PITCH_CLARITY && hz >= PITCH_HZ_MIN && hz <= PITCH_HZ_MAX) {
        rawFrames.push(hz);
      }
    }
    if (rawFrames.length < 10) return buffer;

    // Médiane glissante — fenêtre de PITCH_SMOOTH_K frames
    const smoothed: number[] = [];
    const win: number[]      = [];
    for (const p of rawFrames) {
      win.push(p);
      if (win.length > PITCH_SMOOTH_K) win.shift();
      const s = [...win].sort((a, b) => a - b);
      smoothed.push(s[Math.floor(s.length / 2)]);
    }

    // Médiane globale de la session
    const all    = [...smoothed].sort((a, b) => a - b);
    const global = all[Math.floor(all.length / 2)];

    // Rejet des aberrants > ±12 semitones (erreurs d'octave non corrigées)
    const clean = smoothed.filter(p => Math.abs(12 * Math.log2(p / global)) < 12);
    if (!clean.length) return buffer;

    const sorted   = [...clean].sort((a, b) => a - b);
    const dominant = sorted[Math.floor(sorted.length / 2)];

    // Note cible la plus proche dans la gamme
    const target   = scale.reduce((a: number, b: number) =>
      Math.abs(12 * Math.log2(b / dominant)) < Math.abs(12 * Math.log2(a / dominant)) ? b : a,
    );
    let semitones  = 12 * Math.log2(target / dominant);

    // Clamp : une correction > 3 semi-tons signale une détection erronée, pas un chanteur faux
    semitones = Math.max(-AUTOTUNE_CLAMP, Math.min(AUTOTUNE_CLAMP, semitones));
    if (Math.abs(semitones) < 0.10) return buffer;

    return this._pitchShift(buffer, semitones);
  }

  buildScaleNotes(key: string): number[] {
    const parts   = key.trim().split(/\s+/);
    let root      = parts[0] ?? '';
    const isMinor = parts[1]?.toLowerCase().includes('min') ?? false;

    const noteNames = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
    const flats: Record<string, string> = { Db:'C#', Eb:'D#', Gb:'F#', Ab:'G#', Bb:'A#' };
    root = flats[root] ?? root;
    let rootIdx = noteNames.indexOf(root);
    if (rootIdx === -1) return [];

    // Mineur → majeur relatif (même gamme, fondamentale +3 semi-tons)
    if (isMinor) rootIdx = (rootIdx + 3) % 12;

    const majorIntervals = [0, 2, 4, 5, 7, 9, 11];
    const notes: number[] = [];
    for (let oct = -3; oct <= 3; oct++) {
      for (const semi of majorIntervals) {
        const hz = 440 * Math.pow(2, (rootIdx - 9 + semi + oct * 12) / 12);
        if (hz >= 50 && hz <= 2000) notes.push(hz);
      }
    }
    return notes.sort((a, b) => a - b);
  }

  private _pitchShift(buffer: AudioBuffer, semitones: number): Promise<AudioBuffer> {
    return new Promise(resolve => {
      const st = new SoundTouch(SR);
      st.pitchSemitones = semitones;

      const mono   = buffer.getChannelData(0);
      const len    = mono.length;
      const output = new Float32Array(len);
      const block  = 4096;
      // SoundTouch attend un flux stéréo interleaved (L R L R…)
      const tmp    = new Float32Array(block * 2);

      const source = {
        extract: (target: Float32Array, nFrames: number, pos: number): number => {
          const avail = Math.min(nFrames, len - pos);
          if (avail <= 0) return 0;
          for (let i = 0; i < avail; i++) {
            target[i * 2]     = mono[pos + i];
            target[i * 2 + 1] = mono[pos + i];
          }
          return avail;
        },
      };

      const filter = new SimpleFilter(source, st);
      let wp = 0;
      while (wp < len) {
        const n = filter.extract(tmp, block);
        if (n === 0) break;
        for (let i = 0; i < n && wp < len; i++) output[wp++] = tmp[i * 2];
      }

      const ctx = new this.offlineCtx(1, len, SR);
      const out = ctx.createBuffer(1, len, SR);
      out.getChannelData(0).set(output);
      resolve(out);
    });
  }

  // ── Mix voix + beat ───────────────────────────────────────────────────────────

  private async _mixVoiceAndBeat(
    voice: AudioBuffer,
    beat: AudioBuffer,
    params: MixParameters,
  ): Promise<AudioBuffer> {
    // Compensation de latence : le chanteur entend le beat avec un retard de latencyHintMs.
    // Sa voix arrive donc en retard dans le mix. On coupe le début de la voix pour l'aligner.
    const cropSamples = Math.min(
      Math.max(0, Math.floor(params.latencyHintMs * SR / 1000)),
      voice.length - Math.floor(0.5 * SR), // garder au moins 500 ms
    );

    const voiceLen    = voice.length - cropSamples;
    const totalFrames = Math.min(voiceLen, beat.length);

    const ctx = new this.offlineCtx(2, totalFrames, SR);

    const beatSrc = ctx.createBufferSource();
    beatSrc.buffer = beat;
    const beatGain = ctx.createGain();
    beatGain.gain.value = params.beatGain;
    beatSrc.connect(beatGain).connect(ctx.destination);
    beatSrc.start(0);

    const voiceBuf = ctx.createBuffer(1, voiceLen, SR);
    voiceBuf.getChannelData(0).set(voice.getChannelData(0).subarray(cropSamples));
    const voiceSrc = ctx.createBufferSource();
    voiceSrc.buffer = voiceBuf;
    voiceSrc.connect(ctx.destination);
    voiceSrc.start(0);

    const mixed = await ctx.startRendering();
    return this._peakGuard(mixed);
  }

  // ── Peak guard ────────────────────────────────────────────────────────────────
  // Normalisation down uniquement (jamais d'amplification) pour éviter l'écrêtage
  // dans les cas où voiceGain > 1 provoque des sommes dépassant 0 dBFS.

  private _peakGuard(buf: AudioBuffer, ceiling = 0.92): AudioBuffer {
    let peak = 0;
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < d.length; i++) if (Math.abs(d[i]) > peak) peak = Math.abs(d[i]);
    }
    if (peak > ceiling) {
      const gain = ceiling / peak;
      for (let c = 0; c < buf.numberOfChannels; c++) {
        const d = buf.getChannelData(c);
        for (let i = 0; i < d.length; i++) d[i] *= gain;
      }
    }
    return buf;
  }

  // ── Encodage MP3 (lamejs @ 192 kbps) ─────────────────────────────────────────

  private _encodeToMp3(buf: AudioBuffer): Blob {
    const nCh   = buf.numberOfChannels;
    const enc   = new Mp3Encoder(nCh > 1 ? 2 : 1, SR, MP3_KBPS);
    const parts: Uint8Array[] = [];
    const block = 1152; // taille de frame MP3 standard

    const L = buf.getChannelData(0);
    const R = nCh > 1 ? buf.getChannelData(1) : L;

    for (let i = 0; i < L.length; i += block) {
      const end = Math.min(i + block, L.length);
      const lc  = this._toInt16(L.subarray(i, end));
      const rc  = this._toInt16(R.subarray(i, end));
      const seg = nCh > 1 ? enc.encodeBuffer(lc, rc) : enc.encodeBuffer(lc);
      if (seg.length > 0) parts.push(new Uint8Array(seg.buffer));
    }
    const tail = enc.flush();
    if (tail.length > 0) parts.push(new Uint8Array(tail.buffer));

    return new Blob(parts as unknown as BlobPart[], { type: 'audio/mpeg' });
  }

  private _toInt16(f32: Float32Array): Int16Array {
    const i16 = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      i16[i] = Math.max(-32768, Math.min(32767, Math.round(f32[i] * 32767)));
    }
    return i16;
  }
}
