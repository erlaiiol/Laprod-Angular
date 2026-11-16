import {
  Component, Input, Output, EventEmitter, OnInit, OnDestroy,
  ChangeDetectionStrategy, ChangeDetectorRef, signal, computed, inject,
  NgZone, ViewChild, ElementRef, effect, untracked,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule }  from '@angular/forms';
import { Router }       from '@angular/router';
import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';
import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { Filesystem, Directory } from '@capacitor/filesystem';
import type { PluginListenerHandle } from '@capacitor/core';

import { TrackDetail }              from '../../services/track.service';
import { ToplineService }           from '../../services/topline.service';
import { ToplineStatusService }     from '../../services/topline-status.service';
import { PlayerService }            from '../../services/player.service';
import { AuthService }              from '../../services/auth.service';
import { MobileMaquetteService, VocalTrack } from '../../services/mobile-maquette.service';
import { MobileAudioProcessorService, LiveVoiceChain, PreviewQuality } from '../../services/mobile-audio-processor.service';
import { LatencyCalibrationService }   from '../../services/latency-calibration.service';
import { DraftSaveService, DraftEntry } from '../../services/draft-save.service';
import { NativeShellService }          from '../../services/native-shell.service';
import { PITCH_MONITOR, InterruptedResult, PitchMonitorPlugin, SessionResult, StartSessionInfo, VoiceFx } from '../../services/pitch-monitor-plugin';
import { environment }              from '../../../environments/environment';
import { MobileTrackItemComponent }      from './mobile-track-item/mobile-track-item.component';
import { BeatSectionPickerComponent }    from '../beat-section-picker/beat-section-picker.component';
import { ExtendedBeatResult }           from '../../services/beat-extender.service';
import { BluetoothCalibrationComponent } from '../bluetooth-calibration/bluetooth-calibration.component';
import { MobileStudioWarmupComponent }   from './mobile-studio-warmup/mobile-studio-warmup.component';
import { MobileStudioPunchinComponent }  from './mobile-studio-punchin/mobile-studio-punchin.component';
import { MobileStudioConfirmDialogComponent } from './mobile-studio-confirm-dialog/mobile-studio-confirm-dialog.component';
import { DawWaveformComponent } from './daw-waveform/daw-waveform.component';
import { DawGuestGateOverlayComponent } from './daw-guest-gate-overlay/daw-guest-gate-overlay.component';
import { MobileMetronomeService }        from '../../services/mobile-metronome.service';
import { computeWaveform, spliceWaveform, formatTimer } from '../../utils/waveform.utils';

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

// Plafond unifié web/mobile (config.TOPLINE_MAX_DURATION, backend) — pas de
// rôle anti-piratage ici (cf. beatStreamUrl), juste la durée max d'une prise.
const MAX_REC_SECONDS  = 150;
const WAVEFORM_POINTS  = 120;
const LIVE_WAVE_POINTS = 80;
const COUNTDOWN_START     = 3;
/** En dessous, la prise est considérée vide (arrêt immédiat, interruption). */
const MIN_TAKE_SECONDS    = 0.2;
const BT_CALIB_SHOWN_KEY  = 'laprod_bt_calib_v1';
const DEFAULT_BEAT_VOL = 0.65;
/** Gain du beat dans le mix exporté — la lecture du studio reprend la même balance. */
const MIX_BEAT_GAIN = 0.355;
/** Marge de planification (s) : toutes les sources partent au même instant d'horloge audio. */
const TRANSPORT_LEAD_SEC = 0.08;
/** Niveaux de zoom de la timeline (pixels par seconde). */
const ZOOM_LEVELS = [5, 8, 14, 24, 40] as const;
const PREVIEW_QUALITY_KEY = 'laprod_studio_preview_quality';
/** Après un geste sur la timeline, le suivi automatique de la tête de lecture attend (ms). */
const FOLLOW_RESUME_MS = 2500;

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

function isBluetooth(t: string | null | undefined): boolean {
  return t === 'bluetooth' || t === 'bluetooth-a2dp';
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    // "data:audio/mpeg;base64,<data>" → on ne garde que <data>
    reader.onload  = () => resolve((reader.result as string).split(',')[1] ?? '');
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// ── Composant ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-mobile-studio',
  standalone: true,
  imports: [
    CommonModule, FormsModule,
    MobileTrackItemComponent, BeatSectionPickerComponent,
    BluetoothCalibrationComponent,
    MobileStudioWarmupComponent, MobileStudioPunchinComponent,
    MobileStudioConfirmDialogComponent,
    DawWaveformComponent,
    DawGuestGateOverlayComponent,
  ],
  templateUrl: './mobile-studio.component.html',
  styleUrls: ['./mobile-studio-shared.scss', './mobile-studio.component.scss', './mobile-studio-timeline.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [MobileMetronomeService],
})
export class MobileStudioComponent implements OnInit, OnDestroy {

  @Input({ required: true }) track!: TrackDetail;
  @Output() closed = new EventEmitter<void>();

  @ViewChild('liveCanvas')     liveCanvasRef?:     ElementRef<HTMLCanvasElement>;
  @ViewChild('beatWaveCanvas') beatWaveCanvasRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('tlScroll')       tlScrollRef?:       ElementRef<HTMLElement>;
  @ViewChild('tlContent')      tlContentRef?:      ElementRef<HTMLElement>;

  readonly env       = environment;

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
  /** Le mix complet (instrumentale + toutes les voix) est en lecture. */
  isPlayingPreview  = signal(false);
  /** Décodage des pistes en cours avant le départ de la lecture. */
  transportLoading  = signal(false);
  description       = '';
  undoToast         = signal<{ trackId: string; trackName: string } | null>(null);
  get metronomeOn() { return this.metronome.active; }

  // ── Écouteurs + monitoring ────────────────────────────────────────────────────

  headphoneType   = signal<HeadphoneType | null>(null);
  /** "M'entendre chanter" — retour de la voix dans le casque (filaire ou Bluetooth). */
  monitorVoice    = signal(false);
  /** Autotune live sur ce retour (n'a d'effet que si monitorVoice). */
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

  draftSaved   = signal(false);  // brève confirmation après sauvegarde locale

  // ── DAW Studio ────────────────────────────────────────────────────────────────

  /** Piste sélectionnée dans la timeline : 'beat', l'id d'une voix, ou null. */
  selectedLane   = signal<string | null>(null);
  /** Feuille "Micro & monitoring" (barre d'outils du bas). */
  showMonitoring = signal(false);
  /** Feuille de publication (description + confirmation). */
  showPublishSheet = signal(false);

  // ── Timeline ──────────────────────────────────────────────────────────────────

  /** Échelle horizontale de la timeline. */
  pxPerSec = signal<number>(ZOOM_LEVELS[2]);
  readonly timelineWidth = computed(() => Math.max(1, this.beatDuration()) * this.pxPerSec());
  readonly playheadX     = computed(() => this.beatCurrentTime() * this.pxPerSec());
  readonly canZoomIn     = computed(() => this.pxPerSec() < ZOOM_LEVELS[ZOOM_LEVELS.length - 1]);
  readonly canZoomOut    = computed(() => this.pxPerSec() > ZOOM_LEVELS[0]);
  /** Graduations de la règle : pas choisi pour rester lisible au zoom courant. */
  readonly rulerMarks = computed(() => {
    const pps  = this.pxPerSec();
    const dur  = this.beatDuration();
    const step = [1, 2, 5, 10, 15, 30, 60].find(st => st * pps >= 56) ?? 60;
    const marks: Array<{ x: number; label: string }> = [];
    for (let t = 0; t <= dur; t += step) marks.push({ x: t * pps, label: this.fmtBeatTime(t) });
    return marks;
  });
  /** Piste vocale sélectionnée (null si aucune ou si c'est l'instrumentale). */
  readonly selectedTrack = computed(() =>
    this.tracks().find(t => t.id === this.selectedLane()) ?? null
  );

  // ── Qualité de l'écoute (charge processeur ↔ fidélité à l'export) ─────────────

  previewQuality = signal<PreviewQuality>(
    (() => { try { return localStorage.getItem(PREVIEW_QUALITY_KEY) === 'light' ? 'light' : 'full'; } catch { return 'full'; } })(),
  );

