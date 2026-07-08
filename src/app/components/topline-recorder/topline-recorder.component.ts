import {
  Component, Input, Output, EventEmitter, OnDestroy,
  signal, computed, effect, untracked, inject, ChangeDetectionStrategy, ChangeDetectorRef,
  ElementRef, ViewChild, AfterViewInit
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
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

type RecorderState = 'idle' | 'recording' | 'processing' | 'result';

@Component({
  selector: 'app-topline-recorder',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, MobileStudioComponent],
  templateUrl: './topline-recorder.component.html',
  styleUrls: ['./topline-recorder.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ToplineRecorderComponent implements AfterViewInit, OnDestroy {

  @Input() track!: TrackDetail;
  @Output() published = new EventEmitter<PublishedTopline>();
  @Output() closed    = new EventEmitter<void>();

  @ViewChild('visualizerCanvas') canvasRef!: ElementRef<HTMLCanvasElement>;

  state         = signal<RecorderState>('idle');
  timer         = signal(0);
  errorMsg      = signal<string | null>(null);
  resultTopline = signal<PublishedTopline | null>(null);
  isPublished   = signal(false);
  loadingAudio   = signal(false);
  calibrating    = signal(false);
  calibTapCount  = signal(0);
  calibResult    = signal<number | null>(null);
  calibBeat      = signal(false);
  isBluetooth    = signal(false);

  useAutotune  = false;
  useMonitor   = false;
  description  = '';

  private toplineSvc       = inject(ToplineService);
  private toplineStatusSvc = inject(ToplineStatusService);
  private player           = inject(PlayerService);
  private cdr              = inject(ChangeDetectorRef);
  readonly auth            = inject(AuthService);
  readonly guestSvc        = inject(GuestToplineService);
  private http             = inject(HttpClient);

  readonly isNative = Capacitor.isNativePlatform();

  readonly isGuest          = computed(() => !this.auth.isLoggedIn());
  readonly guestSentTopline = signal(false);

  // Flag interne : un upload guest est en cours de traitement (polling actif)
  private _guestPolling = false;

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

  readonly MAX_SECONDS = 70;
  readonly MIN_SECONDS = 10;

  private recordingStartTime = 0;
  private recordingTooShort  = false;
  private _latencyHintMs     = 0;

  private _calibCtx:       AudioContext | null = null;
  private _calibBeatTimes: number[] = [];
  private _calibTapTimes:  number[] = [];
  readonly CALIB_BEATS           = 8;
  private readonly _CALIB_LEAD_IN = 2;
  private readonly _CALIB_BPM     = 90;

  ngAfterViewInit(): void {
    this._initLatencyHint();
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
    this.player.pause();

    if (typeof MediaRecorder === 'undefined') {
      this.errorMsg.set('Votre navigateur ne prend pas en charge l\'enregistrement audio. Mettez à jour Safari ou utilisez Chrome.');
      this.cdr.markForCheck();
      return;
    }

    try {
      // Désactiver le traitement du signal iOS qui peut changer la route audio
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        video: false,
      });
    } catch {
      this.errorMsg.set('Accès au microphone refusé. Autorisez le micro dans votre navigateur.');
      this.cdr.markForCheck();
      return;
    }

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

    const source  = this.audioCtx.createMediaStreamSource(this.micStream);
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

    // Beat playback
    this.player.play(this.track as any);

    // MediaRecorder — détection du format supporté par le navigateur
    this.chunks = [];
    this.recordingMimeType = this.detectMimeType();
    const recorderOptions: MediaRecorderOptions = this.recordingMimeType
      ? { mimeType: this.recordingMimeType }
      : {};
    this.mediaRecorder = new MediaRecorder(this.micStream, recorderOptions);
    this.mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.mediaRecorder.onstop = () => this.onRecordingStop();
    this.mediaRecorder.start(100);

    // Timer
    this.recordingStartTime = Date.now();
    this.timer.set(0);
    this.timerInterval = setInterval(() => {
      const t = this.timer() + 1;
      this.timer.set(t);
      this.cdr.markForCheck();
      if (t >= this.MAX_SECONDS) this.stopRecording();
    }, 1000);

    this.state.set('recording');
    this.cdr.markForCheck();
    this.drawVisualizer();
  }

  stopRecording(): void {
    const elapsed = (Date.now() - this.recordingStartTime) / 1000;
    if (elapsed < this.MIN_SECONDS) {
      this.recordingTooShort = true;
      this.errorMsg.set(
        `Enregistrement trop court (${Math.floor(elapsed)}s). Minimum requis : ${this.MIN_SECONDS} secondes.`
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

  playResult(): void {
    const tl = this.resultTopline();
    if (!tl || this.loadingAudio()) return;

    // Si déjà chargé en blob, toggle play/pause
    if (this.resultBlobUrl && this.player.currentTrack()?.stream_url === this.resultBlobUrl) {
      this.player.togglePlay();
      return;
    }

    // Fetch avec JWT (connecté) ou X-Guest-Session (guest)
    this.loadingAudio.set(true);
    this.cdr.markForCheck();
    const authHeader: Record<string, string> = this.isGuest()
      ? { 'X-Guest-Session': this.guestSvc.sessionId() }
      : { 'Authorization': `Bearer ${this.auth.getToken()}` };
    this.http.get(`${environment.apiUrl}${tl.stream_url}`, {
      headers:      authHeader,
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        if (this.resultBlobUrl) URL.revokeObjectURL(this.resultBlobUrl);
        this.resultBlobUrl = URL.createObjectURL(blob);
        this.player.play({
          id:            tl.id,
          title:         `Topline — aperçu`,
          composer_user: tl.artist_user as any,
          stream_url:      this.resultBlobUrl,
          full_stream_url: null,
          image_file:    this.track.image_file,
          bpm: 0, key: '', style: '', price_mp3: 0, tags: [], is_approved: false,
          playlist_count: 0, first_playlist_image: null,
        });
        this.loadingAudio.set(false);
        this.cdr.markForCheck();
      },
      error: () => {
        this.errorMsg.set('Impossible de charger l\'audio.');
        this.loadingAudio.set(false);
        this.cdr.markForCheck();
      },
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
    this.resultTopline.set(null);
    this.isPublished.set(false);
    this.loadingAudio.set(false);
    this.errorMsg.set(null);
    this.timer.set(0);
    this.guestSentTopline.set(false);
    this._guestPolling = false;
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
        ctx.fillStyle = `hsl(${260 + i * 0.5}, 80%, 60%)`;
        ctx.fillRect(x, canvas.height - h, barW, h);
        x += barW + 1;
      }
    };
    draw();
  }

  formatTimer(s: number): string {
    const m = Math.floor(s / 60);
    return `${m}:${(s % 60).toString().padStart(2, '0')}`;
  }

  // ── Calibration ──────────────────────────────────────────────────────────────

  startCalibration(): void {
    if (this._calibCtx || this.calibrating()) return;
    this._calibBeatTimes = [];
    this._calibTapTimes  = [];
    this.calibTapCount.set(0);

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
    }

    this._calibCtx?.close();
    this._calibCtx      = null;
    this._calibBeatTimes = [];
    this._calibTapTimes  = [];
    this.cdr.markForCheck();
  }

  cancelCalibration(): void {
    if (!this.calibrating()) return;
    this.calibrating.set(false);
    this._calibCtx?.close();
    this._calibCtx      = null;
    this._calibBeatTimes = [];
    this._calibTapTimes  = [];
    this.cdr.markForCheck();
  }

  resetCalibration(): void {
    localStorage.removeItem('laprod_latency_ms');
    this.calibResult.set(null);
    this._latencyHintMs = 0;
    this.cdr.markForCheck();
  }

  ngOnDestroy(): void {
    this.clearTimerAndMic();
    this.cancelCalibration();
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    if (this.resultBlobUrl) URL.revokeObjectURL(this.resultBlobUrl);
  }

}
