import {
  Component, Input, Output, EventEmitter, OnDestroy,
  signal, computed, effect, untracked, inject, ChangeDetectionStrategy, ChangeDetectorRef,
  ElementRef, ViewChild, AfterViewInit
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { Capacitor } from '@capacitor/core';
import { TrackDetail, PublishedTopline } from '../../services/track.service';
import { MobileStudioComponent } from '../mobile-studio/mobile-studio.component';
import { ToplineService } from '../../services/topline.service';
import { ToplineStatusService } from '../../services/topline-status.service';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { GuestToplineService } from '../../services/guest-topline.service';
import { environment } from '../../../environments/environment';
import { AppDownloadService } from '../../services/app-download.service';
import { StudioToolbarComponent } from '../studio-toolbar/studio-toolbar.component';
import { DawGuestGateOverlayComponent } from '../mobile-studio/daw-guest-gate-overlay/daw-guest-gate-overlay.component';

type RecorderState = 'idle' | 'recording' | 'processing' | 'result';
type Lane = 'beat' | 'voice';

/** Couleur de la piste voix — même palette que le studio de l'app (TRACK_COLORS[0]). */
const VOICE_COLOR = '#4FC3F7';

@Component({
  selector: 'app-topline-recorder',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, MobileStudioComponent, StudioToolbarComponent, DawGuestGateOverlayComponent],
  templateUrl: './topline-recorder.component.html',
  // La feuille du studio de l'app fournit transport, timeline et inspecteur :
  // le studio web reprend exactement le même rendu.
  styleUrls: ['./topline-recorder.component.scss', '../mobile-studio/mobile-studio-timeline.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ToplineRecorderComponent implements AfterViewInit, OnDestroy {

  @Input() track!: TrackDetail;
  @Output() published = new EventEmitter<PublishedTopline>();
  @Output() closed    = new EventEmitter<void>();

  @ViewChild('visualizerCanvas') canvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('tlContent') tlContentRef?: ElementRef<HTMLElement>;

  readonly VOICE_COLOR = VOICE_COLOR;
  readonly env = environment;

  state         = signal<RecorderState>('idle');
  timer         = signal(0);
  errorMsg      = signal<string | null>(null);
  resultTopline = signal<PublishedTopline | null>(null);
  isPublished   = signal(false);
  loadingAudio   = signal(false);
  startingRecording = signal(false);
  calibrating    = signal(false);
  calibCountdown = signal<number | null>(null);
  calibTapCount  = signal(0);
  calibResult    = signal<number | null>(null);
  calibBeat      = signal(false);
  isBluetooth    = signal(false);
  // Calibration enregistrée avec un autre type de sortie (casque BT ↔ filaire/HP) : périmée
  calibStale     = signal(false);
  // 'denied' = micro bloqué dans le navigateur (le clic ne redemandera rien) ; 'unavailable' = pas d'appareil / contexte non sécurisé
  micState       = signal<'unknown' | 'prompt' | 'granted' | 'denied' | 'unavailable'>('unknown');
  readonly micBlocked = computed(() => this.micState() === 'denied' || this.micState() === 'unavailable');
  // « Plus tard » sur l'encart de calibration : masqué CALIB_NUDGE_SNOOZE_DAYS jours
  nudgeSnoozed   = signal(this._readNudgeSnoozed());
  readonly needsCalibration = computed(() => this.calibResult() === null || this.calibStale());
  readonly showCalibNudge   = computed(() => this.needsCalibration() && !this.nudgeSnoozed());

  useAutotune  = false;
  useMonitor   = false;
  description  = '';

  private toplineSvc       = inject(ToplineService);
  private toplineStatusSvc = inject(ToplineStatusService);
  readonly player          = inject(PlayerService);
  private cdr              = inject(ChangeDetectorRef);
  readonly auth            = inject(AuthService);
  readonly guestSvc        = inject(GuestToplineService);
  private http             = inject(HttpClient);
  private router           = inject(Router);
  readonly appDownload     = inject(AppDownloadService);

  readonly isNative = Capacitor.isNativePlatform();

  readonly isGuest          = computed(() => !this.auth.isLoggedIn());
  readonly guestSentTopline = signal(false);

  // Flag interne : un upload guest est en cours de traitement (polling actif)
  private _guestPolling = false;

  // ── Studio : transport · timeline · panneaux ──────────────────────────────
  readonly selectedLane   = signal<Lane>('voice');
  readonly showSettings   = signal(false);
  readonly showAppInfo    = signal(false);
  readonly showGuestGate  = signal(false);
  readonly downloading    = signal(false);
  /** Position (s) et durée de la prise dans le beat, connues à l'enregistrement. */
  readonly voiceStartSec  = signal(0);
  readonly voiceDurSec    = signal(0);
  private readonly _beatDur = signal(0);
  private readonly _mixDur  = signal(0);
  private _pendingSeek: number | null = null;
  /** Position demandée en fraction de la timeline, quand la durée réelle est encore inconnue. */
  private _pendingRatio: number | null = null;
  private _scrubbing = false;

  /** Ce que le lecteur global joue en ce moment, s'il s'agit de ce studio. */
  readonly source = computed<'beat' | 'mix' | null>(() => {
    const cur = this.player.currentTrack();
    if (!cur) return null;
    if (this._resultUrl() && cur.stream_url === this._resultUrl()) return 'mix';
    if (cur.id === this.track?.id && this.player.isReferenceSource()) return 'beat';
    return null;
  });
  readonly isPlayingStudio = computed(() => this.source() !== null && this.player.isPlaying());
  /** Durée représentée par la timeline : celle de l'audio chargé, sinon la dernière connue. */
  readonly spanSec = computed(() => {
    const src = this.source();
    const d = this.player.duration();
    if (src && d > 0 && isFinite(d)) return d;
    if (this.resultTopline() && this._mixDur() > 0) return this._mixDur();
    return this._beatDur() > 0 ? this._beatDur() : this.MAX_SECONDS;
  });
  readonly currentSec = computed(() => this.source() ? this.player.currentTime() : 0);
  readonly playheadPct = computed(() => Math.min(100, (this.currentSec() / this.spanSec()) * 100));
  readonly rulerMarks = computed(() => {
    const span = this.spanSec();
    const step = span > 120 ? 30 : span > 50 ? 15 : 5;
    const marks: { pct: number; label: string }[] = [];
    for (let t = 0; t < span; t += step) {
      marks.push({ pct: (t / span) * 100, label: this.formatTimer(t) });
    }
    return marks;
  });
  /** Clip de voix : grandit pendant la prise, posé là où le beat en était. */
  readonly voiceClip = computed(() => {
    const span = this.spanSec();
    const dur = this.state() === 'recording' ? this.timer() : this.voiceDurSec();
    if (dur <= 0) return null;
    // Le mix serveur cale la voix sur le beat : dans le mix, elle commence au même endroit.
    return {
      left:  Math.min(100, (this.voiceStartSec() / span) * 100),
      width: Math.max(0.5, Math.min(100, (dur / span) * 100)),
    };
  });
  readonly canPublish = computed(() => this.state() === 'result' && !!this.resultTopline());
  readonly publishLabel = computed(() => this.isPublished() ? 'Rendre privé' : 'Publier');
  readonly recordLabel = computed(() => {
    switch (this.state()) {
      case 'recording':  return 'Terminer';
      case 'processing': return 'Traitement…';
      case 'result':     return 'Réenregistrer';
      default:           return 'Enregistrer';
    }
  });
  readonly recordDisabled = computed(() => {
    const st = this.state();
    if (st === 'processing') return true;
    if (st === 'recording' || st === 'result') return false;
    return this.calibrating() || this.calibCountdown() !== null || this.micBlocked()
      || this.guestSentTopline()
      || this.auth.currentUser()?.topline_tokens === 0
      || (this.isGuest() && !this.guestSvc.hasAttemptsLeft());
  });
  private readonly _resultUrl = signal<string | null>(null);

  constructor() {
    // Dès que le job guest est traité, passer en state 'result' pour permettre l'écoute
    effect(() => {
      const tid = this.toplineStatusSvc.toplineId();
      const st  = this.toplineStatusSvc.status();
      if (tid && st === 'done' && this._guestPolling) {
        this._guestPolling = false;
        untracked(() => this._onGuestPollDone(parseInt(tid, 10)));
      }
    });

    // Mémorise les durées pour garder une timeline stable quand rien ne joue,
    // et applique une position demandée avant que l'audio soit chargé.
    effect(() => {
      const src = this.source();
      const d = this.player.duration();
      if (!src || !(d > 0) || !isFinite(d)) return;
      untracked(() => {
        (src === 'beat' ? this._beatDur : this._mixDur).set(d);
        const target = this._pendingRatio !== null ? this._pendingRatio * d : this._pendingSeek;
        if (target !== null && target > 0.05) this.player.seek(Math.min(target, d - 0.05));
        this._pendingSeek = null;
        this._pendingRatio = null;
      });
    });
  }

  private resultBlobUrl: string | null = null;

  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private recordingMimeType = '';
  private timerInterval: ReturnType<typeof setInterval> | null = null;
  private audioCtx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private monitorNode: MediaStreamAudioDestinationNode | null = null;
  private rafId: number | null = null;
  private micStream: MediaStream | null = null;
  private monitorAudio: HTMLAudioElement | null = null;

  // Plafond unifié web/mobile (config.TOPLINE_MAX_DURATION, backend). La
  // référence n'est plus tronquée à 90s (cf. reference_stream_url), donc plus
  // besoin de marge de sécurité sous cette ancienne limite.
  readonly MAX_SECONDS = 150;
  readonly MIN_SECONDS = 10;

  private recordingStartTime = 0;
  private recordingTooShort  = false;
  private _latencyHintMs     = 0;
  private _beatOffsetMs      = 0;
  private _micPermStatus: PermissionStatus | null = null;
  private readonly CALIB_NUDGE_SNOOZE_DAYS = 3;

  private _calibCtx:       AudioContext | null = null;
  private _calibBeatTimes: number[] = [];
  private _calibTapTimes:  number[] = [];
  private _calibCountdownTimer: ReturnType<typeof setTimeout> | null = null;
  readonly CALIB_BEATS            = 8;
  readonly CALIB_COUNTDOWN_SECS   = 3;
  private readonly _CALIB_LEAD_IN = 2;
  private readonly _CALIB_BPM     = 90;

  private _readNudgeSnoozed(): boolean {
    const until = parseInt(localStorage.getItem('laprod_calib_nudge_until') ?? '', 10);
    return until > Date.now();
  }

  snoozeCalibNudge(): void {
    const until = Date.now() + this.CALIB_NUDGE_SNOOZE_DAYS * 86_400_000;
    localStorage.setItem('laprod_calib_nudge_until', String(until));
    this.nudgeSnoozed.set(true);
  }

  ngAfterViewInit(): void {
    this._initLatencyHint();
    this._watchMicPermission();
  }

  /** Suit l'état de la permission micro (Permissions API ; absente/partielle sur Safari → repli sur l'erreur du clic). */
  private async _watchMicPermission(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      this.micState.set('unavailable');
      return;
    }
    try {
      const status = await navigator.permissions.query({ name: 'microphone' as PermissionName });
      this._micPermStatus = status;
      const sync = () => {
        this.micState.set(status.state as 'prompt' | 'granted' | 'denied');
        this.cdr.markForCheck();
      };
      status.onchange = sync;
      sync();
    } catch { /* Safari : on laisse 'unknown', getUserMedia tranchera au clic */ }
  }

  /** Relance après que l'utilisateur a réautorisé le micro dans les réglages du site. */
  async retryMic(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) return;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      s.getTracks().forEach(t => t.stop());
      this.micState.set('granted');
      this.errorMsg.set(null);
    } catch (e) {
      this.micState.set(this._isNoDeviceError(e) ? 'unavailable' : 'denied');
    }
    this.cdr.markForCheck();
  }

  private _isNoDeviceError(e: unknown): boolean {
    const n = (e as DOMException)?.name;
    return n === 'NotFoundError' || n === 'NotReadableError' || n === 'OverconstrainedError';
  }

  private async _initLatencyHint(): Promise<void> {
    const saved = parseInt(localStorage.getItem('laprod_latency_ms') ?? '', 10);
    if (saved > 0 && saved <= 500) {
      this.calibResult.set(saved);
      this._latencyHintMs = saved;
    }
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const BT_RE = /bluetooth|airpod|galaxy\s*bud|jabra|bose\b|sennheiser|jbl\b|beats\s|powerbeats|wireless/i;
      if (devices.filter(d => d.kind === 'audioinput').some(d => BT_RE.test(d.label))) {
        this.isBluetooth.set(true);
      }
    } catch { /* ignore */ }
    // Une calibration faite en filaire n'est pas valable en Bluetooth (+100-200 ms) et inversement
    const savedBt = localStorage.getItem('laprod_latency_bt');
    if (this.calibResult() !== null && savedBt !== null && (savedBt === '1') !== this.isBluetooth()) {
      this.calibStale.set(true);
      this.nudgeSnoozed.set(false);
    }
    this.cdr.markForCheck();
  }

  private detectMimeType(): string {
    const preferred = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/ogg;codecs=opus',
      'audio/ogg',
      'audio/mp4',
    ];
    if (typeof MediaRecorder === 'undefined') return '';
    for (const type of preferred) {
      if (MediaRecorder.isTypeSupported(type)) return type;
    }
    return '';
  }

  async startRecording(): Promise<void> {
    this.errorMsg.set(null);
    this.showSettings.set(false);
    this.selectedLane.set('voice');
    this.player.pause();
    // Feedback pendant la préparation (permission micro + attente du beat
    // audible) : sans ça, le bouton reste cliquable et silencieux pendant
    // jusqu'à 2s, ce qui invite au double-clic et masque ce qui se passe.
    this.startingRecording.set(true);
    this.cdr.markForCheck();

    try {
      if (!navigator.mediaDevices?.getUserMedia) {
        this.micState.set('unavailable');
        this.errorMsg.set('Le microphone n\'est pas disponible ici (connexion sécurisée HTTPS requise).');
        return;
      }
      if (typeof MediaRecorder === 'undefined') {
        this.errorMsg.set('Votre navigateur ne prend pas en charge l\'enregistrement audio. Mettez à jour Safari ou utilisez Chrome.');
        return;
      }

      try {
        // Désactiver le traitement du signal iOS qui peut changer la route audio
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
          video: false,
        });
      } catch (e) {
        if (this._isNoDeviceError(e)) {
          this.micState.set('unavailable');
          this.errorMsg.set('Aucun microphone utilisable détecté. Branchez un micro ou fermez l\'application qui l\'utilise.');
        } else {
          this.micState.set('denied');
          this.errorMsg.set('Accès au microphone refusé. Autorisez le micro dans votre navigateur.');
        }
        return;
      }

      await this._prepareAndRecord();
    } finally {
      this.startingRecording.set(false);
      this.cdr.markForCheck();
    }
  }

  private async _prepareAndRecord(): Promise<void> {
    // Web Audio API — visualizer
    this.audioCtx = new AudioContext();
    // iOS : l'AudioContext créé dans un contexte async démarre en suspended
    if (this.audioCtx.state === 'suspended') {
      await this.audioCtx.resume();
    }

    // Detect Bluetooth from actual mic track label (more reliable than enumerateDevices)
    const trackLabel = this.micStream!.getAudioTracks()[0]?.label ?? '';
    const BT_RE = /bluetooth|airpod|galaxy\s*bud|jabra|bose\b|sennheiser|jbl\b|beats\s|powerbeats|wireless/i;
    if (BT_RE.test(trackLabel)) this.isBluetooth.set(true);
    const isBT = this.isBluetooth();

    // Prefer saved calibration; otherwise estimate from AudioContext latency values.
    // The user sings in response to what they *hear* (delayed by outputLatency + BT codec),
    // so their voice arrives late in the merged file by that same amount.
    const savedCalib = parseInt(localStorage.getItem('laprod_latency_ms') ?? '', 10);
    if (savedCalib > 0 && savedCalib <= 500) {
      this._latencyHintMs = savedCalib;
    } else {
      const outputLatency = (this.audioCtx as any).outputLatency ?? 0;
      const baseLatency   = (this.audioCtx as any).baseLatency   ?? 0;
      let latencyHintMs   = Math.round((outputLatency + baseLatency) * 1000);
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
      if (isBT)       latencyHintMs = Math.max(latencyHintMs, 150); // Bluetooth A2DP floor
      else if (isIOS) latencyHintMs = Math.max(latencyHintMs, 80);  // iOS under-reports
      this._latencyHintMs = Math.min(latencyHintMs, 500);
    }

    const source  = this.audioCtx.createMediaStreamSource(this.micStream!);
    this.analyser = this.audioCtx.createAnalyser();
    this.analyser.fftSize = 256;
    source.connect(this.analyser);

    // Monitoring (hear yourself)
    if (this.useMonitor) {
      this.monitorAudio = new Audio();
      this.monitorAudio.srcObject = this.micStream;
      this.monitorAudio.play().catch(() => {});
    }

    // iOS : laisser 150 ms à la session audio pour stabiliser la route
    // après activation du micro (évite le renvoi vers l'écouteur interne)
    await new Promise<void>(resolve => setTimeout(resolve, 150));

    // Beat playback — la référence watermarquée dense (pas de troncature à
    // 90s) : c'est cette version qui est mixée avec la voix côté serveur
    // dans la topline exportée (cf. merge_voice_and_beat, routes/toplines_api.py).
    //
    // player.play() ne fait que poser un signal ; le son réel ne démarre
    // qu'après le chargement WaveSurfer (fetch + décodage), délai variable
    // et non borné selon le cache navigateur. Sans attendre l'événement
    // 'playing' de l'audio réel, le MediaRecorder capturait dès t≈0 alors
    // que le beat n'était audible qu'après ce délai : à la fusion, seule la
    // latence matérielle (calibration) est retranchée, jamais ce délai de
    // chargement — la voix ressortait décalée du beat dans le fichier exporté.
    await this._waitForBeatAudible();

    // MediaRecorder — détection du format supporté par le navigateur
    this.chunks = [];
    this.recordingMimeType = this.detectMimeType();
    const recorderOptions: MediaRecorderOptions = this.recordingMimeType
      ? { mimeType: this.recordingMimeType }
      : {};
    this.mediaRecorder = new MediaRecorder(this.micStream!, recorderOptions);
    this.mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.mediaRecorder.onstop = () => this.onRecordingStop();
    // Position réelle du beat quand le recorder démarre : voix[0] ≠ beat[0].
    // Envoyée au serveur pour caler la voix sur le beat à la fusion.
    this._beatOffsetMs = 0;
    this.mediaRecorder.onstart = () => {
      this._beatOffsetMs = Math.max(0, Math.round(this.player.audioEl.currentTime * 1000));
    };
    this.mediaRecorder.start(100);

    // Timer
    this.recordingStartTime = Date.now();
    this.timer.set(0);
    this.timerInterval = setInterval(() => {
      const t = this.timer() + 1;
      this.timer.set(t);
      this.cdr.markForCheck();
      if (t >= this.MAX_SECONDS) this.stopRecording(true);
    }, 1000);

    this.state.set('recording');
    this.cdr.markForCheck();
    // Le canvas n'existe qu'une fois la vue « recording » rendue.
    setTimeout(() => this.drawVisualizer());
  }

  /**
   * Résout quand `player.audioEl` émet réellement 'playing' (son audible),
   * pas seulement quand play() a été demandé. Filet de sécurité 4s si
   * l'événement n'arrive jamais, pour ne pas bloquer l'enregistrement.
   */
  private _waitForBeatAudible(): Promise<void> {
    return new Promise<void>(resolve => {
      const audioEl = this.player.audioEl;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        audioEl.removeEventListener('playing', onPlaying);
        resolve();
      };
      const onPlaying = () => finish();
      audioEl.addEventListener('playing', onPlaying);
      setTimeout(finish, 4000);

      // Beat déjà chargé (écouté dans le studio) : le lecteur ne recharge pas
      // une piste identique, play() n'émettrait jamais 'playing'. On le relance
      // depuis le début ; pause d'abord pour que 'playing' soit bien émis.
      if (this.source() === 'beat') {
        this.player.pause();
        this.player.seek(0);
        this.player.resume();
      } else {
        this.player.play(this.track as any, 'home', { referenceSource: true });
      }
    });
  }

  stopRecording(auto = false): void {
    const elapsed = (Date.now() - this.recordingStartTime) / 1000;
    this.voiceStartSec.set(this._beatOffsetMs / 1000);
    this.voiceDurSec.set(elapsed >= this.MIN_SECONDS ? Math.min(elapsed, this.MAX_SECONDS) : 0);
    if (elapsed < this.MIN_SECONDS) {
      this.recordingTooShort = true;
      this.errorMsg.set(
        `Enregistrement trop court (${Math.floor(elapsed)}s). Minimum requis : ${this.MIN_SECONDS} secondes.`
      );
      this.cdr.markForCheck();
    } else if (auto) {
      this.errorMsg.set(
        `Durée max atteinte (${this.formatTimer(this.MAX_SECONDS)}) — enregistrement arrêté automatiquement.`
      );
      this.cdr.markForCheck();
    }
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    this.clearTimerAndMic();
  }

  private clearTimerAndMic(): void {
    if (this.timerInterval) { clearInterval(this.timerInterval); this.timerInterval = null; }
    if (this.rafId) { cancelAnimationFrame(this.rafId); this.rafId = null; }
    if (this.monitorAudio) { this.monitorAudio.pause(); this.monitorAudio = null; }
    this.micStream?.getTracks().forEach(t => t.stop());
    this.micStream = null;
    this.audioCtx?.close();
    this.audioCtx = null;
    this.analyser = null;
  }

  private async onRecordingStop(): Promise<void> {
    this.player.pause();

    if (this.recordingTooShort) {
      this.recordingTooShort = false;
      this.state.set('idle');
      this.cdr.markForCheck();
      return;
    }

    this.state.set('processing');
    this.cdr.markForCheck();

    // Sur natif, onRecordingStop() n'est jamais atteint : le template redirige
    // vers MobileRecorderComponent qui gère l'intégralité du flux natif.
    const mimeType = this.recordingMimeType || 'audio/webm';
    const ext      = mimeType.includes('mp4') ? 'mp4' : mimeType.includes('ogg') ? 'ogg' : 'webm';
    const voiceBlob = new Blob(this.chunks, { type: mimeType });

    const fd = new FormData();
    fd.append('voice_file',      voiceBlob, `voice.${ext}`);
    fd.append('track_id',        String(this.track.id));
    fd.append('use_autotune',    String(this.useAutotune));
    fd.append('latency_hint_ms', String(this._latencyHintMs));
    fd.append('beat_offset_ms',  String(this._beatOffsetMs));
    if (this.description) fd.append('description', this.description);

    const imageUrl = this.track.image_file
      ? `${environment.apiUrl}/db_assets/${this.track.image_file}`
      : null;
    this.toplineStatusSvc.openForUpload(this.track.id, this.track.title, imageUrl);

    const guestId = this.isGuest() ? this.guestSvc.sessionId() : undefined;

    this.toplineSvc.uploadTopline(fd, guestId).subscribe({
      next: (res) => {
        if (res.success && res.data?.job_id) {
          if (this.isGuest()) {
            this.guestSvc.syncFromServer(res.data.remaining_guest_attempts ?? null);
            this.guestSvc.markPendingClaim();
            this.guestSentTopline.set(true);
            // Démarre le polling pour suivre la progression ET permettre l'écoute
            this._guestPolling = true;
            this.toplineStatusSvc.startPolling(res.data.job_id);
            this.state.set('idle');
          } else {
            this.toplineStatusSvc.startPolling(res.data.job_id);
            this.state.set('idle');
            this.closed.emit();
          }
        } else {
          this.toplineStatusSvc.stopPolling();
          this.errorMsg.set(res.feedback?.message ?? 'Erreur lors de l\'envoi.');
          this.state.set('idle');
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.toplineStatusSvc.stopPolling();
        this.errorMsg.set('Impossible de contacter le serveur.');
        this.state.set('idle');
        this.cdr.markForCheck();
      }
    });
  }

  async playResult(): Promise<void> {
    const tl = this.resultTopline();
    if (!tl || this.loadingAudio()) return;

    // Déjà chargé dans le lecteur : play/pause
    if (this.source() === 'mix') {
      this.player.togglePlay();
      return;
    }

    // Fetch avec JWT (connecté) ou X-Guest-Session (guest), une seule fois
    this.loadingAudio.set(true);
    this.cdr.markForCheck();
    const url = this.resultBlobUrl ?? await this._fetchResultUrl();
    this.loadingAudio.set(false);
    this.cdr.markForCheck();
    if (!url) return;
    this.player.play({
      id:            tl.id,
      title:         `Topline — aperçu`,
      composer_user: tl.artist_user as any,
      stream_url:      url,
      full_stream_url: null,
      image_file:    this.track.image_file,
      bpm: 0, key: '', style: '', price_mp3: 0, tags: [], is_approved: false,
      playlist_count: 0, first_playlist_image: null,
    });
  }

  publishResult(): void {
    const tl = this.resultTopline();
    if (!tl) return;
    this.toplineSvc.publishTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success && res.data?.topline) {
          this.isPublished.set(true);
          this.published.emit(res.data.topline);
          this.cdr.markForCheck();
        } else {
          this.errorMsg.set(res.feedback?.message ?? 'Erreur lors de la publication.');
          this.cdr.markForCheck();
        }
      },
      error: () => {
        this.errorMsg.set('Impossible de contacter le serveur.');
        this.cdr.markForCheck();
      }
    });
  }

  unpublishResult(): void {
    const tl = this.resultTopline();
    if (!tl) return;
    this.toplineSvc.unpublishTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success) {
          this.isPublished.set(false);
          this.cdr.markForCheck();
        } else {
          this.errorMsg.set(res.feedback?.message ?? 'Erreur.');
          this.cdr.markForCheck();
        }
      },
      error: () => {
        this.errorMsg.set('Impossible de contacter le serveur.');
        this.cdr.markForCheck();
      }
    });
  }

  deleteResult(): void {
    const tl = this.resultTopline();
    if (!tl) return;
    this.toplineSvc.deleteTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success) {
          this.resetToIdle();
        } else {
          this.errorMsg.set(res.feedback?.message ?? 'Erreur lors de la suppression.');
          this.cdr.markForCheck();
        }
      },
      error: () => {
        this.errorMsg.set('Impossible de contacter le serveur.');
        this.cdr.markForCheck();
      }
    });
  }

  private _onGuestPollDone(toplineId: number): void {
    // Construit un PublishedTopline minimal pour permettre l'écoute
    const tl: PublishedTopline = {
      id:           toplineId,
      artist_id:    0,
      stream_url:   `/api/stream/toplines/${toplineId}`,
      description:  null,
      created_at:   new Date().toISOString(),
      is_published: false,
      artist_user:  { username: '', profile_image: null },
    };
    this.resultTopline.set(tl);
    this.guestSentTopline.set(false);
    this.state.set('result');
    this.cdr.markForCheck();
  }

  resetToIdle(): void {
    if (this.resultBlobUrl) { URL.revokeObjectURL(this.resultBlobUrl); this.resultBlobUrl = null; }
    this._resultUrl.set(null);
    this.resultTopline.set(null);
    this.isPublished.set(false);
    this.loadingAudio.set(false);
    this.errorMsg.set(null);
    this.timer.set(0);
    this.guestSentTopline.set(false);
    this._guestPolling = false;
    this.voiceDurSec.set(0);
    this.voiceStartSec.set(0);
    this.state.set('idle');
    this.cdr.markForCheck();
  }

  private drawVisualizer(): void {
    if (!this.analyser || !this.canvasRef) return;
    const canvas  = this.canvasRef.nativeElement;
    const ctx     = canvas.getContext('2d');
    if (!ctx) return;
    const bufLen  = this.analyser.frequencyBinCount;
    const dataArr = new Uint8Array(bufLen);

    const draw = () => {
      if (!this.analyser) return;
      this.rafId = requestAnimationFrame(draw);
      this.analyser.getByteFrequencyData(dataArr);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      const barW = (canvas.width / bufLen) * 2.5;
      let x = 0;
      for (let i = 0; i < bufLen; i++) {
        const h = (dataArr[i] / 255) * canvas.height;
        ctx.fillStyle = `hsl(${355 - i * 0.25}, 78%, 56%)`;
        ctx.fillRect(x, canvas.height - h, barW, h);
        x += barW + 1;
      }
    };
    draw();
  }

  fmtSec(sec: number): string {
    return this.formatTimer(Math.floor(Math.max(0, sec || 0)));
  }

  formatTimer(s: number): string {
    const m = Math.floor(s / 60);
    return `${m}:${(s % 60).toString().padStart(2, '0')}`;
  }

  // ── Barre d'outils ───────────────────────────────────────────────────────────

  onRecordPressed(): void {
    switch (this.state()) {
      case 'recording': this.stopRecording(); break;
      case 'result':    this.resetToIdle(); break;
      case 'idle':      void this.startRecording(); break;
    }
  }

  toggleSettings(): void {
    if (this.state() === 'recording' || this.state() === 'processing') return;
    if (this.showSettings()) this.cancelCalibration();
    this.showSettings.update(v => !v);
  }

  onPublishPressed(): void {
    if (!this.canPublish()) return;
    if (this.isGuest()) { this.showGuestGate.set(true); return; }
    if (this.isPublished()) this.unpublishResult(); else this.publishResult();
  }

  /** Télécharge le mix voix + beat calculé par le serveur. */
  async downloadResult(): Promise<void> {
    if (!this.resultTopline() || this.downloading()) return;
    this.downloading.set(true);
    try {
      const url = this.resultBlobUrl ?? await this._fetchResultUrl();
      if (!url) return;
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(this.track.title || 'topline').replace(/[^\p{L}\p{N} _-]+/gu, '').trim() || 'topline'} - topline.mp3`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } finally {
      this.downloading.set(false);
      this.cdr.markForCheck();
    }
  }

  goToRegister(): void {
    this.showGuestGate.set(false);
    this.closed.emit();
    this.router.navigate(['/register']);
  }

  // ── Transport · timeline ─────────────────────────────────────────────────────

  /** Lecture / pause : le mix (voix + beat) s'il existe, sinon l'instrumentale. */
  togglePlay(): void {
    if (this.state() === 'recording' || this.state() === 'processing') return;
    if (this.isPlayingStudio()) { this.player.pause(); return; }
    this._playAt(this.source() ? this.player.currentTime() : 0);
  }

  playFromStart(): void {
    if (this.state() === 'recording' || this.state() === 'processing') return;
    this._playAt(0);
  }

  selectLane(lane: Lane): void {
    this.selectedLane.set(lane);
  }

  /** Clic dans une piste : sélection + lecture du mix à cet endroit. */
  onLaneClick(event: MouseEvent, lane: Lane): void {
    this.selectedLane.set(lane);
    if (this.state() === 'recording' || this.state() === 'processing') return;
    this._playAt(this._secAtClientX(event.clientX));
  }

  onScrubStart(e: PointerEvent): void {
    if (this.state() === 'recording' || this.state() === 'processing') return;
    this._scrubbing = true;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    this._scrubTo(e.clientX);
  }

  onScrubMove(e: PointerEvent): void {
    if (this._scrubbing) this._scrubTo(e.clientX);
  }

  onScrubEnd(e: PointerEvent): void {
    if (!this._scrubbing) return;
    this._scrubbing = false;
    (e.target as Element).releasePointerCapture?.(e.pointerId);
    if (!this.isPlayingStudio()) this._playAt(this._secAtClientX(e.clientX));
  }

  onBeatVolumeInput(e: Event): void {
    this.player.setVolume(+(e.target as HTMLInputElement).value);
  }

  private _scrubTo(clientX: number): void {
    const sec = this._secAtClientX(clientX);
    if (this.source()) this.player.seek(sec);
  }

  private _secAtClientX(clientX: number): number {
    const el = this.tlContentRef?.nativeElement;
    if (!el) return 0;
    const r = el.getBoundingClientRect();
    const ratio = r.width > 0 ? (clientX - r.left) / r.width : 0;
    return Math.max(0, Math.min(1, ratio)) * this.spanSec();
  }

  private _playAt(sec: number): void {
    const wanted = this.resultTopline() ? 'mix' : 'beat';
    if (this.source() === wanted) {
      this.player.seek(sec);
      this.player.resume();
      return;
    }
    // L'audio n'est pas encore chargé : la position est appliquée dès que sa durée est connue.
    // Durée encore jamais vue → la timeline est provisoire : on garde la fraction cliquée.
    const known = wanted === 'mix' ? this._mixDur() : this._beatDur();
    this._pendingSeek  = known > 0 ? sec : null;
    this._pendingRatio = known > 0 ? null : sec / this.spanSec();
    if (wanted === 'mix') this.playResult();
    else this.player.play(this.track as any, 'home', { referenceSource: true });
  }

  private _fetchResultUrl(): Promise<string | null> {
    const tl = this.resultTopline();
    if (!tl) return Promise.resolve(null);
    const authHeader: Record<string, string> = this.isGuest()
      ? { 'X-Guest-Session': this.guestSvc.sessionId() }
      : { 'Authorization': `Bearer ${this.auth.getToken()}` };
    return new Promise(resolve => {
      this.http.get(`${environment.apiUrl}${tl.stream_url}`, { headers: authHeader, responseType: 'blob' })
        .subscribe({
          next: (blob) => {
            if (this.resultBlobUrl) URL.revokeObjectURL(this.resultBlobUrl);
            this.resultBlobUrl = URL.createObjectURL(blob);
            this._resultUrl.set(this.resultBlobUrl);
            resolve(this.resultBlobUrl);
          },
          error: () => {
            this.errorMsg.set('Impossible de charger l\'audio.');
            this.cdr.markForCheck();
            resolve(null);
          },
        });
    });
  }

  // ── Calibration ──────────────────────────────────────────────────────────────

  startCalibration(): void {
    if (this._calibCtx || this.calibrating() || this.calibCountdown() !== null) return;
    this._calibBeatTimes = [];
    this._calibTapTimes  = [];
    this.calibTapCount.set(0);
    this.calibResult.set(null);

    // Décompte visible avant le premier son : sans lui, le métronome
    // démarrait sans prévenir et le premier tap ne pouvait jamais être
    // proche de 0 ms de latence (réaction humaine face à un son surprise).
    this.calibCountdown.set(this.CALIB_COUNTDOWN_SECS);
    this.cdr.markForCheck();
    this._calibCountdownTimer = setTimeout(() => this._tickCalibCountdown(), 1000);
  }

  private _tickCalibCountdown(): void {
    const current = this.calibCountdown();
    if (current === null) return; // annulé entre-temps

    if (current <= 1) {
      this.calibCountdown.set(null);
      this.cdr.markForCheck();
      this._startCalibMetronome();
      return;
    }

    this.calibCountdown.set(current - 1);
    this.cdr.markForCheck();
    this._calibCountdownTimer = setTimeout(() => this._tickCalibCountdown(), 1000);
  }

  private _startCalibMetronome(): void {
    if (this._calibCtx || this.calibrating()) return;

    try {
      this._calibCtx = new AudioContext();
    } catch {
      this.errorMsg.set('Impossible d\'accéder au contexte audio pour la calibration.');
      this.cdr.markForCheck();
      return;
    }

    this.calibrating.set(true);
    this.cdr.markForCheck();

    const ctx        = this._calibCtx;
    const intervalS  = 60 / this._CALIB_BPM;
    const totalBeats = this._CALIB_LEAD_IN + this.CALIB_BEATS;
    const startTime  = ctx.currentTime + 0.15;

    for (let i = 0; i < totalBeats; i++) {
      const beatTime = startTime + i * intervalS;

      // Schedule audio click
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = i < this._CALIB_LEAD_IN ? 660 : 880;
      gain.gain.setValueAtTime(0, beatTime);
      gain.gain.linearRampToValueAtTime(0.35, beatTime + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.001, beatTime + 0.055);
      osc.start(beatTime);
      osc.stop(beatTime + 0.055);

      // Schedule visual flash
      const visualDelay = Math.max(0, (beatTime - ctx.currentTime) * 1000);
      setTimeout(() => {
        if (!this.calibrating()) return;
        this.calibBeat.set(true);
        this.cdr.markForCheck();
        setTimeout(() => { this.calibBeat.set(false); this.cdr.markForCheck(); }, 90);
      }, visualDelay);

      // Track beat times (only measure beats, not lead-in)
      if (i >= this._CALIB_LEAD_IN) {
        this._calibBeatTimes.push(beatTime);
      }
    }

    // Auto-finish after last beat + 1 grace beat
    const finishAfterMs = (startTime - ctx.currentTime + (totalBeats + 0.8) * intervalS) * 1000;
    setTimeout(() => { if (this.calibrating()) this._finishCalibration(); }, finishAfterMs);
  }

  onCalibTap(): void {
    if (!this._calibCtx || !this.calibrating()) return;
    this._calibTapTimes.push(this._calibCtx.currentTime);
    const count = this._calibTapTimes.length;
    this.calibTapCount.set(count);
    this.cdr.markForCheck();
    if (count >= this.CALIB_BEATS) this._finishCalibration();
  }

  private _finishCalibration(): void {
    if (!this.calibrating()) return;
    this.calibrating.set(false);

    const taps  = this._calibTapTimes;
    const beats = this._calibBeatTimes;

    if (taps.length >= 3) {
      const offsets: number[] = [];
      for (let i = 0; i < Math.min(taps.length, beats.length); i++) {
        offsets.push((taps[i] - beats[i]) * 1000);
      }
      offsets.sort((a, b) => a - b);
      const mid    = Math.floor(offsets.length / 2);
      const median = offsets.length % 2 === 0
        ? (offsets[mid - 1] + offsets[mid]) / 2
        : offsets[mid];
      const result = Math.max(0, Math.min(500, Math.round(median)));
      this.calibResult.set(result);
      this._latencyHintMs = result;
      localStorage.setItem('laprod_latency_ms', String(result));
      localStorage.setItem('laprod_latency_bt', this.isBluetooth() ? '1' : '0');
      this.calibStale.set(false);
    }

    this._calibCtx?.close();
    this._calibCtx      = null;
    this._calibBeatTimes = [];
    this._calibTapTimes  = [];
    this.cdr.markForCheck();
  }

  cancelCalibration(): void {
    if (this._calibCountdownTimer !== null) {
      clearTimeout(this._calibCountdownTimer);
      this._calibCountdownTimer = null;
    }
    this.calibCountdown.set(null);

    if (!this.calibrating()) { this.cdr.markForCheck(); return; }
    this.calibrating.set(false);
    this._calibCtx?.close();
    this._calibCtx      = null;
    this._calibBeatTimes = [];
    this._calibTapTimes  = [];
    this.cdr.markForCheck();
  }

  resetCalibration(): void {
    localStorage.removeItem('laprod_latency_ms');
    localStorage.removeItem('laprod_latency_bt');
    this.calibStale.set(false);
    this.calibResult.set(null);
    this._latencyHintMs = 0;
    this.cdr.markForCheck();
  }

  ngOnDestroy(): void {
    if (this._micPermStatus) this._micPermStatus.onchange = null;
    this.clearTimerAndMic();
    this.cancelCalibration();
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    if (this.resultBlobUrl) URL.revokeObjectURL(this.resultBlobUrl);
  }

}
