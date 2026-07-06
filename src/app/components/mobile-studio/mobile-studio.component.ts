import {
  Component, Input, Output, EventEmitter, OnInit, OnDestroy,
  ChangeDetectionStrategy, ChangeDetectorRef, signal, computed, inject,
  NgZone, ViewChild, ElementRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule }  from '@angular/forms';
import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';
import { App } from '@capacitor/app';
import type { PluginListenerHandle } from '@capacitor/core';

import { TrackDetail }              from '../../services/track.service';
import { ToplineService }           from '../../services/topline.service';
import { ToplineStatusService }     from '../../services/topline-status.service';
import { PlayerService }            from '../../services/player.service';
import { AuthService }              from '../../services/auth.service';
import { MobileMaquetteService }       from '../../services/mobile-maquette.service';
import { MobileAudioProcessorService } from '../../services/mobile-audio-processor.service';
import { LatencyCalibrationService }   from '../../services/latency-calibration.service';
import { DraftSaveService }            from '../../services/draft-save.service';
import { NativeShellService }          from '../../services/native-shell.service';
import { PITCH_MONITOR, InterruptedResult, PitchMonitorPlugin, SessionResult } from '../../services/pitch-monitor-plugin';
import { environment }              from '../../../environments/environment';
import { MobileTrackItemComponent }      from './mobile-track-item/mobile-track-item.component';
import { BeatSectionPickerComponent }    from '../beat-section-picker/beat-section-picker.component';
import { BluetoothCalibrationComponent } from '../bluetooth-calibration/bluetooth-calibration.component';

// ── Types ─────────────────────────────────────────────────────────────────────

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
})
export class MobileStudioComponent implements OnInit, OnDestroy {

  @Input({ required: true }) track!: TrackDetail;
  @Output() closed = new EventEmitter<void>();

  @ViewChild('liveCanvas') liveCanvasRef?: ElementRef<HTMLCanvasElement>;

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
  private toplineSvc   = inject(ToplineService);
  private statusSvc    = inject(ToplineStatusService);
  private player       = inject(PlayerService);
  private cdr          = inject(ChangeDetectorRef);
  private zone         = inject(NgZone);

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
  readonly metronomeOn = signal(false);

  // ── Écouteurs + monitoring ────────────────────────────────────────────────────

  headphoneType   = signal<HeadphoneType | null>(null);
  monitorAutotune = signal(false);
  retuneSpeed     = signal<'natural' | 'precise'>('natural');
  showCalibration = signal(false);

  // ── Beat preview (idle) ───────────────────────────────────────────────────────

  beatIsPlaying = signal(false);

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

  // ── Permission micro + état UI supplémentaires ────────────────────────────────