  // ── Permission micro + état UI supplémentaires ────────────────────────────────

  permState        = signal<'granted' | 'prompt' | 'denied' | null>(null);
  confirmClose     = signal(false);
  showGuestGate    = signal(false);
  /** Invité qui veut régler les effets d'une piste (seul le volume est libre sans compte). */
  showFxGate       = signal(false);
  publishedId      = signal<number | null>(null);
  showUpgradeSheet = signal(false);

  // ── Politique "1 session ouverte = 1 token" ─────────────────────────────────
  // (cf. routes/toplines_api.py: mobile-session/start, MobileStudioSession)
  showResumeDraftDialog = signal(false);
  showQuotaBlocked      = signal(false);
  quotaBlockedMessage   = signal('');

  // ── Punch-in ─────────────────────────────────────────────────────────────────

  punchInTrackId = signal<string | null>(null);
  punchInSec     = signal(0);

  // ── Computed ──────────────────────────────────────────────────────────────────

  readonly tracks   = this.service.tracks;
  readonly canAdd   = computed(() => this.service.canAddTrack());
  readonly hasTrack = computed(() => this.service.tracks().some(t => t.rawBlob !== null));
  /** Une piste vide attend sa prise : "Enregistrer" l'utilise au lieu d'en créer une autre. */
  readonly hasEmptyTrack = computed(() => this.service.tracks().some(t => t.rawBlob === null && t.trackState === 'empty'));
  readonly filledTrackCount = computed(() => this.service.tracks().filter(t => t.rawBlob !== null).length);

  readonly MAX_SECONDS  = MAX_REC_SECONDS;
  readonly levelPct     = computed(() => Math.min(100, this.recordRms() * 30_000));
  /** true si le niveau ajusté au gain dépasse 85% du max — risque de saturation. */
  readonly clipWarning  = computed(() => this.recordRms() * this.micGain() > 0.85);

  /** Piste vocale en cours de punch-in (null si aucune). */
  readonly punchInTrack = computed(() =>
    this.tracks().find(t => t.id === this.punchInTrackId()) ?? null
  );

