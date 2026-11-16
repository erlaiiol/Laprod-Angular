import { Injectable, inject, signal, computed } from '@angular/core';
import {
  MobileAudioProcessorService,
  TrackSettings,
  DEFAULT_TRACK_SETTINGS,
} from './mobile-audio-processor.service';
import { AuthService } from './auth.service';

// ── Modèle de données ─────────────────────────────────────────────────────────

export type { TrackSettings };

export interface VocalTrack {
  id:           string;
  name:         string;
  rawBlob:      Blob | null;
  processedBlob: Blob | null;  // voix autotunée (sans effets) — null jusqu'au 1er toggle ON
  waveform:     number[];      // 120 points [0–1] pour le canvas
  duration:     number;        // secondes
  /** Position du beat (s) où démarre la piste, latence casque déjà compensée :
   *  la voix est rejouée/mixée exactement là où elle a été chantée. */
  beatStartSec: number;
  settings:     TrackSettings;
  trackState:   'empty' | 'recording' | 'recorded' | 'processing';
  /** Couleur de la piste dans la timeline (attribuée à la création, stable ensuite). */
  color:        string;
}

/** Couleurs des pistes vocales — le rouge de la marque est réservé à l'instrumentale. */
export const TRACK_COLORS: readonly string[] = [
  '#4FC3F7', '#FFB74D', '#81C784', '#BA68C8', '#4DD0E1', '#F06292', '#FFD54F', '#9575CD',
];

const FREE_TRACK_LIMIT = 2;

let _idCounter = 0;
function newId(): string { return `t${Date.now()}_${_idCounter++}`; }

