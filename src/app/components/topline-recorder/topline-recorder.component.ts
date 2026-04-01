import {
  Component, Input, Output, EventEmitter, OnDestroy,
  signal, inject, ChangeDetectionStrategy, ChangeDetectorRef,
  ElementRef, ViewChild, AfterViewInit
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TrackDetail, PublishedTopline } from '../../services/track.service';
import { ToplineService } from '../../services/topline.service';
import { PlayerService } from '../../services/player.service';

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

  state      = signal<RecorderState>('idle');
  timer      = signal(0);
  errorMsg   = signal<string | null>(null);
  resultTopline = signal<PublishedTopline | null>(null);

  useAutotune  = false;
  useMonitor   = false;
  description  = '';

  private toplineSvc = inject(ToplineService);
  private player     = inject(PlayerService);
  private cdr        = inject(ChangeDetectorRef);

  private mediaRecorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
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

  async startRecording(): Promise<void> {
    this.errorMsg.set(null);
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

    // MediaRecorder
    this.chunks = [];
    this.mediaRecorder = new MediaRecorder(this.micStream);
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

    const blob = new Blob(this.chunks, { type: 'audio/webm' });
    const fd   = new FormData();
    fd.append('voice_file',   blob, 'voice.webm');
    fd.append('track_id',     String(this.track.id));
    fd.append('use_autotune', String(this.useAutotune));
    if (this.description) fd.append('description', this.description);

    this.toplineSvc.uploadTopline(fd).subscribe({
      next: (res) => {
        if (res.success && res.data?.topline) {
          this.resultTopline.set(res.data.topline);
          this.state.set('result');
        } else {
          this.errorMsg.set(res.feedback?.message ?? 'Erreur lors du traitement.');
          this.state.set('idle');
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.errorMsg.set('Impossible de contacter le serveur.');
        this.state.set('idle');
        this.cdr.markForCheck();
      }
    });
  }

  playResult(): void {
    const tl = this.resultTopline();
    if (!tl) return;
    this.player.play({
      id:            tl.id,
      title:         `Topline (aperçu)`,
      composer_user: tl.artist_user as any,
      stream_url:    tl.stream_url,
      image_file:    this.track.image_file,
      bpm: 0, key: '', style: '', price_mp3: 0, tags: [], is_approved: false,
    });
  }

  publishResult(): void {
    const tl = this.resultTopline();
    if (!tl) return;
    this.toplineSvc.publishTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success && res.data?.topline) {
          this.published.emit(res.data.topline);
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
    this.resultTopline.set(null);
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
  }

}