  /** Label du gain micro en dB, ex. "+3.0 dB". */
  readonly micGainDb = computed(() => {
    const db = 20 * Math.log10(this.micGain());
    return (db >= 0 ? '+' : '') + db.toFixed(1) + ' dB';
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
  // ── Transport : lecture du mix complet ──────────────────────────────────────
  // Instrumentale et voix sont des sources du MÊME AudioContext, démarrées au même
  // instant d'horloge audio : chaque voix reste calée à l'échantillon près sur sa
  // position d'enregistrement (beatStartSec), quel que soit le point de départ.
  private _mixCtx:            AudioContext | null                   = null;
  /** Bus de sortie du contexte courant : limiteur de sécurité + réverb partagée. */
  private _mixBus: { ctx: AudioContext; master: AudioNode; reverb: AudioNode } | null = null;
  private _transport: {
    seq:          number;
    beatSrc:      AudioBufferSourceNode;
    beatGain:     GainNode;
    /** Une entrée par piste vocale du mix ; src est null si la piste est déjà passée. */
    voices:       Map<string, { blob: Blob; src: AudioBufferSourceNode | null; chain: LiveVoiceChain }>;
    quality:      PreviewQuality;
    startCtxTime: number;      // instant (horloge du contexte) du départ
    startPos:     number;      // position du beat (s) à cet instant
    duration:     number;      // durée de l'instrumentale (s)
  } | null = null;
  /** Invalide les démarrages asynchrones devenus obsolètes (seek/stop pendant un décodage). */
  private _transportSeq       = 0;
  private _beatBufCache:      { blob: Blob; buf: AudioBuffer } | null = null;
  private _vocalBufCache      = new WeakMap<Blob, AudioBuffer>();
  private _punchPreviewCtx:   AudioContext | null                   = null;
  private _punchPreviewSrc:   AudioBufferSourceNode | null          = null;
  private _undoToastTimer:     ReturnType<typeof setTimeout> | null  = null;
  private _draftSavedTimer:    ReturnType<typeof setTimeout> | null  = null;
  private _interruptedHandle:  { remove: () => void } | null         = null;
  private _isFinalizingRec     = false;  // garde contre double-stop (user + interruption)
  private _warnedNearEnd       = false;
  private _errorDismissTimer:   ReturnType<typeof setTimeout>  | null = null;
  private _popBackHandler:      (() => void) | null                  = null;
  private _appStateHandle:      PluginListenerHandle | null          = null;
  /** Session studio mobile en cours (token déjà consommé) — null tant qu'elle
   *  n'est pas ouverte (dialogue de reprise en attente, ou quota bloqué). */
  private _sessionId:           number | null                        = null;
  private _pendingDraft:        DraftEntry | null                    = null;

  // ── Beat natif (iOS) ─────────────────────────────────────────────────────────
  // Sur iOS, le beat est joué par le moteur audio natif pendant l'échauffement et
  // l'enregistrement (même horloge que le micro) : il ne peut plus être coupé par
  // l'activation de la session d'enregistrement, et la voix est alignée à
  // l'échantillon près. Ailleurs (Android), le beat reste sur l'<audio> partagé.
  private readonly _isIos = Capacitor.getPlatform() === 'ios';
  /** Résolu quand le téléchargement du beat est terminé (null en cas d'échec). */
  private _beatReady: Promise<Blob | null> = Promise.resolve(null);
  /** Fichier local du beat transmis au natif, mis en cache par blob. */
  private _nativeBeatFile: { blob: Blob; uri: string } | null = null;
  private _nativeBeatWrite: { blob: Blob; promise: Promise<string> } | null = null;
  /** Une session native (échauffement/enregistrement) est ouverte. */
  private _nativeSessionOpen = false;
  /** La calibration en cours a été ouverte par "M'entendre chanter". */
  private _enableMonitorAfterCalib = false;
  /** Horloge du beat natif pour la tête de lecture : position `sec` à `perf` ms. */
  private _nativeBeatClock: { perf: number; sec: number } | null = null;
  /** Infos d'alignement de la prise en cours. */
  private _take: {
    beatStartSec: number;      // position du beat au départ de la prise
    nativeBeat:   boolean;
    latencyMs:    number;      // latence casque à retirer du début de la voix
    leadSec:      number;      // Android : voix captée avant le départ du beat
  } | null = null;

  // ── Lifecycle ─────────────────────────────────────────────────────────────────

  async ngOnInit(): Promise<void> {
    // Hide navbar/player and stop any in-progress playback
    this.player.studioOpen.set(true);
    this.player.pause();
    // Le beat boucle en continu en studio (comportement DAW standard).
    // Posé avant load() pour que la propriété s'applique dès le premier cycle.
    this.player.audioEl.loop = true;
    // Pre-load the beat URL onto the shared audio element (Android recording and
    // warm-up play it from there) even if the track was never played before.
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
      if (this.showFxGate())            { this.showFxGate.set(false); this.cdr.markForCheck(); return true; }
      if (this.showPublishSheet())      { this.showPublishSheet.set(false); this.cdr.markForCheck(); return true; }
      if (this.showMonitoring())        { this.showMonitoring.set(false); this.cdr.markForCheck(); return true; }
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
        this._appActive = isActive;
        void this._syncLiveMonitor();   // micro coupé en arrière-plan, rouvert au retour
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
    if (isBluetooth(hp.type as HeadphoneType)
        && this._calibratedBtLatency() === null
        && !localStorage.getItem(BT_CALIB_SHOWN_KEY)) {
      localStorage.setItem(BT_CALIB_SHOWN_KEY, '1');
      this.showCalibration.set(true);
    }

    // Politique "1 session ouverte = 1 token" — uniquement pour un utilisateur
    // connecté (un guest garde l'accès libre existant, gate à la publication
    // seulement, cf. showGuestGate). Le studio reste utilisable pendant que
    // cette résolution se fait (métronome/monitoring non bloqués) ; seule la
    // publication/reprise dépend de _sessionId — cf. exportAndPublish().
    if (this.auth.isLoggedIn()) {
      void this._resolveStudioSession();
    }

    this.cdr.markForCheck();
  }

  // ── Session studio mobile (politique "1 session ouverte = 1 token") ────────────

  private async _resolveStudioSession(): Promise<void> {
    const drafts = await this.draftSave.listDraftsForTrack(this.track.id);
    if (drafts.length > 0) {
      this._pendingDraft = drafts[0];
      this.showResumeDraftDialog.set(true);
      this.cdr.markForCheck();
      return;
    }
    this._startFreshSessionId(
      sessionId => { this._sessionId = sessionId; this.cdr.markForCheck(); },
      message    => { this._blockOnQuota(message); this.cdr.markForCheck(); },
    );
  }

  /** Choix "Reprendre" du dialogue de reprise de brouillon. */
  async resumeDraft(): Promise<void> {
    this.showResumeDraftDialog.set(false);
    const draft = this._pendingDraft;
    if (!draft) return;

    this.studioState.set('exporting');
    this.cdr.markForCheck();

    try {
      const mp3 = await this.draftSave.readDraft(draft.path);
      this._resolveSessionIdForPublish(
        sessionId => this._submitProcessedMp3(mp3, sessionId),
        message    => {
          this._blockOnQuota(message);
          this.studioState.set('idle');
          this.cdr.markForCheck();
        },
      );
    } catch {
      this._setError('Impossible de lire le brouillon local.');
    }
  }

  /** Choix "Nouvelle session" du dialogue de reprise de brouillon — ignore le(s) brouillon(s) existant(s). */
  startFreshSession(): void {
    this.showResumeDraftDialog.set(false);
    this._pendingDraft = null;
    this._startFreshSessionId(
      sessionId => { this._sessionId = sessionId; this.cdr.markForCheck(); },
      message    => { this._blockOnQuota(message); this.cdr.markForCheck(); },
    );
  }

  /** Réutilise une session 'open' déjà existante pour cette track (reprise), sinon en ouvre une nouvelle. */
  private _resolveSessionIdForPublish(
    onReady: (sessionId: number) => void,
    onFail:  (message?: string) => void,
  ): void {
    this.toplineSvc.getOpenMobileSession(this.track.id).subscribe({
      next: res => {
        if (res.success && res.data?.session_id) { onReady(res.data.session_id); return; }
        this._startFreshSessionId(onReady, onFail);
      },
      error: () => this._startFreshSessionId(onReady, onFail),
    });
  }

  private _startFreshSessionId(
    onReady: (sessionId: number) => void,
    onFail:  (message?: string) => void,
  ): void {
    this.toplineSvc.startMobileSession(this.track.id).subscribe({
      next: res => {
        if (res.success && res.data) onReady(res.data.session_id);
        else onFail(res.feedback?.message);
      },
      error: (httpErr) => onFail(httpErr?.error?.feedback?.message),
    });
  }

  private _blockOnQuota(message?: string): void {
    this.quotaBlockedMessage.set(message ?? 'Plus de tokens de topline disponibles.');
    this.showQuotaBlocked.set(true);
  }

  // ── Getters template ──────────────────────────────────────────────────────────

  get beatStreamUrl(): string {
    // Fichier complet et propre (pas la preview watermarquée) — pour que
    // l'utilisateur entende le beat dans les meilleures conditions pendant
    // qu'il compose. La protection anti-vol se fait à l'export (watermark
    // injecté dans mixAndExport, cf. mobile-audio-processor.service.ts),
    // avant toute sortie possible (téléchargement local ou envoi serveur).
    return `${environment.apiUrl}/api/stream/tracks/${this.track.id}/full`;
  }

  formatTimer(s: number): string {
    return formatTimer(s);
  }

  // ── Warm-up ───────────────────────────────────────────────────────────────────

  async startWarmup(): Promise<void> {
    await this._claimSession(() => this._startWarmup());
  }

  private async _startWarmup(): Promise<void> {
    if (!await this._ensurePermission()) return;

    this._stopPreviewPlayback();
    if (this.beatIsPlaying()) { this.player.audioEl.pause(); this.beatIsPlaying.set(false); }
    this._stopBeatRaf();

    // iOS : le beat boucle dans le moteur natif (l'activation de la session micro
    // ne peut plus le couper). Sinon : <audio> partagé, comme avant.
    const beatPath = this._isIos ? await this._ensureNativeBeatFile().catch(() => null) : null;
    let info: StartSessionInfo | void;
    try {
      info = await this.pm.startSession({
        ...this._sessionOpts(),
        ...(beatPath ? { beatPath, beatStartSec: 0, beatVolume: this.beatVolume(), loopBeat: true } : {}),
      });
    } catch {
      this._setError('Impossible de démarrer le micro. Réessayez.');
      return;
    }
    this._nativeSessionOpen = true;

    if (!info?.nativeBeat) {
      this.player.audioEl.volume      = this.beatVolume();
      this.player.audioEl.currentTime = 0;
      this.player.audioEl.play().catch(() => {});
      this.beatIsPlaying.set(true);
    }

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
    this._nativeSessionOpen = false;
    await this.pm.stopSession().catch(() => {});
    await this.pm.removeAllListeners().catch(() => {});
    this.studioState.set('idle');
    this.cdr.markForCheck();
  }

  /** Options communes de session native (échauffement et enregistrement). */
  private _sessionOpts() {
    // Jamais de retour voix sur le haut-parleur : le micro le reprendrait (larsen).
    const monitor = this.monitorVoice() && this.headphoneType() !== 'none';
    return {
      useMonitor:      monitor,
      // Le gain micro n'agit que sur le retour casque : il est porté par fx.volume
      // pour pouvoir changer en direct (setVoiceFx), comme les autres réglages.
      voiceGain:       1.0,
      fx:              this.monitorFx(),
      reverbWet:       0.0,
      trackKey:        this.track.key,
      monitorAutotune: monitor && this.monitorAutotune(),
      retuneSpeed:     this.retuneSpeed(),
    };
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

  onPunchInSecChange(sec: number): void {
    this._stopPunchPreview();
    this.punchInSec.set(sec);
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

  // ── Transport (idle) : lecture du mix complet ─────────────────────────────────

  /** Bouton principal : lance tout le mix (instrumentale + voix) depuis 0:00. */
  playMixFromStart(): void { void this._playMixAt(0); }

  /** Arrête la lecture et ramène la tête de lecture au début. */
  stopMix(): void {
    this._stopPreviewPlayback();
    this.beatCurrentTime.set(0);
    this._drawBeatWaveform();
    this.cdr.markForCheck();
  }

  /** Pause / reprise à la position courante (bouton de la piste instrumentale). */
  toggleMixPlayback(): void {
    if (this.isPlayingPreview() || this.transportLoading()) {
      const pos = this._transport ? this._transportPos() : this.beatCurrentTime();
      this._stopPreviewPlayback();
      this.beatCurrentTime.set(pos);
      this._drawBeatWaveform();
      this.cdr.markForCheck();
    } else {
      void this._playMixAt(this.beatCurrentTime());
    }
  }

  // ── Timeline : sélection, clic dans une piste, tête de lecture ────────────────

  /** Position (s) sur l'instrumentale correspondant à une abscisse écran. */
  private _timeAtClientX(clientX: number): number {
    const content = this.tlContentRef?.nativeElement;
    if (!content) return 0;
    const sec = (clientX - content.getBoundingClientRect().left) / this.pxPerSec();
    return Math.max(0, Math.min(sec, this.beatDuration()));
  }

  /**
   * Toucher une piste (instrumentale ou voix) : la sélectionne pour ses réglages
   * et lance TOUT le mix à l'instant touché.
   */
  onLaneTap(event: MouseEvent, lane: string): void {
    this._selectLane(lane);
    if (this.beatDuration() <= 0) return;
    void this._playMixAt(this._timeAtClientX(event.clientX));
  }

  /** Toucher l'en-tête d'une piste : ouvre/ferme ses réglages sans toucher à la lecture. */
  selectLane(lane: string): void {
    if (this.selectedLane() === lane) this.selectedLane.set(null);
    else this._selectLane(lane);
    this.cdr.markForCheck();
  }

  private _selectLane(lane: string): void {
    this.selectedLane.set(lane);
    // Le retour casque reprend les réglages de la piste sélectionnée.
    if (lane !== 'beat') this.service.focusTrack(lane);
  }

  /** Glisser la tête de lecture (règle ou poignée). */
  private _scrub: { pointerId: number; wasPlaying: boolean } | null = null;

  onScrubStart(event: PointerEvent): void {
    if (this.studioState() !== 'idle' || this.beatDuration() <= 0) return;
    event.preventDefault();
    event.stopPropagation();
    (event.currentTarget as HTMLElement).setPointerCapture?.(event.pointerId);
    const wasPlaying = this.isPlayingPreview() || this.transportLoading();
    // Le son est coupé pendant le glissement ; le contexte audio reste ouvert pour repartir vite.
    this._transportSeq++;
    this._stopTransportSources();
    this._stopBeatRaf();
    this.transportLoading.set(false);
    this._scrub = { pointerId: event.pointerId, wasPlaying };
    this._lastTimelineTouch = performance.now();
    this.beatCurrentTime.set(this._timeAtClientX(event.clientX));
  }

  onScrubMove(event: PointerEvent): void {
    if (!this._scrub || event.pointerId !== this._scrub.pointerId) return;
    this.beatCurrentTime.set(this._timeAtClientX(event.clientX));
    // Près d'un bord : la timeline défile sous le doigt.
    const scroller = this.tlScrollRef?.nativeElement;
    if (scroller) {
      const r = scroller.getBoundingClientRect();
      if (event.clientX > r.right - 28)     scroller.scrollLeft += 14;
      else if (event.clientX < r.left + 28) scroller.scrollLeft -= 14;
    }
    this._lastTimelineTouch = performance.now();
  }

  /** Relâcher : si le mix jouait, il repart de la nouvelle position, voix recalées. */
  onScrubEnd(event: PointerEvent): void {
    const scrub = this._scrub;
    if (!scrub || event.pointerId !== scrub.pointerId) return;
    this._scrub = null;
    if (scrub.wasPlaying) {
      void this._playMixAt(this.beatCurrentTime());
    } else {
      this._stopPreviewPlayback();   // libère le contexte ; la position est conservée
      this.cdr.markForCheck();
    }
  }

  /** Un geste sur la timeline suspend le suivi automatique de la tête de lecture. */
  private _lastTimelineTouch = 0;
  onTimelineTouch(): void { this._lastTimelineTouch = performance.now(); }

  /** Pendant la lecture, la timeline défile pour garder la tête de lecture visible. */
  private _followPlayhead(): void {
    const scroller = this.tlScrollRef?.nativeElement;
    if (!scroller || performance.now() - this._lastTimelineTouch < FOLLOW_RESUME_MS) return;
    const x  = this.beatCurrentTime() * this.pxPerSec();
    const vw = scroller.clientWidth;
    if (x > scroller.scrollLeft + vw * 0.6)  scroller.scrollLeft = x - vw * 0.6;
    else if (x < scroller.scrollLeft)        scroller.scrollLeft = Math.max(0, x - vw * 0.2);
  }

  zoomIn():  void { this._zoom(+1); }
  zoomOut(): void { this._zoom(-1); }

  /** Change d'échelle en gardant la tête de lecture au même endroit de l'écran. */
  private _zoom(dir: 1 | -1): void {
    const i    = ZOOM_LEVELS.findIndex(z => z >= this.pxPerSec());
    const next = ZOOM_LEVELS[Math.max(0, Math.min(ZOOM_LEVELS.length - 1, (i < 0 ? 0 : i) + dir))];
    if (next === this.pxPerSec()) return;
    const scroller = this.tlScrollRef?.nativeElement;
    const offset   = scroller ? this.playheadX() - scroller.scrollLeft : 0;
    this.pxPerSec.set(next);
    this.cdr.markForCheck();
    requestAnimationFrame(() => {
      if (scroller) scroller.scrollLeft = Math.max(0, this.playheadX() - offset);
      this._drawBeatWaveform();
    });
  }

  setPreviewQuality(q: PreviewQuality): void {
    if (q === this.previewQuality()) return;
    this.previewQuality.set(q);
    try { localStorage.setItem(PREVIEW_QUALITY_KEY, q); } catch { /* stockage indisponible */ }
    // Lecture en cours : la chaîne est reconstruite à la position courante.
    if (this._transport) void this._playMixAt(this._transportPos());
    this.cdr.markForCheck();
  }

  /** Position courante (s, repère de l'instrumentale) de la lecture en cours. */
  private _transportPos(): number {
    const tr = this._transport;
    if (!tr || !this._mixCtx) return this.beatCurrentTime();
    const elapsed = Math.max(0, this._mixCtx.currentTime - tr.startCtxTime);
    return Math.min(tr.duration, tr.startPos + elapsed);
  }

  /** Blob réellement entendu pour une piste : version autotunée si active et calculée. */
  private _activeBlob(t: VocalTrack): Blob | null {
    return (t.settings.useAutotune && t.processedBlob) ? t.processedBlob : t.rawBlob;
  }

  private async _ensureBeatBuffer(): Promise<AudioBuffer> {
    let blob = this._currentBeatBlob() ?? await this._beatReady;
    if (!blob) {
      // Le téléchargement initial a échoué : nouvelle tentative à la demande.
      this._prefetchBeat();
      blob = await this._beatReady;
    }
    if (!blob) throw new Error('beat-unavailable');
    if (this._beatBufCache?.blob === blob) return this._beatBufCache.buf;
    const buf = await this.processor.decodeBlob(blob);
    this._beatBufCache = { blob, buf };
    return buf;
  }

  private async _ensureVocalBuffer(blob: Blob): Promise<AudioBuffer> {
    const cached = this._vocalBufCache.get(blob);
    if (cached) return cached;
    // Mono + noise gate : la même entrée que celle de la chaîne d'effets à l'export.
    const buf = await this.processor.decodeVoiceForPlayback(blob);
    this._vocalBufCache.set(blob, buf);
    return buf;
  }

  /**
   * Lance le mix complet à `sec` (repère de l'instrumentale). Toutes les pistes
   * vocales enregistrées sont incluses, quel que soit leur nombre, chacune à sa
   * position d'enregistrement :
   *   - voix déjà entamée à `sec`  → lue depuis (sec − beatStartSec) dans la piste ;
   *   - voix qui démarre plus tard → planifiée (beatStartSec − sec) secondes après ;
   *   - voix déjà terminée         → non jouée.
   * Chaque voix traverse sa chaîne d'effets en direct (coupe-bas, présence, clarté,
   * réverb, + compresseurs/de-esser/limiteur en qualité 'full') : les réglages
   * s'entendent pendant la lecture. Le retard propre de la chaîne est compensé,
   * la voix reste donc calée sur l'instrumentale. Balance identique à l'export.
   */
  private async _playMixAt(sec: number): Promise<void> {
    if (this.studioState() !== 'idle') return;
    const seq = ++this._transportSeq;
    this._stopTransportSources();
    this.errorMsg.set(null);

    // Contexte créé dans le geste utilisateur (avant tout await) — requis par iOS.
    const ctx = this._mixCtx ?? (this._mixCtx = this._newMixContext());
    const quality = this.previewQuality();
    const voiceTracks = this.tracks()
      .map(t => ({ t, blob: this._activeBlob(t) }))
      .filter((v): v is { t: VocalTrack; blob: Blob } => v.blob !== null);

    this.transportLoading.set(true);
    this.cdr.markForCheck();

    try {
      const [beatBuf, bus, chainDelay, ...voiceBufs] = await Promise.all([
        this._ensureBeatBuffer(),
        this._ensureMixBus(ctx),
        this.processor.vocalChainLatencySec(quality),
        ...voiceTracks.map(v => this._ensureVocalBuffer(v.blob)),
      ]);
      await ctx.resume().catch(() => {});
      // Un seek, un stop ou un changement d'écran est arrivé pendant le décodage.
      if (seq !== this._transportSeq) return;
      if (this._destroyed || this.studioState() !== 'idle' || this._mixCtx !== ctx) {
        this._stopPreviewPlayback();
        return;
      }

      const duration = beatBuf.duration;
      const pos      = sec >= duration - 0.05 || sec < 0 || !isFinite(sec) ? 0 : sec;

      const { master, reverb } = bus;

      const t0 = ctx.currentTime + TRANSPORT_LEAD_SEC;

      const beatSrc  = ctx.createBufferSource();
      const beatGain = ctx.createGain();
      beatSrc.buffer      = beatBuf;
      beatGain.gain.value = this._mixBeatGain();
      beatSrc.connect(beatGain).connect(master);
      // Fin naturelle de l'instrumentale : le mix reboucle depuis le début.
      beatSrc.onended = () => {
        if (this._transport?.seq !== seq) return;
        this.zone.run(() => { void this._playMixAt(0); });
      };
      beatSrc.start(t0, pos);

      const voices = new Map<string, { blob: Blob; src: AudioBufferSourceNode | null; chain: LiveVoiceChain }>();
      voiceTracks.forEach(({ t, blob }, i) => {
        const buf   = voiceBufs[i];
        const chain = this.processor.createLiveVoiceChain(ctx, t.settings, quality);
        chain.dry.connect(master);
        chain.wet.connect(reverb);
        // La chaîne retarde le son de chainDelay : la source part d'autant plus tôt.
        const into = pos - t.beatStartSec + chainDelay;   // > 0 : la voix a déjà commencé
        let src: AudioBufferSourceNode | null = null;
        if (into < buf.duration) {
          src = ctx.createBufferSource();
          src.buffer = buf;
          src.connect(chain.input);
          if (into >= 0) src.start(t0, into);
          else           src.start(t0 - into, 0);
        }
        voices.set(t.id, { blob, src, chain });
      });

      this._transport = { seq, beatSrc, beatGain, voices, quality, startCtxTime: t0, startPos: pos, duration };
      this.beatCurrentTime.set(pos);
      this.beatDuration.set(duration);
      this.isPlayingPreview.set(true);
      this.transportLoading.set(false);
      this._startBeatRaf();
      if (this.metronome.active()) this.metronome.restart(this.track.bpm, pos);
      this.cdr.markForCheck();
    } catch (err) {
      if (seq !== this._transportSeq) return;
      console.error('[MobileStudio] lecture du mix impossible', err);
      this._stopPreviewPlayback();
      this._setError('Lecture impossible — vérifiez votre connexion et réessayez.');
    }
  }

  /** 48 kHz comme le pipeline d'export (mêmes filtres, même réverb) ; défaut de l'appareil sinon. */
  private _newMixContext(): AudioContext {
    try { return new AudioContext({ sampleRate: 48_000 }); }
    catch { return new AudioContext(); }
  }

  private async _ensureMixBus(ctx: AudioContext) {
    if (this._mixBus?.ctx === ctx) return this._mixBus;
    // Limiteur de sécurité : la somme beat + voix ne doit pas saturer la sortie.
    const master = ctx.createDynamicsCompressor();
    master.threshold.value = -1;
    master.knee.value      = 0;
    master.ratio.value     = 20;
    master.attack.value    = 0.003;
    master.release.value   = 0.1;
    master.connect(ctx.destination);
    const reverb = await this.processor.createLiveReverb(ctx);
    reverb.connect(master);
    this._mixBus = { ctx, master, reverb };
    return this._mixBus;
  }

  /**
   * La piste instrumentale est recréée à chaque retour sur l'écran principal
   * (après une prise, un export…) : sa waveform est redessinée à ce moment-là.
   */
  private readonly _redrawBeatOnIdle = effect(() => {
    if (this.studioState() !== 'idle' || !this.beatWaveReady()) return;
    this.timelineWidth();
    requestAnimationFrame(() => this._drawBeatWaveform());
  });

  /** Gain d'écoute du beat : balance de l'export au réglage par défaut du curseur. */
  private _mixBeatGain(): number {
    return MIX_BEAT_GAIN * (this.beatVolume() / DEFAULT_BEAT_VOL);
  }

  /** Coupe les sources en cours sans fermer le contexte (réutilisé pour un seek). */
  private _stopTransportSources(): void {
    const tr = this._transport;
    if (!tr) return;
    this._transport = null;
    tr.beatSrc.onended = null;
    try { tr.beatSrc.stop(); } catch { /* jamais démarrée */ }
    tr.beatSrc.disconnect();
    tr.beatGain.disconnect();
    for (const v of tr.voices.values()) {
      try { v.src?.stop(); } catch { /* jamais démarrée */ }
      v.src?.disconnect();
      v.chain.dispose();
    }
  }

  /**
   * Suit les changements de pistes pendant la lecture : volume et effets
   * s'appliquent en direct, sans coupure ; une piste ajoutée, supprimée ou dont
   * l'audio change (nouvelle prise, autotune) relance le mix à la position courante.
   */
  private readonly _transportTrackSync = effect(() => {
    const tracks = this.tracks();
    untracked(() => {
      const tr = this._transport;
      if (!tr) return;
      const wanted = tracks
        .map(t => ({ t, blob: this._activeBlob(t) }))
        .filter(v => v.blob !== null);
      const same = wanted.length === tr.voices.size
        && wanted.every(v => tr.voices.get(v.t.id)?.blob === v.blob);
      if (!same) { void this._playMixAt(this._transportPos()); return; }
      for (const v of wanted) tr.voices.get(v.t.id)!.chain.update(v.t.settings);
    });
  });

  fmtBeatTime(s: number): string {
    const m   = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${String(sec).padStart(2, '0')}`;
  }

  onBeatVolumeInput(event: Event): void {
    const v = +(event.target as HTMLInputElement).value;
    this.beatVolume.set(v);
    this.player.audioEl.volume = v;
    if (this._transport) this._transport.beatGain.gain.value = this._mixBeatGain();
    if (this._isIos && this._nativeSessionOpen) this.pm.setBeatVolume({ volume: v }).catch(() => {});
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
    this._beatReady = fetch(this.beatStreamUrl)
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
        // iOS : prépare dès maintenant le fichier local lu par le moteur natif,
        // pour ne pas retarder le premier enregistrement.
        if (this._isIos) void this._ensureNativeBeatFile().catch(() => {});
        return blob as Blob | null;
      })
      .catch(() => null /* streaming fallback déjà en place */);
  }

  /** Beat courant : version étendue si le beat a été rallongé, sinon l'original. */
  private _currentBeatBlob(): Blob | null {
    return this.service.extendedBeatBlob() ?? this._beatBlob();
  }

  /**
   * iOS : écrit le beat courant dans le cache de l'app et renvoie son URI file://
   * (lue par AVAudioFile côté natif). null si le beat n'a pas pu être téléchargé.
   */
  private async _ensureNativeBeatFile(): Promise<string | null> {
    const blob = this._currentBeatBlob() ?? await this._beatReady;
    if (!blob) return null;
    if (this._nativeBeatFile?.blob === blob) return this._nativeBeatFile.uri;
    if (this._nativeBeatWrite?.blob === blob) return this._nativeBeatWrite.promise;

    const promise = this._writeNativeBeatFile(blob)
      .finally(() => { if (this._nativeBeatWrite?.promise === promise) this._nativeBeatWrite = null; });
    this._nativeBeatWrite = { blob, promise };
    return promise;
  }

  private async _writeNativeBeatFile(blob: Blob): Promise<string> {
    const ext  = /wav/i.test(blob.type) ? 'wav' : /mp4|m4a|aac/i.test(blob.type) ? 'm4a' : 'mp3';
    const path = `studio-beat-${Date.now()}.${ext}`;
    const data = await blobToBase64(blob);
    await Filesystem.writeFile({ path, data, directory: Directory.Cache });
    const { uri } = await Filesystem.getUri({ path, directory: Directory.Cache });

    const previous = this._nativeBeatFile;
    this._nativeBeatFile = { blob, uri };
    if (previous) {
      const oldPath = previous.uri.split('/').pop()!;
      Filesystem.deleteFile({ path: oldPath, directory: Directory.Cache }).catch(() => {});
    }
    return uri;
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

    // Résolution interne bornée (limites canvas mobiles) ; le CSS l'étire à la largeur de la piste.
    const W = Math.max(320, Math.min(4096, Math.round(this.timelineWidth())));
    const H = 44;
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

  }

  // ── Monitoring : "m'entendre chanter" + autotune live ─────────────────────────

  /** Active/désactive le retour de la voix dans le casque (filaire ou Bluetooth). */
  async toggleMonitorVoice(): Promise<void> {
    if (this.monitorVoice()) {
      this.monitorVoice.set(false);
      this.cdr.markForCheck();
      return;
    }

    const hp = await this.pm.checkHeadphones().catch(() => ({ type: 'none' as HeadphoneType }));
    this.headphoneType.set(hp.type as HeadphoneType);

    // Le retour permanent ouvre le micro : la permission doit être accordée.
    if (hp.type !== 'none' && !await this._ensurePermission()) return;

    if (hp.type === 'wired') {
      this.monitorVoice.set(true);
    } else if (isBluetooth(hp.type)) {
      // Bluetooth : le retour voix a la latence du casque (~150-250 ms). On le
      // permet (choix de l'utilisateur), après le réglage de latence au métronome
      // qui sert aussi à recaler la voix sur le beat.
      if (this._calibratedBtLatency() !== null) {
        this.monitorVoice.set(true);
      } else {
        this._enableMonitorAfterCalib = true;
        this.showCalibration.set(true);
      }
    } else {
      this.errorMsg.set('Branchez un casque (filaire ou Bluetooth) pour vous entendre chanter — sur le haut-parleur, le micro reprendrait votre voix.');
    }
    this.cdr.markForCheck();
  }

  /** Autotune live sur le retour voix — n'a de sens que si le retour est actif. */
  toggleMonitorAutotune(): void {
    if (!this.monitorVoice()) return;
    this.monitorAutotune.update(v => !v);
    this.cdr.markForCheck();
  }

  readonly isBluetoothHeadphone = computed(() => isBluetooth(this.headphoneType()));

  // ── Retour casque : réglages de piste entendus en direct ─────────────────────
  //
  // La chaîne voix du retour casque (boue, présence, clarté, réverb, volume) suit
  // la piste en cours d'enregistrement, sinon la dernière piste dépliée/réglée,
  // sinon la prochaine piste vide : tout changement de réglage est poussé au
  // natif (setVoiceFx) et s'entend immédiatement, sur iOS comme sur Android.

  /** Piste dont les réglages s'entendent dans le retour casque. */
  readonly monitoredTrack = computed((): VocalTrack | null => {
    const ts = this.tracks();
    const byId = (id: string | null) => (id ? ts.find(t => t.id === id) ?? null : null);
    return byId(this.activeRecordingId())
        ?? byId(this.service.focusedTrackId())
        ?? ts.find(t => t.rawBlob === null)
        ?? ts[0]
        ?? null;
  });

  readonly monitorFx = computed((): VoiceFx => {
    const st = this.monitoredTrack()?.settings;
    return {
      lowCutHz:   st?.lowCutHz   ?? 150,
      presenceDb: st?.presenceDb ?? 3.5,
      clarityDb:  st?.clarityDb  ?? 3.0,
      reverbWet:  st?.reverbWet  ?? 0.12,
      volume:     (st?.volume ?? 1) * this.micGain(),
    };
  });

  private readonly _pushFx = effect(() => {
    const fx = this.monitorFx();
    if (untracked(() => this.monitorVoice()) && this._nativeSessionOpen) {
      this.pm.setVoiceFx(fx).catch(() => {});
    }
  });

  /**
   * Micro ouvert en continu dans le studio (sans rien enregistrer) quand
   * "M'entendre chanter" est actif : on s'entend tout de suite, réglages compris.
   * Coupé pendant l'échauffement/l'enregistrement (qui ouvrent leur propre session)
   * et hors de l'écran principal du studio.
   */
  private readonly _liveMonitorSync = effect(() => {
    this.studioState(); this.monitorVoice(); this.headphoneType(); this.showCalibration();
    untracked(() => { void this._syncLiveMonitor(); });
  });

  private _liveMonitorOn = false;
  private _liveOp: Promise<void> = Promise.resolve();
  private _destroyed = false;
  private _sessionClaimed = false;
  private _appActive = true;

  private _wantsLiveMonitor(): boolean {
    return !this._destroyed
        && !this._sessionClaimed
        && this._appActive
        && this.monitorVoice()
        && this.headphoneType() !== null && this.headphoneType() !== 'none'
        && this.studioState() === 'idle'
        && !this.showCalibration()
        && this.permState() === 'granted';
  }

  /** Ouvre/ferme le retour casque permanent selon l'état courant (opérations sérialisées). */
  private _syncLiveMonitor(): Promise<void> {
    this._liveOp = this._liveOp.then(async () => {
      const want = this._wantsLiveMonitor();
      if (want && !this._nativeSessionOpen) {
        try {
          await this.pm.startSession({ ...this._sessionOpts(), record: false });
          this._nativeSessionOpen = true;
          this._liveMonitorOn     = true;
          // Réglages modifiés pendant l'ouverture : on renvoie l'état le plus récent.
          this.pm.setVoiceFx(this.monitorFx()).catch(() => {});
        } catch { /* micro occupé : on réessaiera au prochain changement d'état */ }
      } else if (!want && this._liveMonitorOn) {
        await this._closeLiveMonitor();
      }
    });
    return this._liveOp;
  }

  /**
   * Échauffement / prise : réserve le micro le temps du démarrage. Le retour permanent
   * est fermé d'abord et ne peut pas se rouvrir entre-temps (l'état reste 'idle'
   * pendant la demande de permission) — sinon la session de la prise serait refusée.
   */
  private async _claimSession(start: () => Promise<void>): Promise<void> {
    this._sessionClaimed = true;
    try {
      await this._stopLiveMonitor();
      await start();
    } finally {
      this._sessionClaimed = false;
      void this._syncLiveMonitor();   // démarrage avorté → retour permanent rouvert
    }
  }

  /** Ferme le retour casque permanent — à attendre avant d'ouvrir une autre session. */
  private _stopLiveMonitor(): Promise<void> {
    this._liveOp = this._liveOp.then(() => this._liveMonitorOn ? this._closeLiveMonitor() : undefined);
    return this._liveOp;
  }

  private async _closeLiveMonitor(): Promise<void> {
    this._liveMonitorOn     = false;
    this._nativeSessionOpen = false;
    await this.pm.stopSession().catch(() => {});
  }

  // ── Calibration BT (réglage de latence au métronome) ────────────────────────

  openCalibration(): void {
    this._enableMonitorAfterCalib = false;
    this.showCalibration.set(true);
    this.cdr.markForCheck();
  }

  onCalibrationDone(latencyMs: number): void {
    this.calibration.save(latencyMs, this.headphoneType() ?? 'none');
    this.showCalibration.set(false);
    this.errorMsg.set(null);
    // Calibration lancée depuis "M'entendre chanter" : on active le retour voix
    // (avec la latence du Bluetooth, signalée en continu dans les réglages).
    if (this._enableMonitorAfterCalib) this.monitorVoice.set(true);
    this._enableMonitorAfterCalib = false;
    this.cdr.markForCheck();
  }

  /** Latence Bluetooth mesurée au métronome (ms), null si jamais réglée en Bluetooth. */
  private _calibratedBtLatency(): number | null {
    const e = this.calibration.getEntry();
    return e && isBluetooth(e.deviceType) ? e.latencyMs : null;
  }

  onCalibrationCancelled(): void {
    this._enableMonitorAfterCalib = false;
    this.showCalibration.set(false);
    this.cdr.markForCheck();
  }

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

  /** Bouton "Enregistrer" de la barre d'outils : piste vide en attente, sinon nouvelle voix. */
  async onRecordPressed(): Promise<void> {
    const hasEmpty = this.tracks().some(t => t.rawBlob === null && t.trackState === 'empty');
    if (!hasEmpty && !this.service.canAddTrack()) {
      this.showUpgradeSheet.set(true);
      this.cdr.markForCheck();
      return;
    }
    await this.startFirstRecording();
  }

  /** Bouton "Publier" : invité → invitation à se connecter, sinon feuille de publication. */
  onPublishPressed(): void {
    if (!this.hasTrack()) return;
    if (!this.auth.isLoggedIn()) this.showGuestGate.set(true);
    else                         this.showPublishSheet.set(true);
    this.cdr.markForCheck();
  }

  async confirmPublish(): Promise<void> {
    this.showPublishSheet.set(false);
    await this.exportAndPublish();
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

  // ── Décompte 3-2-1 puis départ synchronisé beat + enregistrement ─────────────
  //
  // Le décompte est silencieux (chiffres + vibrations) ; à sa fin, le beat ET
  // l'enregistrement démarrent ensemble. La voix est ensuite posée sur le beat
  // exactement à la position où elle a été chantée (cf. _finalizeRecording).
  //
  // iOS : la session native est ouverte pendant le décompte et le beat est joué
  // par le moteur natif, programmé à une heure machine précise → alignement à
  // l'échantillon. Android : le beat reste sur l'<audio> partagé, lancé juste
  // après l'ouverture du micro ; l'écart mesuré est retiré du début de la voix.

  private async _beginCountdown(id: string): Promise<void> {
    await this._claimSession(() => this._beginCountdownInner(id));
  }

  private async _beginCountdownInner(id: string): Promise<void> {
    this.errorMsg.set(null);

    this._stopPreviewPlayback();
    if (this.beatIsPlaying()) { this.player.audioEl.pause(); this.beatIsPlaying.set(false); }
    this._stopBeatRaf();

    if (!await this._ensurePermission()) return;

    // Casque branché/débranché depuis l'ouverture : la latence à compenser en dépend.
    const hp = await this.pm.checkHeadphones().catch(() => null);
    if (hp) this.headphoneType.set(hp.type as HeadphoneType);

    // Position du beat où démarre la prise : début du beat, ou point de punch-in
    // (punchInSec est relatif au début de la piste existante).
    const punchSec     = this.punchInSec();
    const punchBase    = punchSec > 0 ? (this.tracks().find(t => t.id === id)?.beatStartSec ?? 0) : 0;
    const beatStartSec = punchBase + punchSec;

    this._prepareTake(id);
    this.countdown.set(COUNTDOWN_START);
    this.studioState.set('countdown');
    this.cdr.markForCheck();

    try {
      const beatPath = this._isIos ? await this._ensureNativeBeatFile().catch(() => null) : null;
      let started = false;

      if (beatPath) {
        await this._attachSessionListeners();
        const info = await this.pm.startSession({
          ...this._sessionOpts(),
          beatPath,
          beatStartSec,
          beatVolume:   this.beatVolume(),
          startDelayMs: COUNTDOWN_START * 1000,
        }).catch(() => null);

        if (info?.nativeBeat) {
          this._nativeSessionOpen = true;
          this._take = {
            beatStartSec,
            nativeBeat: true,
            latencyMs:  this._takeLatencyMs(info),
            leadSec:    0,
          };
          // Le décompte se termine pile au départ programmé du beat.
          await this._runCountdown(performance.now() + (info.startInMs ?? COUNTDOWN_START * 1000));
          this._nativeBeatClock = { perf: performance.now(), sec: beatStartSec };
          started = true;
        } else if (info) {
          // Session ouverte sans beat natif (ne devrait pas arriver) : on la
          // referme et on bascule sur le chemin <audio>.
          await this.pm.stopSession().catch(() => {});
        }
      }

      if (!started) {
        await this._runCountdown(performance.now() + COUNTDOWN_START * 1000);
        if (!this._levelHandle) await this._attachSessionListeners();
        await this.pm.startSession(this._sessionOpts());
        this._nativeSessionOpen = true;
        const micOpenedAt = performance.now();

        const el = this.player.audioEl;
        el.volume      = this.beatVolume();
        el.currentTime = beatStartSec;
        await el.play().catch(() => {});
        // Voix captée avant que le beat ne parte : retirée à la finalisation.
        this._take = {
          beatStartSec,
          nativeBeat: false,
          latencyMs:  this._takeLatencyMs(null),
          leadSec:    (performance.now() - micOpenedAt) / 1000,
        };
      }
    } catch (err) {
      console.error('[MobileStudio] start recording error', err);
      this._stopRecordingListeners();
      this._nativeSessionOpen = false;
      await this.pm.stopSession().catch(() => {});
      await this.pm.removeAllListeners().catch(() => {});
      this._recoverFromError();
      return;
    }

    // Studio fermé / prise annulée pendant le décompte
    if (this.studioState() !== 'countdown') return;

    this._startBeatRaf();
    if (this.metronome.active()) this.metronome.restart(this.track.bpm, beatStartSec);
    this._startRecordingUi();
  }

  /**
   * Latence casque (ms) à retirer du début de la voix : le chanteur entend le
   * beat en retard de cette durée et chante donc en retard d'autant.
   * Bluetooth réglé au métronome → la mesure de l'utilisateur ; sinon, iOS
   * rapporte la latence réelle de la route (Bluetooth compris).
   */
  private _takeLatencyMs(info: StartSessionInfo | null): number {
    if (isBluetooth(this.headphoneType())) {
      const calibrated = this._calibratedBtLatency();
      if (calibrated !== null) return calibrated;
    }
    if (info) return Math.max(0, (info.outputLatencyMs ?? 0) + (info.inputLatencyMs ?? 0));
    return 0;
  }

  /** Remet à zéro l'état d'une nouvelle prise. */
  private _prepareTake(id: string): void {
    this._rmsHistory      = [];
    this._liveRmsBars     = [];
    this._warnedNearEnd   = false;
    this._isFinalizingRec = false;
    this._take            = null;
    this._nativeBeatClock = null;
    this.recordRms.set(0);
    this.recordTimer.set(0);
    this.nearEnd.set(false);
    this.detectedNote.set(null);
    this.correctionCents.set(0);
    this.activeRecordingId.set(id);
    this.service.setRecording(id);
  }

  /**
   * Décompte affiché 3 → 2 → 1, calé sur une échéance absolue (performance.now)
   * pour finir exactement au départ du beat.
   */
  private _runCountdown(deadline: number): Promise<void> {
    return new Promise(resolve => {
      let shown = COUNTDOWN_START;
      this.countdown.set(shown);
      this._hapticTick();   // premier tic immédiat (affichage "3")
      this.cdr.markForCheck();
      this._countdownInterval = setInterval(() => {
        this.zone.run(() => {
          const remaining = deadline - performance.now();
          if (remaining <= 0) {
            clearInterval(this._countdownInterval!);
            this._countdownInterval = null;
            this.countdown.set(null);
            this.cdr.markForCheck();
            resolve();
            return;
          }
          const n = Math.min(COUNTDOWN_START, Math.ceil(remaining / 1000));
          if (n !== shown) {
            shown = n;
            this._hapticTick();   // tics "2" et "1"
            this.countdown.set(n);
            this.cdr.markForCheck();
          }
        });
      }, 20);
    });
  }

  private async _attachSessionListeners(): Promise<void> {
    this._levelHandle = await this.pm.addListener('level', ({ rms }) => {
      // Niveau affiché dès le décompte ; seule la prise elle-même nourrit la waveform.
      if (this.studioState() === 'recording') {
        this._rmsHistory.push(rms);
        this._liveRmsBars.push(rms);
        if (this._liveRmsBars.length > LIVE_WAVE_POINTS) this._liveRmsBars.shift();
        this._drawLiveWaveform(this._liveRmsBars);
      }
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
  }

  private _startRecordingUi(): void {
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
    this._stopTakePlayback();

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
    this._stopTakePlayback();
    this.pm.removeAllListeners().catch(() => {});
    this._finalizeRecording(data, true);
  }

  /** Coupe le beat de la prise (natif : la session est refermée par l'appelant). */
  private _stopTakePlayback(): void {
    this._nativeSessionOpen = false;
    this._nativeBeatClock   = null;
    this.player.audioEl.pause();
    this._stopBeatRaf();
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
    const existingTrack   = this.tracks().find(t => t.id === id);
    const isPunchIn       = this.punchInSec() > 0 && existingTrack?.rawBlob != null;
    const hadExistingTake = existingTrack?.rawBlob != null;
    const take            = this._take;

    try {
      const raw = Uint8Array.from(atob(result.pcmBase64), c => c.charCodeAt(0));
      const bytesPerSample = result.format === 'float32' ? 4 : 2;

      // ── Alignement sur le beat ───────────────────────────────────────────
      // startSec = position du beat sous le 1er échantillon capté (iOS : mesurée
      // par le moteur natif sur l'horloge audio). On retire ensuite du début de
      // la voix la latence casque (+ sur Android, la voix captée avant le départ
      // du beat) : la piste démarre alors exactement sur startSec.
      const startSec = take?.nativeBeat && result.firstSampleBeatSec != null
        ? result.firstSampleBeatSec
        : (take?.beatStartSec ?? 0);
      const cropSec     = take ? take.latencyMs / 1000 + take.leadSec : 0;
      const cropSamples = Math.max(0, Math.round(cropSec * result.sampleRate));
      const voice       = raw.subarray(Math.min(raw.length, cropSamples * bytesPerSample));
      const voiceSec    = voice.length / bytesPerSample / result.sampleRate;
      if (voiceSec < MIN_TAKE_SECONDS) throw new Error('take too short');

      // Le sample rate natif réel (44,1 kHz Android, variable iOS) est encodé dans le MIME
      // type — decodeBlob() s'en sert pour rééchantillonner vers le SR canonique du pipeline
      // au lieu de supposer 48 kHz à tort (cf. MobileAudioProcessorService.decodeBlob).
      const mime  = (result.format === 'float32' ? 'audio/pcm-f32' : 'audio/pcm-i16') + `;rate=${result.sampleRate}`;
      let rawBlob = new Blob([voice], { type: mime });

      const waveform = computeWaveform(this._rmsHistory, WAVEFORM_POINTS);
      let trackStart = startSec;
      let duration   = voiceSec;
      let finalWaveform = waveform;

      if (isPunchIn) {
        // Garde la prise existante jusqu'au point où la nouvelle commence (sur le beat).
        trackStart  = existingTrack!.beatStartSec;
        const local = Math.max(0, startSec - trackStart);
        rawBlob       = await this.processor.spliceAudio(existingTrack!.rawBlob!, rawBlob, local);
        duration      = local + voiceSec;
        finalWaveform = spliceWaveform(existingTrack!.waveform ?? [], local, duration, waveform, WAVEFORM_POINTS);
      }

      this.service.setRecorded(id, rawBlob, finalWaveform, duration, trackStart);
      // La nouvelle prise est sélectionnée : ses réglages s'ouvrent sous la timeline.
      this._selectLane(id);

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
      this.service.cancelRecording(id);
      this.errorMsg.set(interrupted
        ? 'Enregistrement interrompu avant d\'avoir capté votre voix. Réessayez.'
        : 'Erreur lors de l\'enregistrement. Réessayez.');
    }

    this._take = null;
    this._resetRecordingState();
  }

  private _recoverFromError(): void {
    const id = this.activeRecordingId();
    if (id) this.service.cancelRecording(id);
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

  // ── RAF playhead ─────────────────────────────────────────────────────────────

  private _startBeatRaf(): void {
    this._stopBeatRaf();
    const tick = () => {
      const el    = this.player.audioEl;
      const clock = this._nativeBeatClock;
      const tr    = this._transport;
      const d     = tr ? tr.duration
        : isFinite(el.duration) && el.duration > 0 ? el.duration : this.beatDuration();
      // Mix du studio : position lue sur l'horloge du contexte audio.
      // Beat joué par le moteur natif (iOS) : position extrapolée depuis son départ.
      const t = tr ? this._transportPos()
        : clock ? Math.min(clock.sec + (performance.now() - clock.perf) / 1000, d || Infinity)
        : el.currentTime;
      this.beatCurrentTime.set(t);
      if (d > 0) this.beatDuration.set(d);
      if (tr) this._followPlayhead();
      this._rafId = (tr || clock || (!el.paused && !el.ended))
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

  /** Arrête la lecture du mix et libère le contexte audio (la position est conservée). */
  private _stopPreviewPlayback(): void {
    this._transportSeq++;                 // annule un démarrage encore en décodage
    const wasPlaying = this._transport !== null;
    this._stopTransportSources();
    this._mixCtx?.close().catch(() => {});
    this._mixCtx = null;
    this._mixBus = null;
    if (wasPlaying) this._stopBeatRaf();
    this.isPlayingPreview.set(false);
    this.transportLoading.set(false);
  }

  // ── Export & Publication ──────────────────────────────────────────────────────

  async exportAndPublish(): Promise<void> {
    if (!this.auth.isLoggedIn()) {
      this.showGuestGate.set(true);
      this.cdr.markForCheck();
      return;
    }
    if (this._sessionId === null) {
      // Résolution de session pas encore terminée, ou bloquée par le quota —
      // ne devrait pas arriver via l'UI normale (publier est masqué tant que
      // ce n'est pas résolu), garde-fou défensif.
      this._setError('Session studio non prête — merci de patienter ou de rouvrir le studio.');
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
        // Latence déjà retirée de chaque prise à l'enregistrement (cf. _finalizeRecording).
        latencyHintMs: 0,
        beatBlob:      this._beatBlob() ?? undefined,
      });

      // Sauvegarde locale avant l'upload — filet de sécurité si le réseau coupe.
      const label = `${this.track.id}_${this.track.title.replace(/\s+/g, '_').slice(0, 30)}`;
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

      this._submitProcessedMp3(mp3, this._sessionId);

    } catch (err) {
      console.error('[MobileStudio] export error', err);
      this._setError('Erreur lors du traitement audio.');
    }
  }

  /**
   * Envoie un MP3 déjà mixé (fraîchement exporté ou repris depuis un brouillon
   * local, cf. resumeDraft()) vers /upload-processed avec la session qui l'a payé.
   */
  private _submitProcessedMp3(mp3: Blob, sessionId: number): void {
    const fd = new FormData();
    fd.append('processed_file', mp3, 'maquette.mp3');
    fd.append('track_id', String(this.track.id));
    fd.append('session_id', String(sessionId));
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
        } else if (res.code === 'SESSION_INVALID') {
          this.statusSvc.stopPolling();
          this._setError(res.feedback?.message ?? 'Session studio invalide — merci de rouvrir le studio.');
        } else {
          this.statusSvc.stopPolling();
          this._setError(res.feedback?.message ?? 'Erreur lors de l\'envoi.');
        }
        this.cdr.markForCheck();
      },
      error: (httpErr) => {
        this.statusSvc.stopPolling();
        if (httpErr?.error?.code === 'SESSION_INVALID') {
          this._setError(httpErr.error?.feedback?.message ?? 'Session studio invalide — merci de rouvrir le studio.');
        } else {
          this._setError('Impossible de contacter le serveur.');
        }
        this.cdr.markForCheck();
      },
    });
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
        // Latence déjà retirée de chaque prise à l'enregistrement (cf. _finalizeRecording).
        latencyHintMs: 0,
        beatBlob:      this._beatBlob() ?? undefined,
      });

      const label = `${this.track.id}_${this.track.title.replace(/\s+/g, '_').slice(0, 30)}`;
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
    this.showFxGate.set(false);
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
    // L'instrumentale change de longueur : la lecture repart du début.
    this._stopPreviewPlayback();
    this.beatCurrentTime.set(0);
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
    this.metronome.toggle(this.track.bpm, this.isPlayingPreview() ? this._transportPos() : this.player.audioEl.currentTime);
    this.cdr.markForCheck();
  }

  // ── Haptics ───────────────────────────────────────────────────────────────────

  private _hapticTick():    void { Haptics.impact({ style: ImpactStyle.Light  }).catch(() => {}); }
  private _hapticImpact():  void { Haptics.impact({ style: ImpactStyle.Medium }).catch(() => {}); }
  private _hapticSuccess(): void { Haptics.notification({ type: NotificationType.Success }).catch(() => {}); }

  // ── Destroy ───────────────────────────────────────────────────────────────────

  ngOnDestroy(): void {
    this._destroyed     = true;
    this._liveMonitorOn = false;
    this.player.studioOpen.set(false);
    // Une session native encore ouverte (fermeture pendant le décompte,
    // l'échauffement ou une prise) bloquerait la suivante ("Session already
    // active") et laisserait le micro + le beat natif tourner.
    if (this._nativeSessionOpen) {
      this._nativeSessionOpen = false;
      this.pm.stopSession().catch(() => {});
    }
    this._nativeBeatClock = null;
    if (this._nativeBeatFile) {
      const path = this._nativeBeatFile.uri.split('/').pop()!;
      Filesystem.deleteFile({ path, directory: Directory.Cache }).catch(() => {});
      this._nativeBeatFile = null;
    }
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
    if (this.beatIsPlaying()) this.player.audioEl.pause();
    this.pm.removeAllListeners().catch(() => {});
    this.player.audioEl.loop = false;
    this.player.audioEl.pause();
    this.service.reset();
  }
}
