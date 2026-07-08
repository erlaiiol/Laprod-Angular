import {
  Component, Input, Output, EventEmitter, OnInit, OnDestroy,
  ChangeDetectionStrategy, ChangeDetectorRef, signal, computed, inject,
  NgZone, ViewChild, ElementRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule }  from '@angular/forms';
import { Router }       from '@angular/router';
import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';
import { App } from '@capacitor/app';
import type { PluginListenerHandle } from '@capacitor/core';

import { TrackDetail }              from '../../services/track.service';
import { ToplineService }           from '../../services/topline.service';
import { ToplineStatusService }     from '../../services/topline-status.service';
import { PlayerService }            from '../../services/player.service';
import { AuthService }              from '../../services/auth.service';
import { MobileMaquetteService, VocalTrack } from '../../services/mobile-maquette.service';
import { MobileAudioProcessorService } from '../../services/mobile-audio-processor.service';
import { LatencyCalibrationService }   from '../../services/latency-calibration.service';
import { DraftSaveService }            from '../../services/draft-save.service';
import { NativeShellService }          from '../../services/native-shell.service';
import { PITCH_MONITOR, InterruptedResult, PitchMonitorPlugin, SessionResult } from '../../services/pitch-monitor-plugin';
import { environment }              from '../../../environments/environment';
import { MobileTrackItemComponent }      from './mobile-track-item/mobile-track-item.component';
import { BeatSectionPickerComponent }    from '../beat-section-picker/beat-section-picker.component';
import { ExtendedBeatResult }           from '../../services/beat-extender.service';
import { BluetoothCalibrationComponent } from '../bluetooth-calibration/bluetooth-calibration.component';
import { MobileMetronomeService }        from '../../services/mobile-metronome.service';
import { computeWaveform, spliceWaveform } from '../../utils/waveform.utils';

// ── Types ─────────────────────────────────────────────────────────────────────

interface BeatExtendEntry {
  blob:         Blob;
  blobUrl:      string;
  totalSamples: number;
  sampleRate:   number;
  startFrac:    number;
  lengthFrac:   number;
}

type StudioState =
  | 'idle'
  | 'warming-up'
  | 'punch-in'
  | 'countdown'
  | 'recording'
  | 'previewing'
  | 'exporting'
  | 'beat-editor'
  | 'published';

type HeadphoneType = 'wired' | 'bluetooth' | 'bluetooth-a2dp' | 'none';

const MAX_REC_SECONDS  = 180;
const WAVEFORM_POINTS  = 120;
const LIVE_WAVE_POINTS = 80;
const COUNTDOWN_START     = 3;
const BT_CALIB_SHOWN_KEY  = 'laprod_bt_calib_v1';
const DEFAULT_BEAT_VOL = 0.65;

// Gammes musicales (intervalles chromatiques depuis la tonique)
const MAJOR_INTERVALS = [0, 2, 4, 5, 7, 9, 11];
const MINOR_INTERVALS = [0, 2, 3, 5, 7, 8, 10];

// Correspondance nom → index chromatique (0 = C)
const NOTE_CHROMA: Record<string, number> = {
  'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3,
  'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
  'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11,
};
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

// ── Composant ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-mobile-studio',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MobileTrackItemComponent, BeatSectionPickerComponent,
    BluetoothCalibrationComponent,
  ],
  templateUrl: './mobile-studio.component.html',
  styleUrls: ['./mobile-studio.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [MobileMetronomeService],
})
export class MobileStudioComponent implements OnInit, OnDestroy {

  @Input({ required: true }) track!: TrackDetail;
  @Output() closed = new EventEmitter<void>();

  @ViewChild('liveCanvas')     liveCanvasRef?:     ElementRef<HTMLCanvasElement>;
  @ViewChild('beatWaveCanvas') beatWaveCanvasRef?: ElementRef<HTMLCanvasElement>;

  readonly env       = environment;
  readonly noteNames = NOTE_NAMES;

  // ── Services (avant les computed qui les référencent) ─────────────────────────

  readonly service     = inject(MobileMaquetteService);
  readonly calibration = inject(LatencyCalibrationService);
  protected readonly auth = inject(AuthService);
  private pm           = inject(PITCH_MONITOR);
  private processor    = inject(MobileAudioProcessorService);
  private draftSave    = inject(DraftSaveService);
  private nativeShell  = inject(NativeShellService);
  private router       = inject(Router);
  private toplineSvc   = inject(ToplineService);
  private statusSvc    = inject(ToplineStatusService);
  private player       = inject(PlayerService);
  private cdr          = inject(ChangeDetectorRef);
  private zone         = inject(NgZone);
  readonly metronome   = inject(MobileMetronomeService);

  // ── Signaux d'état principal ──────────────────────────────────────────────────

  studioState       = signal<StudioState>('idle');
  activeRecordingId = signal<string | null>(null);
  recordTimer       = signal(0);
  recordRms         = signal(0);
  errorMsg          = signal<string | null>(null);
  countdown         = signal<number | null>(null);
  beatVolume        = signal(DEFAULT_BEAT_VOL);
  confirmReRecordId = signal<string | null>(null);
  isPlayingPreview  = signal(false);
  description       = '';
  undoToast         = signal<{ trackId: string; trackName: string } | null>(null);
  get metronomeOn() { return this.metronome.active; }

  // ── Écouteurs + monitoring ────────────────────────────────────────────────────

  headphoneType   = signal<HeadphoneType | null>(null);
  monitorAutotune = signal(false);
  retuneSpeed     = signal<'natural' | 'precise' | 'robot'>('natural');
  showCalibration = signal(false);

  // ── Beat preview (idle) ───────────────────────────────────────────────────────

  beatIsPlaying  = signal(false);
  beatWaveReady  = signal(false);
  /** Blob du beat téléchargé localement — null tant que le download est en cours. */
  private _beatBlob    = signal<Blob | null>(null);
  private _beatBlobUrl: string | null = null;
  private _beatWaveform: number[] | null = null;
  /** Blob URL du dernier beat étendu — nul si aucune extension. Utilisé par le picker au 2ème ouverture. */
  private _extendedBeatBlobUrl = signal<string | null>(null);
  /** Historique des extensions, une entrée par appel à onSectionExtended. */
  private _beatHistory: BeatExtendEntry[] = [];
  private readonly _histLen = signal(0);
  private _originalBeatDuration = 0;
  readonly undoConfirmPending  = signal(false);
  readonly canUndoExtend       = computed(() => this._histLen() > 0);
  readonly beatExtendCount     = computed(() => this._histLen());
  readonly undoWouldCutTopline = computed((): string[] => {
    if (this._histLen() === 0) return [];
    const prevDur = this._beatHistory.length > 1
      ? this._beatHistory.at(-2)!.totalSamples / this._beatHistory.at(-2)!.sampleRate
      : this._originalBeatDuration;
    return this.tracks()
      .filter(t => t.trackState === 'recorded' && t.beatStartSec + t.duration > prevDur)
      .map(t => t.name);
  });
  /** Id du requestAnimationFrame du playhead — null si inactif. */
  private _rafId: number | null = null;

  // ── Playhead ──────────────────────────────────────────────────────────────────

  beatCurrentTime = signal(0);
  beatDuration    = signal(0);

  // ── Pitch meter ───────────────────────────────────────────────────────────────

  detectedNote    = signal<string | null>(null);
  correctionCents = signal(0);

  // ── Indicateurs d'enregistrement ──────────────────────────────────────────────

  nearEnd = signal(false);  // true à partir de 15s avant la fin

  // ── Gain micro ────────────────────────────────────────────────────────────────

