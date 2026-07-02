import {
  Component, Input, Output, EventEmitter, OnDestroy,
  signal, inject, ChangeDetectionStrategy, ChangeDetectorRef,
  ElementRef, ViewChild, AfterViewInit
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { TrackDetail, PublishedTopline } from '../../services/track.service';
import { ToplineService } from '../../services/topline.service';
import { ToplineStatusService } from '../../services/topline-status.service';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { environment } from '../../../environments/environment';

type RecorderState = 'idle' | 'recording' | 'processing' | 'result';

@Component({
  selector: 'app-topline-recorder',
  standalone: true,
  imports: [CommonModule, FormsModule],
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
  loadingAudio  = signal(false);

  useAutotune  = false;
  useMonitor   = false;
  description  = '';

  private toplineSvc       = inject(ToplineService);
  private toplineStatusSvc = inject(ToplineStatusService);
  private player           = inject(PlayerService);
  private cdr              = inject(ChangeDetectorRef);
  readonly auth            = inject(AuthService);
  private http             = inject(HttpClient);

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

  ngAfterViewInit(): void {}

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
      this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch {
      this.errorMsg.set('Accès au microphone refusé. Autorisez le micro dans votre navigateur.');
      this.cdr.markForCheck();
      return;
    }

    // Web Audio API — visualizer
    this.audioCtx = new AudioContext();
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

    const mimeType = this.recordingMimeType || 'audio/webm';
    const ext      = mimeType.includes('mp4') ? 'mp4' : mimeType.includes('ogg') ? 'ogg' : 'webm';
    const blob     = new Blob(this.chunks, { type: mimeType });
    const fd       = new FormData();
    fd.append('voice_file',   blob, `voice.${ext}`);
    fd.append('track_id',     String(this.track.id));
    fd.append('use_autotune', String(this.useAutotune));
    if (this.description) fd.append('description', this.description);

    const imageUrl = this.track.image_file
      ? `${environment.apiUrl}/db_assets/${this.track.image_file}`
      : null;
    this.toplineStatusSvc.openForUpload(this.track.id, this.track.title, imageUrl);

    this.toplineSvc.uploadTopline(fd).subscribe({
      next: (res) => {
        if (res.success && res.data?.job_id) {
          this.toplineStatusSvc.startPolling(res.data.job_id);
          this.state.set('idle');
          this.closed.emit();
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

    // Fetch avec JWT (topline non publiée = accès protégé)
    this.loadingAudio.set(true);
    this.cdr.markForCheck();
    this.http.get(`${environment.apiUrl}${tl.stream_url}`, {
      headers:      { Authorization: `Bearer ${this.auth.getToken()}` },
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

  resetToIdle(): void {
    if (this.resultBlobUrl) { URL.revokeObjectURL(this.resultBlobUrl); this.resultBlobUrl = null; }
    this.resultTopline.set(null);
    this.isPublished.set(false);
    this.loadingAudio.set(false);
    this.errorMsg.set(null);
    this.timer.set(0);
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

  ngOnDestroy(): void {
    this.clearTimerAndMic();
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    if (this.resultBlobUrl) URL.revokeObjectURL(this.resultBlobUrl);
  }

}