interface UndoEntry {
  rawBlob:       Blob;
  processedBlob: Blob | null;
  waveform:      number[];
  duration:      number;
  beatStartSec:  number;
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class MobileMaquetteService {

  private readonly processor = inject(MobileAudioProcessorService);
  private readonly auth      = inject(AuthService);

  readonly tracks           = signal<VocalTrack[]>([]);
  readonly isExporting      = signal(false);
  readonly exportPct        = signal(0);
  readonly exportStep       = signal('');
  readonly extendedBeatBlob = signal<Blob | null>(null);
  /** Piste dont les réglages sont appliqués au retour casque (dernière dépliée/réglée). */
  readonly focusedTrackId   = signal<string | null>(null);

  // Une seule entrée undo par piste — restaure la prise précédente après re-enregistrement
  private readonly _undoMap = new Map<string, UndoEntry>();

  /** true si l'utilisateur peut ajouter une piste supplémentaire */
  canAddTrack(): boolean {
    return this.auth.isPremium() || this.tracks().length < FREE_TRACK_LIMIT;
  }

  // ── CRUD pistes ──────────────────────────────────────────────────────────────

  addTrack(): string {
    const id: string = newId();
    const n = this.tracks().length + 1;
    const track: VocalTrack = {
      id,
      name:         `Voix ${n}`,
      rawBlob:      null,
      processedBlob: null,
      waveform:     [],
      duration:     0,
      beatStartSec: 0,
      settings:     { ...DEFAULT_TRACK_SETTINGS },
      trackState:   'empty',
      color:        this._nextColor(),
    };
    this.tracks.update(ts => [...ts, track]);
    return id;
  }

  /** Première couleur de la palette non utilisée par une piste existante. */
  private _nextColor(): string {
    const used = new Set(this.tracks().map(t => t.color));
    return TRACK_COLORS.find(c => !used.has(c)) ?? TRACK_COLORS[this.tracks().length % TRACK_COLORS.length];
  }

  removeTrack(id: string): void {
    this.tracks.update(ts => ts.filter(t => t.id !== id));
    if (this.focusedTrackId() === id) this.focusedTrackId.set(null);
  }

  focusTrack(id: string): void { this.focusedTrackId.set(id); }

  setRecording(id: string): void {
    this._patchTrack(id, { trackState: 'recording' });
  }

  /**
   * Prise avortée (erreur, arrêt immédiat) : une piste qui avait déjà une prise
   * la garde ; une piste vide ajoutée pour l'occasion est retirée, sauf si c'est
   * la seule (le studio garde toujours une piste prête à enregistrer).
   */
  cancelRecording(id: string): void {
    const t = this.tracks().find(x => x.id === id);
    if (!t) return;
    if (t.rawBlob) {
      this._patchTrack(id, { trackState: 'recorded' });
    } else if (this.tracks().length > 1) {
      this.removeTrack(id);
    } else {
      this._patchTrack(id, { trackState: 'empty' });
    }
  }

  setRecorded(id: string, rawBlob: Blob, waveform: number[], duration: number, beatStartSec = 0): void {
    // Sauvegarde la prise actuelle avant d'écraser — permet un undo unique
    const existing = this.tracks().find(t => t.id === id);
    if (existing?.rawBlob) {
      this._undoMap.set(id, {
        rawBlob:       existing.rawBlob,
        processedBlob: existing.processedBlob,
        waveform:      [...existing.waveform],
        duration:      existing.duration,
        beatStartSec:  existing.beatStartSec,
      });
    }
    this._patchTrack(id, {
      rawBlob,
      processedBlob: null,  // invalide le cache autotune après re-enregistrement
      waveform,
      duration,
      beatStartSec,
      trackState: 'recorded',
    });
  }

  /** Retourne true si une prise précédente est disponible pour la piste. */
  hasUndoFor(id: string): boolean {
    return this._undoMap.has(id);
  }

  /**
   * Restaure la prise précédente d'une piste.
   * Retourne false si aucun undo n'est disponible (un seul niveau d'undo par piste).
   */
  undoLastTake(id: string): boolean {
    const prev = this._undoMap.get(id);
    if (!prev) return false;
    this._undoMap.delete(id);
    this._patchTrack(id, {
      rawBlob:       prev.rawBlob,
      processedBlob: prev.processedBlob,
      waveform:      prev.waveform,
      duration:      prev.duration,
      beatStartSec:  prev.beatStartSec,
      trackState:    'recorded',
    });
    return true;
  }

  setExtendedBeat(blob: Blob): void  { this.extendedBeatBlob.set(blob); }
  clearExtendedBeat(): void          { this.extendedBeatBlob.set(null); }

  renameTrack(id: string, name: string): void {
    const trimmed = name.trim();
    if (trimmed) this._patchTrack(id, { name: trimmed });
  }

  updateSettings(id: string, partial: Partial<TrackSettings>): void {
    this.tracks.update(ts => ts.map(t => {
      if (t.id !== id) return t;
      const newSettings = { ...t.settings, ...partial };
      // Si autotune passe à OFF, le processedBlob reste en cache pour le prochain toggle ON
      return { ...t, settings: newSettings };
    }));
  }

  // ── Autotune à la demande ────────────────────────────────────────────────────

  async ensureAutotune(id: string, trackKey: string): Promise<void> {
    const track = this.tracks().find(t => t.id === id);
    if (!track?.rawBlob || track.processedBlob) return;  // no-op si déjà calculé
    if (!track.settings.useAutotune) return;

    this._patchTrack(id, { trackState: 'processing' });
    try {
      // Autotune sur la voix brute uniquement : les effets (EQ, compression, réverb)
      // sont appliqués une seule fois, plus tard, à l'écoute et à l'export — ils
      // restent donc réglables après coup et ne sont jamais appliqués deux fois.
      const processed = await this.processor.autotuneOnly(track.rawBlob, trackKey);

      const processedBlob = new Blob([processed.buffer as ArrayBuffer], { type: 'audio/pcm-f32' });
      this._patchTrack(id, { processedBlob, trackState: 'recorded' });
    } catch {
      this._patchTrack(id, { trackState: 'recorded' });
    }
  }

  // ── Export complet ───────────────────────────────────────────────────────────

  async exportMaquette(opts: {
    beatStreamUrl: string;
    beatGain:      number;
    accessToken:   string;
    trackKey:      string;
    latencyHintMs: number;
    /** Beat pré-téléchargé localement — évite un fetch réseau lors de l'export. */
    beatBlob?:     Blob;
  }): Promise<Blob> {
    const tracks = this.tracks().filter(t => t.rawBlob !== null);
    if (tracks.length === 0) throw new Error('Aucune piste enregistrée');

    this.isExporting.set(true);
    this.exportPct.set(0);
    this.exportStep.set('Préparation…');

    try {
      // 1. Assurer que l'autotune est calculé — traitement en parallèle pour toutes les pistes
      const needsAutotune = tracks.filter(t => t.settings.useAutotune && !t.processedBlob);
      if (needsAutotune.length > 0) {
        this.exportStep.set('Correction de hauteur…');
        await Promise.all(needsAutotune.map(t => this.ensureAutotune(t.id, opts.trackKey)));
      }

      // 2. Traiter chaque piste (effets uniquement, l'autotune est déjà dans processedBlob ou non)
      const processed: Array<{ samples: Float32Array; settings: TrackSettings; startSec: number }> = [];
      const total = tracks.length;

      for (let i = 0; i < total; i++) {
        const t = this.tracks().find(x => x.id === tracks[i].id)!;
        this.exportStep.set(`Traitement ${t.name}…`);

        // Utiliser processedBlob (avec autotune) ou rawBlob (sans)
        const activeBlob = (t.settings.useAutotune && t.processedBlob)
          ? t.processedBlob
          : t.rawBlob!;

        // Effets sans autotune (déjà appliqué si processedBlob)
        const settingsNoTune: TrackSettings = { ...t.settings, useAutotune: false };
        const blobToProcess = (t.settings.useAutotune && t.processedBlob)
          ? t.processedBlob
          : t.rawBlob!;

        const samples = await this.processor.processVocalTrack({
          blob:          blobToProcess,
          settings:      settingsNoTune,
          trackKey:      opts.trackKey,
          latencyHintMs: opts.latencyHintMs,
          onProgress:    (_, pct) => {
            const base = (i / total) * 70;
            const slot = (1 / total) * 70;
            this.exportPct.set(Math.round(base + (pct / 100) * slot));
          },
        });
        processed.push({ samples, settings: t.settings, startSec: t.beatStartSec });
      }

      // 3. Mix + export MP3
      this.exportStep.set('Mixage final…');
      this.exportPct.set(75);

      const mp3 = await this.processor.mixAndExport({
        vocals:        processed,
        beatStreamUrl: opts.beatStreamUrl,
        beatGain:      opts.beatGain,
        accessToken:   opts.accessToken,
        latencyHintMs: opts.latencyHintMs,
        beatBlob:      this.extendedBeatBlob() ?? opts.beatBlob ?? undefined,
        onProgress:    (step, pct) => {
          this.exportStep.set(step);
          this.exportPct.set(75 + Math.round(pct * 0.25));
        },
      });

      this.exportPct.set(100);
      return mp3;

    } finally {
      this.isExporting.set(false);
    }
  }

  // ── Utilitaires ──────────────────────────────────────────────────────────────

  reset(): void {
    this._undoMap.clear();
    this.tracks.set([]);
    this.isExporting.set(false);
    this.exportPct.set(0);
    this.exportStep.set('');
    this.extendedBeatBlob.set(null);
    this.focusedTrackId.set(null);
  }

  private _patchTrack(id: string, patch: Partial<VocalTrack>): void {
    this.tracks.update(ts => ts.map(t => t.id === id ? { ...t, ...patch } : t));
  }
}