  micGain = signal(1.0);   // 1.0 = 0 dB, passé à startSession() comme voiceGain

  // ── BT play-ahead feedback ────────────────────────────────────────────────────

  btPreparing  = signal(false);  // true pendant le délai BT avant le countdown
  draftSaved   = signal(false);  // brève confirmation après sauvegarde locale

  // ── DAW Studio ────────────────────────────────────────────────────────────────

  selectedLane   = signal<'beat' | null>(null);
  showMonitoring = signal(false);

  // ── Permission micro + état UI supplémentaires ────────────────────────────────

  permState        = signal<'granted' | 'prompt' | 'denied' | null>(null);
  confirmClose     = signal(false);
  showGuestGate    = signal(false);
  btCountdown      = signal(0);
  publishedId      = signal<number | null>(null);
  showUpgradeSheet = signal(false);

  // ── Punch-in ─────────────────────────────────────────────────────────────────

  punchInTrackId = signal<string | null>(null);
  punchInSec     = signal(0);

  // ── Computed ──────────────────────────────────────────────────────────────────

  readonly tracks   = this.service.tracks;
  readonly canAdd   = computed(() => this.service.canAddTrack());
  readonly hasTrack = computed(() => this.service.tracks().some(t => t.rawBlob !== null));

  readonly MAX_SECONDS  = MAX_REC_SECONDS;
  readonly levelPct     = computed(() => Math.min(100, this.recordRms() * 30_000));
  /** true si le niveau ajusté au gain dépasse 85% du max — risque de saturation. */
  readonly clipWarning  = computed(() => this.recordRms() * this.micGain() > 0.85);

  /** Notes de la gamme courante (indices chromatiques 0–11). */
  readonly scaleNotes = computed(() => this._buildScaleNotes(this.track?.key ?? ''));

  /** Piste vocale en cours de punch-in (null si aucune). */
  readonly punchInTrack = computed(() =>
    this.tracks().find(t => t.id === this.punchInTrackId()) ?? null
  );

  /** Label du gain micro en dB, ex. "+3.0 dB". */
  readonly micGainDb = computed(() => {
    const db = 20 * Math.log10(this.micGain());
    return (db >= 0 ? '+' : '') + db.toFixed(1) + ' dB';
  });

  /** Index chromatique de la note détectée (-1 si aucune). */
  readonly detectedNoteIndex = computed(() => {
    const note = this.detectedNote();
    if (!note) return -1;
    return NOTE_NAMES.indexOf(note.replace(/\d+$/, ''));
  });

  /** URL du beat à analyser dans le picker — étendu si déjà rallongé, original sinon. */
  get beatPickerUrl(): string {
    return this._extendedBeatBlobUrl() ?? this.beatStreamUrl;
  }

  // ── Internals ─────────────────────────────────────────────────────────────────

  private _timerInterval:     ReturnType<typeof setInterval> | null = null;
  private _countdownInterval: ReturnType<typeof setInterval> | null = null;
  private _pitchHandle:       { remove: () => void } | null         = null;
  private _levelHandle:       { remove: () => void } | null         = null;
  private _rmsHistory:        number[]                              = [];
  private _liveRmsBars:       number[]                              = [];
  private _previewAudioCtx:   AudioContext | null                   = null;
  private _previewSource:     AudioBufferSourceNode | null          = null;
  private _punchPreviewCtx:   AudioContext | null                   = null;
  private _punchPreviewSrc:   AudioBufferSourceNode | null          = null;
  private _undoToastTimer:     ReturnType<typeof setTimeout> | null  = null;
  private _draftSavedTimer:    ReturnType<typeof setTimeout> | null  = null;
  private _interruptedHandle:  { remove: () => void } | null         = null;
  private _isFinalizingRec     = false;  // garde contre double-stop (user + interruption)
  private _warnedNearEnd       = false;
  private _errorDismissTimer:   ReturnType<typeof setTimeout>  | null = null;
  private _btCountdownInterval: ReturnType<typeof setInterval> | null = null;
  private _popBackHandler:      (() => void) | null                  = null;
  private _appStateHandle:      PluginListenerHandle | null          = null;

  // ── Lifecycle ─────────────────────────────────────────────────────────────────

  async ngOnInit(): Promise<void> {
    // Hide navbar/player and stop any in-progress playback
    this.player.studioOpen.set(true);
    this.player.pause();
    // Le beat boucle en continu en studio (comportement DAW standard).
    // Posé avant load() pour que la propriété s'applique dès le premier cycle.
    this.player.audioEl.loop = true;
    // Pre-load the beat URL onto the shared audio element so toggleBeatPreview()
    // works even if the user never played the track in the main player.
    this.player.audioEl.src = this.beatStreamUrl;
    this.player.audioEl.load();
    // Download beat in background → zero-latency local playback once ready
    this._prefetchBeat();
    // Pre-create first vocal track so controls are visible from the start
    if (this.service.tracks().length === 0) {
      this.service.addTrack();
    }

    const [perm, hp] = await Promise.all([
      this.pm.checkPermission().catch(() => ({ microphone: 'granted' as const })),
      this.pm.checkHeadphones().catch(() => ({ type: 'none' as HeadphoneType })),
    ]);

    this.permState.set(perm.microphone);
    this.headphoneType.set(hp.type as HeadphoneType);

    // Le studio est un overlay plein écran (pas une route) : intercepte le bouton
    // retour Android tant qu'il est ouvert, sinon Android quitterait l'app ou
    // naviguerait en contournant les confirmations (perte d'enregistrement).
    this._popBackHandler = this.nativeShell.pushBackHandler(() => {
      if (this.showCalibration())       { this.onCalibrationCancelled(); return true; }
      if (this.confirmReRecordId())     { this.cancelReRecord();         return true; }
      if (this.confirmClose())          { this.cancelClose();            return true; }
      if (this.showUpgradeSheet())      { this.showUpgradeSheet.set(false); this.cdr.markForCheck(); return true; }
      if (this.studioState() === 'beat-editor') { this.onBeatEditorCancelled(); return true; }
      if (this.studioState() === 'punch-in')    { this.cancelPunchIn();         return true; }
      this._closeRequested();
      return true;
    });

    // L'app peut être mise en arrière-plan (verrouillage écran, swipe home) sans
    // que la session audio native ne remonte d'événement 'sessionInterrupted' —
    // sans ça, un enregistrement resterait bloqué en 'recording' indéfiniment.
    this._appStateHandle = await App.addListener('appStateChange', ({ isActive }) => {
      this.zone.run(() => {
        if (isActive) {
          // L'AudioContext du métronome se suspend en arrière-plan ; le redémarrer
          // évite une rafale de clics de rattrapage au retour au premier plan.
          if (this.metronome.active()) { this.metronome.restart(this.track.bpm, this.player.audioEl.currentTime); }
        } else if (this.studioState() === 'recording') {
          this.stopRecording();
        }
      });
    });

    // Propose la calibration BT au premier usage
    if (hp.type === 'bluetooth'
        && !this.calibration.hasCalibration()
        && !localStorage.getItem(BT_CALIB_SHOWN_KEY)) {
      localStorage.setItem(BT_CALIB_SHOWN_KEY, '1');
      this.showCalibration.set(true);
    }

    this.cdr.markForCheck();
  }

  // ── Getters template ──────────────────────────────────────────────────────────

  get beatStreamUrl(): string {
    return `${environment.apiUrl}/api/stream/tracks/${this.track.id}/preview`;
  }