  permState        = signal<'granted' | 'prompt' | 'denied' | null>(null);
  confirmClose     = signal(false);
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
  private _metroCtx:           AudioContext | null                   = null;
  private _metroScheduler:     ReturnType<typeof setInterval> | null = null;
  private _nextNoteTime        = 0;
  private _metroBeatIdx        = 0;
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
          if (this.metronomeOn()) { this._stopMetronome(); this._startMetronome(); }
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
    } else {
      this.player.audioEl.volume = this.beatVolume();
      this.player.audioEl.play().then(() => {
        this.beatIsPlaying.set(true);
        this.cdr.markForCheck();
      }).catch(() => {});
    }
    this.cdr.markForCheck();
  }

  onBeatVolumeInput(event: Event): void {
    const v = +(event.target as HTMLInputElement).value;
    this.beatVolume.set(v);
    this.player.audioEl.volume = v;
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
      const waveform      = this._computeWaveform(this._rmsHistory, WAVEFORM_POINTS);
      const finalWaveform = punchSec > 0
        ? this._spliceWaveform(this.tracks().find(t => t.id === id)?.waveform ?? [], punchSec, duration, waveform)
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
        beatBlob:      this.service.extendedBeatBlob() ?? undefined,
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

  private _stopPreviewPlayback(): void {
    try { this._previewSource?.stop(); } catch { /* ignore */ }
    this._previewSource = null;
    this._previewAudioCtx?.close();
    this._previewAudioCtx = null;
  }

  // ── Export & Publication ──────────────────────────────────────────────────────

  async exportAndPublish(): Promise<void> {
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

  // ── Beat editor ───────────────────────────────────────────────────────────────

  openBeatEditor(): void {
    this._stopPreviewPlayback();
    this.studioState.set('beat-editor');
    this.cdr.markForCheck();
  }

  onSectionExtended(blob: Blob): void {
    this.service.setExtendedBeat(blob);
    this.studioState.set('idle');
    this.cdr.markForCheck();
  }

  onBeatEditorCancelled(): void { this.studioState.set('idle'); this.cdr.markForCheck(); }

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

  private _computeWaveform(rms: number[], n: number): number[] {
    if (rms.length === 0) return Array(n).fill(0.1);
    const step   = rms.length / n;
    const result = Array.from({ length: n }, (_, i) => {
      const s = rms.slice(Math.floor(i * step), Math.floor((i + 1) * step));
      return s.length > 0 ? Math.max(...s) : 0;
    });
    const max = Math.max(...result, 0.001);
    return result.map(v => v / max);
  }

  /**
   * Fusionne le waveform de la partie conservée (avant punch-in) avec celui de
   * la nouvelle prise, proportionnellement à leur durée.
   */
  private _spliceWaveform(
    existing: number[], fromSec: number, totalSec: number, newWf: number[],
  ): number[] {
    if (!existing.length) return newWf;
    const ratio     = Math.min(1, fromSec / totalSec);
    const keepN     = Math.round(WAVEFORM_POINTS * ratio);
    const newN      = WAVEFORM_POINTS - keepN;
    const keepSlice = existing.slice(0, keepN);
    const newSlice  = this._resample(newWf, newN);
    return [...keepSlice, ...newSlice];
  }

  private _resample(wf: number[], targetLen: number): number[] {
    if (targetLen <= 0) return [];
    if (wf.length === targetLen) return wf;
    return Array.from({ length: targetLen }, (_, i) => {
      const src = (i / targetLen) * wf.length;
      return wf[Math.floor(src)] ?? 0;
    });
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
    if (this.metronomeOn()) { this._stopMetronome(); } else { this._startMetronome(); }
  }

  private _startMetronome(): void {
    if (!this.track?.bpm) return;
    this._metroCtx = new AudioContext();
    const beatInterval  = 60 / this.track.bpm;
    const audioPos      = this.player.audioEl.currentTime;
    const phase         = audioPos % beatInterval;
    this._nextNoteTime  = this._metroCtx.currentTime + (beatInterval - phase);
    this._metroBeatIdx  = 0;
    // Lookahead scheduler : planifie les clics 150 ms en avance toutes les 50 ms
    this._metroScheduler = setInterval(() => this._scheduleMetro(), 50);
    this.metronomeOn.set(true);
    this.cdr.markForCheck();
  }

  private _scheduleMetro(): void {
    const ctx = this._metroCtx;
    if (!ctx) return;
    const beatInterval = 60 / this.track.bpm;
    const lookahead    = 0.15; // 150 ms d'avance
    while (this._nextNoteTime < ctx.currentTime + lookahead) {
      this._scheduleClick(this._nextNoteTime, this._metroBeatIdx === 0);
      this._nextNoteTime  += beatInterval;
      this._metroBeatIdx   = (this._metroBeatIdx + 1) % 4;
    }
  }

  private _scheduleClick(when: number, accent: boolean): void {
    const ctx = this._metroCtx;
    if (!ctx) return;
    const osc  = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'triangle';
    osc.frequency.value = accent ? 1320 : 880;
    gain.gain.setValueAtTime(accent ? 0.4 : 0.25, when);
    gain.gain.exponentialRampToValueAtTime(0.001, when + 0.04);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(when);
    osc.stop(when + 0.05);
  }

  private _stopMetronome(): void {
    clearInterval(this._metroScheduler!);
    this._metroScheduler = null;
    this._metroCtx?.close();
    this._metroCtx = null;
    this.metronomeOn.set(false);
    this.cdr.markForCheck();
  }

  // ── Haptics ───────────────────────────────────────────────────────────────────

  private _hapticTick():    void { Haptics.impact({ style: ImpactStyle.Light  }).catch(() => {}); }
  private _hapticImpact():  void { Haptics.impact({ style: ImpactStyle.Medium }).catch(() => {}); }
  private _hapticSuccess(): void { Haptics.notification({ type: NotificationType.Success }).catch(() => {}); }

  // ── Destroy ───────────────────────────────────────────────────────────────────

  ngOnDestroy(): void {
    this._popBackHandler?.(); this._popBackHandler = null;
    this._appStateHandle?.remove(); this._appStateHandle = null;
    clearInterval(this._timerInterval!);
    clearInterval(this._countdownInterval!);
    this._levelHandle?.remove();
    this._pitchHandle?.remove();
    this._interruptedHandle?.remove();
    this._stopPreviewPlayback();
    this._stopPunchPreview();
    this._stopMetronome();
    if (this._undoToastTimer)      clearTimeout(this._undoToastTimer);
    if (this._draftSavedTimer)     clearTimeout(this._draftSavedTimer);
    if (this._errorDismissTimer)   clearTimeout(this._errorDismissTimer);
    if (this._btCountdownInterval) clearInterval(this._btCountdownInterval);
    if (this.beatIsPlaying()) this.player.audioEl.pause();
    this.pm.removeAllListeners().catch(() => {});
    this.player.audioEl.pause();
    this.service.reset();
  }
}