  formatTimer(s: number): string {
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, '0')}`;
  }

  // ── Warm-up ───────────────────────────────────────────────────────────────────

  async startWarmup(): Promise<void> {
    if (!await this._ensurePermission()) return;

    const wired = this.headphoneType() === 'wired';
    await this.pm.startSession({
      useMonitor:      wired,
      voiceGain:       this.micGain(),
      reverbWet:       0.0,
      trackKey:        this.track.key,
      monitorAutotune: wired && this.monitorAutotune(),
      retuneSpeed:     this.retuneSpeed(),
    });

    // Joue le beat pour que le chanteur s'échauffe dans le bon contexte
    this.player.audioEl.volume      = this.beatVolume();
    this.player.audioEl.currentTime = 0;
    this.player.audioEl.play().catch(() => {});
    this.beatIsPlaying.set(true);

    this.detectedNote.set(null);
    this.correctionCents.set(0);
    this.recordRms.set(0);

    this._levelHandle = await this.pm.addListener('level', ({ rms }) => {
      this.zone.run(() => { this.recordRms.set(rms); this.cdr.markForCheck(); });
    });

    // Écoute le pitch indépendamment de l'autotune — feedback visuel toujours utile
    this._pitchHandle = await this.pm.addListener('pitch', ({ hz, correction }) => {
      this.zone.run(() => {
        this.detectedNote.set(this._noteFromHz(hz));
        this.correctionCents.set(Math.round(correction * 100));
        this.cdr.markForCheck();
      });
    });

    this.studioState.set('warming-up');
    this.cdr.markForCheck();
  }

  async stopWarmup(): Promise<void> {
    this._levelHandle?.remove(); this._levelHandle = null;
    this._pitchHandle?.remove(); this._pitchHandle = null;
    this.detectedNote.set(null);
    this.recordRms.set(0);
    this.player.audioEl.pause();
    this.beatIsPlaying.set(false);
    await this.pm.stopSession().catch(() => {});
    await this.pm.removeAllListeners().catch(() => {});
    this.studioState.set('idle');
    this.cdr.markForCheck();
  }

  // ── Punch-in ─────────────────────────────────────────────────────────────────

  openPunchIn(trackId: string): void {
    const t = this.tracks().find(v => v.id === trackId);
    if (!t?.rawBlob) return;
    this.punchInTrackId.set(trackId);
    // Positionne le curseur au milieu par défaut
    this.punchInSec.set(Math.round(t.duration / 2));
    this._stopPreviewPlayback();
    if (this.beatIsPlaying()) { this.player.audioEl.pause(); this.beatIsPlaying.set(false); }
    this.studioState.set('punch-in');
    this.cdr.markForCheck();
  }

  cancelPunchIn(): void {
    this._stopPunchPreview();
    this.punchInTrackId.set(null);
    this.punchInSec.set(0);
    this.studioState.set('idle');
    this.cdr.markForCheck();
  }

  onPunchInSlider(event: Event): void {
    this._stopPunchPreview();
    this.punchInSec.set(+( event.target as HTMLInputElement).value);
  }

  /** Joue la piste à partir du point de punch-in pour que l'utilisateur s'y repère. */
  async previewFromPunchIn(): Promise<void> {
    this._stopPunchPreview();
    const id = this.punchInTrackId();
    const t  = this.tracks().find(v => v.id === id);
    if (!t?.rawBlob) return;

    try {
      this._punchPreviewCtx = new AudioContext();
      // processor.decodeBlob() gère le PCM brut natif (iOS/Android) que
      // AudioContext.decodeAudioData rejette sans container WAV/MP4.
      const buf = await this.processor.decodeBlob(t.rawBlob);
      const src = this._punchPreviewCtx.createBufferSource();
      src.buffer = buf;
      src.connect(this._punchPreviewCtx.destination);
      // start(when, offset, duration) — joue 4 s depuis le point de punch-in
      src.start(0, this.punchInSec(), 4);
      src.onended = () => {
        this.zone.run(() => this.cdr.markForCheck());
        this._stopPunchPreview();
      };
      this._punchPreviewSrc = src;
      this.cdr.markForCheck();
    } catch { this._stopPunchPreview(); }
  }

  private _stopPunchPreview(): void {
    try { this._punchPreviewSrc?.stop(); } catch { /* ignore */ }
    this._punchPreviewSrc = null;
    this._punchPreviewCtx?.close();
    this._punchPreviewCtx = null;
  }

  async confirmPunchIn(): Promise<void> {
    const id = this.punchInTrackId();
    if (!id) return;
    this._stopPunchPreview();
    this.studioState.set('idle');
    // _beginCountdown lira punchInSec() et punchInTrackId() pour savoir qu'il s'agit d'un punch-in
    await this._beginCountdown(id);
  }

  // ── Beat preview (idle) ───────────────────────────────────────────────────────

  toggleBeatPreview(): void {
    if (this.beatIsPlaying()) {
      this.player.audioEl.pause();
      this.beatIsPlaying.set(false);
      this._stopBeatRaf();
    } else {
      this.player.audioEl.volume = this.beatVolume();
      this.player.audioEl.play().then(() => {
        this.beatIsPlaying.set(true);
        this._startBeatRaf();
        this.cdr.markForCheck();
      }).catch(() => {});
    }
    this.cdr.markForCheck();
  }

  onBeatWaveformClick(event: MouseEvent): void {
    const canvas = this.beatWaveCanvasRef?.nativeElement;
    if (!canvas || !this.beatWaveReady()) return;
    const rect    = canvas.getBoundingClientRect();
    const frac    = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const dur     = isFinite(this.player.audioEl.duration) ? this.player.audioEl.duration : this.beatDuration();
    if (dur <= 0) return;
    this.player.audioEl.currentTime = frac * dur;
    this.beatCurrentTime.set(frac * dur);
    if (!this.beatIsPlaying()) {
      this.player.audioEl.volume = this.beatVolume();
      this.player.audioEl.play().then(() => {
        this.beatIsPlaying.set(true);
        this._startBeatRaf();
        this.cdr.markForCheck();
      }).catch(() => {});
    }
  }

  onVocalWaveformSeek(track: VocalTrack, frac: number): void {
    const beatTime  = frac * track.duration + track.beatStartSec;
    const dur       = isFinite(this.player.audioEl.duration) ? this.player.audioEl.duration : this.beatDuration();
    const clamped   = Math.max(0, Math.min(beatTime, dur > 0 ? dur : beatTime));
    this.player.audioEl.currentTime = clamped;
    this.beatCurrentTime.set(clamped);
    if (!this.beatIsPlaying()) {
      this.player.audioEl.volume = this.beatVolume();
      this.player.audioEl.play().then(() => {
        this.beatIsPlaying.set(true);
        this._startBeatRaf();
        this.cdr.markForCheck();
      }).catch(() => {});
    }
  }

  trackPlayheadPct(track: VocalTrack): number | null {
    if (!track.rawBlob || track.duration <= 0) return null;
    const t = this.beatCurrentTime() - track.beatStartSec;
    if (t < 0 || t > track.duration) return null;
    return t / track.duration;
  }

  fmtBeatTime(s: number): string {
    const m   = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${String(sec).padStart(2, '0')}`;
  }

  onBeatVolumeInput(event: Event): void {
    const v = +(event.target as HTMLInputElement).value;
    this.beatVolume.set(v);
    this.player.audioEl.volume = v;
  }

  /**
   * Télécharge le preview de l'instrumentale en une seule requête au démarrage
   * du studio. Une fois le blob disponible :
   * - l'audioEl est basculé vers une URL locale (blob://), indépendante du réseau
   * - le blob est réutilisé pour quickMix et exportMaquette, évitant un 2ème fetch
   *
   * Si le téléchargement échoue ou prend trop de temps, le streaming HTTP de secours
   * déjà positionné dans ngOnInit reste actif.
   */
  private _prefetchBeat(): void {
    fetch(this.beatStreamUrl)
      .then(r => {
        if (!r.ok) throw new Error(`${r.status}`);
        return r.blob();
      })
      .then(blob => {
        const url = URL.createObjectURL(blob);
        if (this._beatBlobUrl) URL.revokeObjectURL(this._beatBlobUrl);
        this._beatBlobUrl = url;
        this._beatBlob.set(blob);
        this._decodeBeatWaveform(blob, true);

        // Hot-swap vers le blob local uniquement en idle (jamais pendant un enregistrement)
        if (this.studioState() === 'idle') {
          const wasPlaying = this.beatIsPlaying();
          this.player.audioEl.src = url;
          this.player.audioEl.load();
          if (wasPlaying) {
            this.player.audioEl.volume = this.beatVolume();
            this.player.audioEl.play().catch(() => {});
          }
        }
        this.cdr.markForCheck();
      })
      .catch(() => { /* streaming fallback déjà en place */ });
  }

  // ── Waveform du beat (canvas réel, décodé depuis le blob pré-fetché) ────────

  private async _decodeBeatWaveform(blob: Blob, clearHistory = false): Promise<void> {
    if (clearHistory) {
      this._revokeHistoryUrls();
      this._beatHistory = [];
      this._histLen.set(0);
      this.undoConfirmPending.set(false);
      this._extendedBeatBlobUrl.set(null);
    }
    try {
      const ab  = await blob.arrayBuffer();
      const ctx = new AudioContext();
      const buf = await ctx.decodeAudioData(ab);
      ctx.close();

      if (clearHistory) {
        this._originalBeatDuration = buf.duration;
        this.beatDuration.set(buf.duration);
      }

      // Mix stéréo → mono en moyennant les canaux
      const nCh  = buf.numberOfChannels;
      const len  = buf.length;
      const mono = new Float32Array(len);
      for (let c = 0; c < nCh; c++) {
        const ch = buf.getChannelData(c);
        for (let i = 0; i < len; i++) mono[i] += ch[i] / nCh;
      }

      // Downsample vers ~300 points en RMS
      const POINTS    = 300;
      const blockSize = Math.ceil(len / POINTS);
      const wf: number[] = [];
      for (let p = 0; p < POINTS; p++) {
        const start = p * blockSize;
        const end   = Math.min(start + blockSize, len);
        let rms = 0;
        for (let i = start; i < end; i++) rms += mono[i] * mono[i];
        wf.push(Math.sqrt(rms / Math.max(1, end - start)));
      }

      // Normalise vers [0, 1]
      const peak = Math.max(...wf, 0.001);
      this._beatWaveform = wf.map(v => v / peak);

      this.beatWaveReady.set(true);
      this.cdr.markForCheck();
      // Le signal force Angular à re-rendre le canvas avant de dessiner
      requestAnimationFrame(() => this._drawBeatWaveform());
    } catch { /* échec silencieux — le placeholder CSS reste visible */ }
  }

  private _drawBeatWaveform(): void {
    const canvas = this.beatWaveCanvasRef?.nativeElement;
    const wf     = this._beatWaveform;
    if (!canvas || !wf) return;

    const W = canvas.offsetWidth || 320;
    const H = 52;
    if (canvas.width !== W || canvas.height !== H) {
      canvas.width  = W;
      canvas.height = H;
    }

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, W, H);

    // ── Fonds des régions ajoutées ──────────────────────────────────────────────
    for (const r of this._beatHistory) {
      const xS = Math.round(r.startFrac * W);
      const xE = Math.min(W, Math.round((r.startFrac + r.lengthFrac) * W));
      if (xE > xS) {
        ctx.fillStyle = 'rgba(100,200,255,0.06)';
        ctx.fillRect(xS, 0, xE - xS, H);
        ctx.strokeStyle = 'rgba(100,200,255,0.35)';
        ctx.lineWidth   = 1;
        ctx.beginPath();
        ctx.moveTo(xS + 0.5, 0);
        ctx.lineTo(xS + 0.5, H);
        ctx.stroke();
      }
    }

    // ── Barres waveform bicolores ───────────────────────────────────────────────
    const barW = W / wf.length;
    for (let i = 0; i < wf.length; i++) {
      const barH    = Math.max(2, wf[i] * H * 0.88);
      const alpha   = 0.35 + wf[i] * 0.65;
      const frac    = (i + 0.5) / wf.length;
      const isAdded = this._beatHistory.some(r =>
        frac >= r.startFrac && frac < r.startFrac + r.lengthFrac
      );
      ctx.fillStyle = isAdded
        ? `rgba(100,200,255,${alpha.toFixed(2)})`   // bleu ciel — extension
        : `rgba(229,50,60,${alpha.toFixed(2)})`;    // rouge — original
      ctx.fillRect(i * barW + 0.5, (H - barH) / 2, Math.max(1, barW - 1), barH);
    }

    // ── Tête de lecture (playhead) ─────────────────────────────────────────────
    const dur = this.beatDuration();
    const cur = this.beatCurrentTime();
    if (dur > 0) {
      const x = Math.round((cur / dur) * W);
      ctx.save();
      ctx.shadowColor = 'rgba(0,0,0,0.55)';
      ctx.shadowBlur  = 4;
      ctx.strokeStyle = 'rgba(255,255,255,0.88)';
      ctx.lineWidth   = 1.5;
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, H);
      ctx.stroke();
      ctx.restore();
    }
  }

  // ── Monitoring autotune toggle ────────────────────────────────────────────────

  async toggleMonitorAutotune(): Promise<void> {
    if (this.monitorAutotune()) {
      this.monitorAutotune.set(false);
      this.cdr.markForCheck();
      return;
    }

    const hp = await this.pm.checkHeadphones().catch(() => ({ type: 'none' as HeadphoneType }));
    this.headphoneType.set(hp.type as HeadphoneType);

    if (hp.type === 'wired') {
      this.monitorAutotune.set(true);
    } else if (hp.type === 'bluetooth') {
      this.showCalibration.set(true);
    } else if (hp.type === 'bluetooth-a2dp') {
      this.errorMsg.set('Ce casque Bluetooth utilise le profil A2DP (lecture seule). Le monitoring nécessite un casque HFP/SCO ou des écouteurs filaires.');
    } else {
      this.errorMsg.set('Branchez des écouteurs filaires pour activer le monitoring.');
    }
    this.cdr.markForCheck();
  }

  // ── Calibration BT ───────────────────────────────────────────────────────────

  openCalibration(): void { this.showCalibration.set(true); this.cdr.markForCheck(); }

  onCalibrationDone(latencyMs: number): void {
    this.calibration.save(latencyMs, this.headphoneType() ?? 'none');
    this.showCalibration.set(false);
    this.errorMsg.set(null);
    this.cdr.markForCheck();
  }

  onCalibrationCancelled(): void { this.showCalibration.set(false); this.cdr.markForCheck(); }

  // ── Permission micro ──────────────────────────────────────────────────────────

  async requestMicPermission(): Promise<void> {
    const req = await this.pm.requestPermission().catch(() => ({ microphone: 'denied' as const }));
    this.permState.set(req.microphone as 'granted' | 'denied');
    this.cdr.markForCheck();
  }

  // ── Fermeture avec confirmation ────────────────────────────────────────────────

  _closeRequested(): void {
    const active = this.studioState();
    if (active !== 'idle' && active !== 'published') {
      this.confirmClose.set(true);
      this.cdr.markForCheck();
      return;
    }
    if (this.hasTrack()) {
      this.confirmClose.set(true);
      this.cdr.markForCheck();
      return;
    }
    this.closed.emit();
  }

  confirmCloseStudio(): void {
    this.confirmClose.set(false);
    this.closed.emit();
  }

  cancelClose(): void {
    this.confirmClose.set(false);
    this.cdr.markForCheck();
  }

  onPublishedClose(): void {
    this.closed.emit();
  }

  goToPremium(): void {
    this.showUpgradeSheet.set(false);
    window.location.href = '/premium';
  }

  // ── Enregistrement ────────────────────────────────────────────────────────────

  async addAndRecord(): Promise<void> {
    if (!this.service.canAddTrack()) return;
    const id = this.service.addTrack();
    await this._beginCountdown(id);
  }

  /** Uses the pre-created empty track from ngOnInit instead of creating a 2nd one. */
  async startFirstRecording(): Promise<void> {
    const emptyTrack = this.tracks().find(t => t.rawBlob === null && t.trackState === 'empty');
    if (emptyTrack) {
      await this._beginCountdown(emptyTrack.id);
    } else {
      await this.addAndRecord();
    }
  }

  async reRecord(id: string): Promise<void> {
    const t = this.tracks().find(v => v.id === id);
    if (t?.rawBlob) {
      this.confirmReRecordId.set(id);
      this.cdr.markForCheck();
    } else {
      await this._beginCountdown(id);
    }
  }

  async confirmReRecord(): Promise<void> {
    const id = this.confirmReRecordId();
    this.confirmReRecordId.set(null);
    if (id) await this._beginCountdown(id);
  }

  cancelReRecord(): void { this.confirmReRecordId.set(null); this.cdr.markForCheck(); }

  // ── Countdown 3-2-1 ──────────────────────────────────────────────────────────

  private async _beginCountdown(id: string): Promise<void> {
    this.errorMsg.set(null);

    if (this.beatIsPlaying()) { this.player.audioEl.pause(); this.beatIsPlaying.set(false); }

    if (!await this._ensurePermission()) return;

    const punchSec  = this.punchInSec();
    const btAheadMs = this._btAheadMs();

    this.player.audioEl.volume      = this.beatVolume();
    this.player.audioEl.currentTime = Math.max(0, punchSec);
    this.player.audioEl.play().catch(() => {});
    this._startBeatRaf();

    if (btAheadMs > 0) await this._runBtPrepare(btAheadMs);

    this.countdown.set(COUNTDOWN_START);
    this.studioState.set('countdown');
    this.cdr.markForCheck();

    await this._runCountdown();
    await this._startRecording(id);
  }

  /** Latence BT à compenser en ms (0 si filaire ou non calibré). */
  private _btAheadMs(): number {
    return (this.headphoneType() === 'bluetooth' && this.calibration.hasCalibration())
      ? this.calibration.latencyMs
      : 0;
  }

  private _runCountdown(): Promise<void> {
    return new Promise(resolve => {
      let n = COUNTDOWN_START;
      this._hapticTick();   // premier tic immédiat (affichage "3")
      this._countdownInterval = setInterval(() => {
        this.zone.run(() => {
          n--;
          if (n <= 0) {
            clearInterval(this._countdownInterval!);
            this._countdownInterval = null;
            this.countdown.set(null);
            this.cdr.markForCheck();
            resolve();
          } else {
            this._hapticTick();   // tics "2" et "1"
            this.countdown.set(n);
            this.cdr.markForCheck();
          }
        });
      }, 1000);
    });
  }

  private async _startRecording(id: string): Promise<void> {
    this._rmsHistory     = [];
    this._liveRmsBars    = [];
    this._warnedNearEnd  = false;
    this._isFinalizingRec = false;
    this.recordRms.set(0);
    this.recordTimer.set(0);
    this.nearEnd.set(false);
    this.detectedNote.set(null);
    this.correctionCents.set(0);
    this.activeRecordingId.set(id);
    this.service.setRecording(id);

    await this.pm.startSession({
      useMonitor:      this.monitorAutotune(),
      voiceGain:       this.micGain(),
      reverbWet:       0.0,
      trackKey:        this.track.key,
      monitorAutotune: this.monitorAutotune(),
      retuneSpeed:     this.retuneSpeed(),
    });

    this._levelHandle = await this.pm.addListener('level', ({ rms }) => {
      this._rmsHistory.push(rms);
      this._liveRmsBars.push(rms);
      if (this._liveRmsBars.length > LIVE_WAVE_POINTS) this._liveRmsBars.shift();
      this._drawLiveWaveform(this._liveRmsBars);
      this.zone.run(() => { this.recordRms.set(rms); this.cdr.markForCheck(); });
    });

    this._pitchHandle = await this.pm.addListener('pitch', ({ hz, correction }) => {
      this.zone.run(() => {
        this.detectedNote.set(this._noteFromHz(hz));
        this.correctionCents.set(Math.round(correction * 100));
        this.cdr.markForCheck();
      });
    });

    this._interruptedHandle = await this.pm.addListener('sessionInterrupted', (data) => {
      this.zone.run(() => this._handleInterrupted(data));
    });

    this._timerInterval = setInterval(() => {
      this.zone.run(() => {
        this.recordTimer.update(t => t + 1);
        const t = this.recordTimer();

        // Avertissement 15s avant la fin — haptic + indicateur visuel
        if (t >= MAX_REC_SECONDS - 15 && !this._warnedNearEnd) {
          this._warnedNearEnd = true;
          this.nearEnd.set(true);
          this._hapticTick();
        }

        this.cdr.markForCheck();
        if (t >= MAX_REC_SECONDS) this.stopRecording();
      });
    }, 1000);

    this._hapticImpact();
    this.studioState.set('recording');
    this.cdr.markForCheck();
  }

  // ── Waveform live ─────────────────────────────────────────────────────────────

  private _drawLiveWaveform(bars: number[]): void {
    const canvas = this.liveCanvasRef?.nativeElement;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W = canvas.width, H = canvas.height;
    const max = Math.max(...bars, 0.001);
    const barW = W / LIVE_WAVE_POINTS;
    ctx.clearRect(0, 0, W, H);
    for (let i = 0; i < bars.length; i++) {
      const norm  = bars[i] / max;
      const barH  = Math.max(2, norm * H * 0.88);
      const alpha = 0.35 + norm * 0.65;
      ctx.fillStyle = `rgba(229, 50, 60, ${alpha.toFixed(2)})`;
      ctx.fillRect(i * barW + 0.5, (H - barH) / 2, Math.max(1, barW - 1), barH);
    }
  }

  // ── Arrêt enregistrement ──────────────────────────────────────────────────────

  async stopRecording(): Promise<void> {
    if (this._isFinalizingRec) return;
    this._isFinalizingRec = true;
    this._hapticTick();
    this._stopRecordingListeners();
    this.player.audioEl.pause();

    try {
      const result = await this.pm.stopSession();
      await this.pm.removeAllListeners();
      await this._finalizeRecording(result);
    } catch (err) {
      console.error('[MobileStudio] stopRecording error', err);
      this._recoverFromError();
    }
  }

  /** Appelé par le plugin quand la session est interrompue côté natif (appel entrant, etc.). */
  private _handleInterrupted(data: InterruptedResult): void {
    if (this._isFinalizingRec) return;
    this._isFinalizingRec = true;
    this._stopRecordingListeners();
    this.player.audioEl.pause();
    this.pm.removeAllListeners().catch(() => {});
    this._finalizeRecording(data, true);
  }

  /** Libère les ressources d'une session d'enregistrement en cours. */
  private _stopRecordingListeners(): void {
    clearInterval(this._timerInterval!);    this._timerInterval     = null;
    this._levelHandle?.remove();            this._levelHandle       = null;
    this._pitchHandle?.remove();            this._pitchHandle       = null;
    this._interruptedHandle?.remove();      this._interruptedHandle = null;
    this.detectedNote.set(null);
    this.nearEnd.set(false);
    this._warnedNearEnd = false;
  }

  /**
   * Traitement commun d'une session terminée (normalement ou interrompue).
   * Décode le PCM, splice si punch-in, sauvegarde la piste, remet l'UI en idle.
   */
  private async _finalizeRecording(result: SessionResult, interrupted = false): Promise<void> {
    const id              = this.activeRecordingId()!;
    const punchSec        = this.punchInSec();
    const hadExistingTake = this.tracks().find(t => t.id === id)?.rawBlob != null;

    try {
      const raw   = Uint8Array.from(atob(result.pcmBase64), c => c.charCodeAt(0));
      // Le sample rate natif réel (44,1 kHz Android, variable iOS) est encodé dans le MIME
      // type — decodeBlob() s'en sert pour rééchantillonner vers le SR canonique du pipeline
      // au lieu de supposer 48 kHz à tort (cf. MobileAudioProcessorService.decodeBlob).
      const mime  = (result.format === 'float32' ? 'audio/pcm-f32' : 'audio/pcm-i16') + `;rate=${result.sampleRate}`;
      let rawBlob = new Blob([raw.buffer as ArrayBuffer], { type: mime });

      if (punchSec > 0) {
        const existing = this.tracks().find(t => t.id === id)?.rawBlob ?? null;
        if (existing) rawBlob = await this.processor.spliceAudio(existing, rawBlob, punchSec);
      }

      const duration      = punchSec + this.recordTimer();
      const waveform      = computeWaveform(this._rmsHistory, WAVEFORM_POINTS);
      const finalWaveform = punchSec > 0
        ? spliceWaveform(this.tracks().find(t => t.id === id)?.waveform ?? [], punchSec, duration, waveform, WAVEFORM_POINTS)
        : waveform;

      this.service.setRecorded(id, rawBlob, finalWaveform, duration);

      if (interrupted) {
        this.errorMsg.set('Enregistrement interrompu (appel entrant). La prise partielle a été conservée.');
        if (this._errorDismissTimer) clearTimeout(this._errorDismissTimer);
        this._errorDismissTimer = setTimeout(() => {
          this.errorMsg.set(null);
          this._errorDismissTimer = null;
          this.cdr.markForCheck();
        }, 8000);
      } else {
        this._hapticSuccess();
        if (hadExistingTake) {
          const trackName = this.tracks().find(t => t.id === id)?.name ?? 'Voix';
          this._showUndoToast(id, trackName);
        }
      }
    } catch (err) {
      console.error('[MobileStudio] _finalizeRecording error', err);
      if (!punchSec && !interrupted) this.service.removeTrack(id);
      this.errorMsg.set('Erreur lors de l\'enregistrement. Réessayez.');
    }

    this._resetRecordingState();
  }

  private _recoverFromError(): void {
    const id = this.activeRecordingId();
    if (id && !this.punchInSec()) this.service.removeTrack(id);
    this.errorMsg.set('Erreur lors de l\'enregistrement. Réessayez.');
    this._resetRecordingState();
  }

  private _resetRecordingState(): void {
    this.activeRecordingId.set(null);
    this.punchInTrackId.set(null);
    this.punchInSec.set(0);
    this.studioState.set('idle');
    this._isFinalizingRec = false;
    this.cdr.markForCheck();
  }

  // ── Aperçu du mix (preview rapide sans WSOLA) ────────────────────────────────

  /**
   * Preview instantanée : décode les PCM bruts + beat, mixe avec les volumes
   * uniquement (sans DSP ni autotune WSOLA). Typiquement < 1 s.
   * L'export final via exportAndPublish() applique la chaîne de traitement complète.
   */
  async previewMix(): Promise<void> {
    if (this.studioState() === 'previewing') return;
    this._stopPreviewPlayback();

    const activeTracks = this.service.tracks().filter(t => t.rawBlob !== null);
    if (activeTracks.length === 0) return;

    this.studioState.set('previewing');
    this.errorMsg.set(null);
    this.cdr.markForCheck();

    try {
      const buf = await this.processor.quickMix({
        vocals: activeTracks.map(t => ({
          blob:   (t.settings.useAutotune && t.processedBlob) ? t.processedBlob : t.rawBlob!,
          volume: t.settings.volume,
        })),
        beatStreamUrl: this.beatStreamUrl,
        beatGain:      0.355,
        accessToken:   this.auth.getToken() ?? '',
        beatBlob:      this.service.extendedBeatBlob() ?? this._beatBlob() ?? undefined,
      });
      this.studioState.set('idle');
      this.cdr.markForCheck();
      await this._playPreviewBuffer(buf);
    } catch {
      this._setError('Erreur lors de la prévisualisation.');
    }
  }

  stopPreview(): void {
    this._stopPreviewPlayback();
    this.isPlayingPreview.set(false);
    this.cdr.markForCheck();
  }

  private async _playPreviewBuffer(buf: AudioBuffer): Promise<void> {
    try {
      this._previewAudioCtx = new AudioContext();
      const src = this._previewAudioCtx.createBufferSource();
      src.buffer = buf;
      src.connect(this._previewAudioCtx.destination);
      src.onended = () => {
        this.zone.run(() => { this.isPlayingPreview.set(false); this.cdr.markForCheck(); });
        this._stopPreviewPlayback();
      };
      src.start(0);
      this._previewSource = src;
      this.isPlayingPreview.set(true);
      this.cdr.markForCheck();
    } catch { this.isPlayingPreview.set(false); }
  }

  // ── RAF playhead ─────────────────────────────────────────────────────────────

  private _startBeatRaf(): void {
    this._stopBeatRaf();
    const tick = () => {
      const el = this.player.audioEl;
      const t  = el.currentTime;
      const d  = isFinite(el.duration) ? el.duration : 0;
      this.beatCurrentTime.set(t);
      if (d > 0) this.beatDuration.set(d);
      this._drawBeatWaveform();
      this._rafId = (!el.paused && !el.ended)
        ? requestAnimationFrame(tick)
        : null;
    };
    this._rafId = requestAnimationFrame(tick);
  }

  private _stopBeatRaf(): void {
    if (this._rafId !== null) {
      cancelAnimationFrame(this._rafId);
      this._rafId = null;
    }
  }

  private _stopPreviewPlayback(): void {
    try { this._previewSource?.stop(); } catch { /* ignore */ }
    this._previewSource = null;
    this._previewAudioCtx?.close();
    this._previewAudioCtx = null;
  }

  // ── Export & Publication ──────────────────────────────────────────────────────

  async exportAndPublish(): Promise<void> {
    if (!this.auth.isLoggedIn()) {
      this.showGuestGate.set(true);
      this.cdr.markForCheck();
      return;
    }
    this._stopPreviewPlayback();
    this.studioState.set('exporting');
    this.errorMsg.set(null);
    this.cdr.markForCheck();

    const accessToken = this.auth.getToken() ?? '';

    try {
      const mp3 = await this.service.exportMaquette({
        beatStreamUrl: this.beatStreamUrl,
        beatGain:      0.355,
        accessToken,
        trackKey:      this.track.key,
        latencyHintMs: this.calibration.latencyMs,
        beatBlob:      this._beatBlob() ?? undefined,
      });

      // Sauvegarde locale avant l'upload — filet de sécurité si le réseau coupe.
      const label = this.track.title.replace(/\s+/g, '_').slice(0, 30);
      this.draftSave.saveMp3(mp3, label).then(() => {
        this.zone.run(() => {
          this.draftSaved.set(true);
          this.cdr.markForCheck();
          if (this._draftSavedTimer) clearTimeout(this._draftSavedTimer);
          this._draftSavedTimer = setTimeout(() => {
            this.draftSaved.set(false);
            this._draftSavedTimer = null;
            this.cdr.markForCheck();
          }, 4000);
        });
      }).catch(() => {});
      // Nettoyage des vieux brouillons (> 7 jours) en arrière-plan
      this.draftSave.pruneOld().catch(() => {});

      const fd = new FormData();
      fd.append('processed_file', mp3, 'maquette.mp3');
      fd.append('track_id', String(this.track.id));
      if (this.description) fd.append('description', this.description);

      const imageUrl = this.track.image_file
        ? `${environment.apiUrl}/db_assets/${this.track.image_file}` : null;
      this.statusSvc.openForUpload(this.track.id, this.track.title, imageUrl);

      this.toplineSvc.uploadProcessed(fd).subscribe({
        next: res => {
          if (res.success && res.data?.topline_id) {
            this._hapticSuccess();
            this.statusSvc.setDoneWithId(res.data.topline_id);
            this.publishedId.set(res.data.topline_id);
            this.studioState.set('published');
            this.cdr.markForCheck();
          } else {
            this.statusSvc.stopPolling();
            this._setError(res.feedback?.message ?? 'Erreur lors de l\'envoi.');
          }
          this.cdr.markForCheck();
        },
        error: () => {
          this.statusSvc.stopPolling();
          this._setError('Impossible de contacter le serveur.');
        },
      });

    } catch (err) {
      console.error('[MobileStudio] export error', err);
      this._setError('Erreur lors du traitement audio.');
    }
  }

  async exportLocal(): Promise<void> {
    this._stopPreviewPlayback();
    this.studioState.set('exporting');
    this.errorMsg.set(null);
    this.cdr.markForCheck();

    try {
      const mp3 = await this.service.exportMaquette({
        beatStreamUrl: this.beatStreamUrl,
        beatGain:      0.355,
        accessToken:   '',
        trackKey:      this.track.key,
        latencyHintMs: this.calibration.latencyMs,
        beatBlob:      this._beatBlob() ?? undefined,
      });

      const label = this.track.title.replace(/\s+/g, '_').slice(0, 30);
      const savedPath = await this.draftSave.saveMp3(mp3, label);

      if (!savedPath) {
        // Web fallback: trigger browser download
        const url = URL.createObjectURL(mp3);
        const a   = document.createElement('a');
        a.href     = url;
        a.download = `${label}_maquette.mp3`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      }

      this.draftSave.pruneOld().catch(() => {});
      this.studioState.set('idle');
      this.draftSaved.set(true);
      if (this._draftSavedTimer) clearTimeout(this._draftSavedTimer);
      this._draftSavedTimer = setTimeout(() => {
        this.draftSaved.set(false);
        this._draftSavedTimer = null;
        this.zone.run(() => this.cdr.markForCheck());
      }, 4000);
      this.cdr.markForCheck();

    } catch (err) {
      console.error('[MobileStudio] export local error', err);
      this._setError('Erreur lors du traitement audio.');
    }
  }

  goToLogin(): void {
    this.showGuestGate.set(false);
    this.closed.emit();
    this.router.navigate(['/auth/login']);
  }

  // ── Beat editor ───────────────────────────────────────────────────────────────

  openBeatEditor(): void {
    this.selectedLane.set(null);
    this._stopPreviewPlayback();
    this.studioState.set('beat-editor');
    this.cdr.markForCheck();
  }

  onSectionExtended(result: ExtendedBeatResult): void {
    const newUrl = URL.createObjectURL(result.blob);

    // Pousse dans l'historique (l'ancienne URL est conservée — nécessaire pour undo)
    this._beatHistory.push({
      blob:         result.blob,
      blobUrl:      newUrl,
      totalSamples: result.totalSamples,
      sampleRate:   result.sampleRate,
      startFrac:    result.addedStartSample  / result.totalSamples,
      lengthFrac:   result.addedLengthSamples / result.totalSamples,
    });
    this._histLen.set(this._beatHistory.length);
    this.undoConfirmPending.set(false);

    // Met à jour la durée immédiatement
    this.beatDuration.set(result.totalSamples / result.sampleRate);

    // Enregistre le blob étendu pour le mix pipeline
    this.service.setExtendedBeat(result.blob);
    this._extendedBeatBlobUrl.set(newUrl);

    // Hot-swap l'audioEl vers le beat étendu
    const wasPlaying = this.beatIsPlaying();
    this._stopBeatRaf();
    this.player.audioEl.pause();
    this.player.audioEl.src = newUrl;
    this.player.audioEl.loop = true;
    this.player.audioEl.load();
    // Confirme beatDuration depuis le vrai audioEl une fois les métadonnées chargées
    const onMeta = () => {
      const d = this.player.audioEl.duration;
      if (isFinite(d) && d > 0) { this.beatDuration.set(d); this.cdr.markForCheck(); }
      this.player.audioEl.removeEventListener('loadedmetadata', onMeta);
    };
    this.player.audioEl.addEventListener('loadedmetadata', onMeta);
    if (wasPlaying) {
      this.player.audioEl.play().then(() => {
        this.beatIsPlaying.set(true);
        this._startBeatRaf();
        this.cdr.markForCheck();
      }).catch(() => {});
    }

    this._decodeBeatWaveform(result.blob, false);
    this.studioState.set('idle');
    this.cdr.markForCheck();
  }

  onBeatEditorCancelled(): void { this.studioState.set('idle'); this.cdr.markForCheck(); }

  requestUndoLastExtend(): void {
    if (!this.canUndoExtend()) return;
    if (this.undoWouldCutTopline().length > 0) {
      this.undoConfirmPending.set(true);
      this.cdr.markForCheck();
    } else {
      this._applyUndoLastExtend();
    }
  }

  confirmUndoExtend(): void {
    this.undoConfirmPending.set(false);
    this._applyUndoLastExtend();
  }

  cancelUndoExtend(): void {
    this.undoConfirmPending.set(false);
    this.cdr.markForCheck();
  }

  private _applyUndoLastExtend(): void {
    const popped = this._beatHistory.pop();
    if (!popped) return;
    URL.revokeObjectURL(popped.blobUrl);
    this._histLen.set(this._beatHistory.length);

    const prev = this._beatHistory.at(-1);
    if (prev) {
      // Retour à l'extension précédente
      this.beatDuration.set(prev.totalSamples / prev.sampleRate);
      this.service.setExtendedBeat(prev.blob);
      this._extendedBeatBlobUrl.set(prev.blobUrl);
      const wasPlaying = this.beatIsPlaying();
      this._stopBeatRaf();
      this.player.audioEl.pause();
      this.player.audioEl.src = prev.blobUrl;
      this.player.audioEl.loop = true;
      this.player.audioEl.load();
      const onMetaPrev = () => {
        const d = this.player.audioEl.duration;
        if (isFinite(d) && d > 0) { this.beatDuration.set(d); this.cdr.markForCheck(); }
        this.player.audioEl.removeEventListener('loadedmetadata', onMetaPrev);
      };
      this.player.audioEl.addEventListener('loadedmetadata', onMetaPrev);
      if (wasPlaying) {
        this.player.audioEl.play().then(() => {
          this.beatIsPlaying.set(true);
          this._startBeatRaf();
          this.cdr.markForCheck();
        }).catch(() => {});
      }
      this._decodeBeatWaveform(prev.blob, false);
    } else {
      // Retour au beat original
      this.beatDuration.set(this._originalBeatDuration);
      this.service.clearExtendedBeat();
      this._extendedBeatBlobUrl.set(null);
      const originalUrl = this._beatBlobUrl ?? this.beatStreamUrl;
      const wasPlaying  = this.beatIsPlaying();
      this._stopBeatRaf();
      this.player.audioEl.pause();
      this.player.audioEl.src = originalUrl ?? '';
      this.player.audioEl.loop = true;
      this.player.audioEl.load();
      const onMetaOrig = () => {
        const d = this.player.audioEl.duration;
        if (isFinite(d) && d > 0) { this.beatDuration.set(d); this.cdr.markForCheck(); }
        this.player.audioEl.removeEventListener('loadedmetadata', onMetaOrig);
      };
      this.player.audioEl.addEventListener('loadedmetadata', onMetaOrig);
      if (wasPlaying) {
        this.player.audioEl.play().then(() => {
          this.beatIsPlaying.set(true);
          this._startBeatRaf();
          this.cdr.markForCheck();
        }).catch(() => {});
      }
      if (this._beatBlob()) {
        this._decodeBeatWaveform(this._beatBlob()!, false);
      } else {
        this._beatWaveform = null;
        this.beatWaveReady.set(false);
      }
    }
    this.cdr.markForCheck();
  }

  private _revokeHistoryUrls(): void {
    for (const e of this._beatHistory) URL.revokeObjectURL(e.blobUrl);
  }

  // ── DAW lane interaction ──────────────────────────────────────────────────────

  selectLane(lane: 'beat'): void {
    this.selectedLane.set(this.selectedLane() === lane ? null : lane);
    this.cdr.markForCheck();
  }

  toggleMonitoring(): void {
    this.showMonitoring.update(v => !v);
    this.cdr.markForCheck();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  private async _ensurePermission(): Promise<boolean> {
    if (this.permState() === 'granted') return true;

    const perm = await this.pm.checkPermission().catch(() => ({ microphone: 'granted' as const }));
    this.permState.set(perm.microphone);
    this.cdr.markForCheck();
    if (perm.microphone === 'granted') return true;

    if (perm.microphone === 'denied') {
      this._setError('Microphone refusé — activez-le dans Réglages › LaProd.');
      return false;
    }

    const req = await this.pm.requestPermission().catch(() => ({ microphone: 'denied' as const }));
    this.permState.set(req.microphone as 'granted' | 'denied');
    this.cdr.markForCheck();
    if (req.microphone !== 'granted') {
      this._setError('Microphone refusé — activez-le dans les réglages système.');
      return false;
    }
    return true;
  }

  private _runBtPrepare(ms: number): Promise<void> {
    const steps = Math.max(1, Math.ceil(ms / 1000));
    this.btCountdown.set(steps);
    this.btPreparing.set(true);
    this.cdr.markForCheck();

    return new Promise(resolve => {
      this._btCountdownInterval = setInterval(() => {
        const next = this.btCountdown() - 1;
        this.btCountdown.set(next);
        this.cdr.markForCheck();
        if (next <= 0) {
          clearInterval(this._btCountdownInterval!);
          this._btCountdownInterval = null;
          this.btPreparing.set(false);
          resolve();
        }
      }, 1000);
    });
  }

  private _setError(msg: string): void {
    if (this._errorDismissTimer) {
      clearTimeout(this._errorDismissTimer);
      this._errorDismissTimer = null;
    }
    this.errorMsg.set(msg);
    this.studioState.set('idle');
    this.cdr.markForCheck();
    this._errorDismissTimer = setTimeout(() => {
      this.errorMsg.set(null);
      this._errorDismissTimer = null;
      this.cdr.markForCheck();
    }, 5000);
  }


  /** Convertit Hz en nom de note (ex. 440 → 'A4'). */
  private _noteFromHz(hz: number): string {
    const midi   = Math.round(69 + 12 * Math.log2(hz / 440));
    const octave = Math.floor(midi / 12) - 1;
    return NOTE_NAMES[((midi % 12) + 12) % 12] + octave;
  }

  /** Retourne l'ensemble des indices chromatiques [0–11] appartenant à la gamme. */
  private _buildScaleNotes(key: string): Set<number> {
    const match = key.match(/^([A-G][#b]?)\s*(major|minor|maj|min)?/i);
    if (!match) return new Set();
    const root      = NOTE_CHROMA[match[1]] ?? 0;
    const isMinor   = /min/i.test(match[2] ?? '');
    const intervals = isMinor ? MINOR_INTERVALS : MAJOR_INTERVALS;
    return new Set(intervals.map(i => (root + i) % 12));
  }

  // ── Undo toast ────────────────────────────────────────────────────────────────

  private _showUndoToast(trackId: string, trackName: string): void {
    if (this._undoToastTimer) clearTimeout(this._undoToastTimer);
    this.undoToast.set({ trackId, trackName });
    this.cdr.markForCheck();
    this._undoToastTimer = setTimeout(() => {
      this.undoToast.set(null);
      this._undoToastTimer = null;
      this.cdr.markForCheck();
    }, 6000);
  }

  dismissUndoToast(): void {
    if (this._undoToastTimer) clearTimeout(this._undoToastTimer);
    this._undoToastTimer = null;
    this.undoToast.set(null);
    this.cdr.markForCheck();
  }

  applyUndo(): void {
    const toast = this.undoToast();
    if (!toast) return;
    this.service.undoLastTake(toast.trackId);
    this.dismissUndoToast();
    this._hapticImpact();
  }

  // ── Métronome ─────────────────────────────────────────────────────────────────

  toggleMetronome(): void {
    this.metronome.toggle(this.track.bpm, this.player.audioEl.currentTime);
    this.cdr.markForCheck();
  }

  // ── Haptics ───────────────────────────────────────────────────────────────────

  private _hapticTick():    void { Haptics.impact({ style: ImpactStyle.Light  }).catch(() => {}); }
  private _hapticImpact():  void { Haptics.impact({ style: ImpactStyle.Medium }).catch(() => {}); }
  private _hapticSuccess(): void { Haptics.notification({ type: NotificationType.Success }).catch(() => {}); }

  // ── Destroy ───────────────────────────────────────────────────────────────────

  ngOnDestroy(): void {
    this.player.studioOpen.set(false);
    this._stopBeatRaf();
    if (this._beatBlobUrl) { URL.revokeObjectURL(this._beatBlobUrl); this._beatBlobUrl = null; }
    this._revokeHistoryUrls();
    this._popBackHandler?.(); this._popBackHandler = null;
    this._appStateHandle?.remove(); this._appStateHandle = null;
    clearInterval(this._timerInterval!);
    clearInterval(this._countdownInterval!);
    this._levelHandle?.remove();
    this._pitchHandle?.remove();
    this._interruptedHandle?.remove();
    this._stopPreviewPlayback();
    this._stopPunchPreview();
    this.metronome.stop();
    if (this._undoToastTimer)      clearTimeout(this._undoToastTimer);
    if (this._draftSavedTimer)     clearTimeout(this._draftSavedTimer);
    if (this._errorDismissTimer)   clearTimeout(this._errorDismissTimer);
    if (this._btCountdownInterval) clearInterval(this._btCountdownInterval);
    if (this.beatIsPlaying()) this.player.audioEl.pause();
    this.pm.removeAllListeners().catch(() => {});
    this.player.audioEl.loop = false;
    this.player.audioEl.pause();
    this.service.reset();
  }
}
