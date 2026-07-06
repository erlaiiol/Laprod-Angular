import {
  Component, Input, Output, EventEmitter, signal,
  ChangeDetectionStrategy, inject, OnDestroy, OnChanges,
  ViewChild, ElementRef, SimpleChanges, AfterViewChecked,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule }  from '@angular/forms';
import { VocalTrack, MobileMaquetteService } from '../../../services/mobile-maquette.service';
import type { TrackSettings } from '../../../services/mobile-maquette.service';
import { MobileAudioProcessorService } from '../../../services/mobile-audio-processor.service';

@Component({
  selector: 'app-mobile-track-item',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './mobile-track-item.component.html',
  styleUrls: ['./mobile-track-item.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MobileTrackItemComponent implements OnChanges, AfterViewChecked, OnDestroy {

  @Input({ required: true }) track!: VocalTrack;
  @Input() trackKey = '';

  @Output() startRecord = new EventEmitter<string>();
  @Output() remove      = new EventEmitter<string>();
  @Output() punchIn     = new EventEmitter<string>();

  @ViewChild('wfCanvas')   wfCanvasRef?: ElementRef<HTMLCanvasElement>;
  @ViewChild('nameInput')  nameInputRef?: ElementRef<HTMLInputElement>;

  readonly expanded         = signal(false);
  readonly editingName      = signal(false);
  readonly isPlayingPreview = signal(false);
  editNameValue             = '';

  private _audioCtx:       AudioContext | null          = null;
  private _sourceNode:     AudioBufferSourceNode | null = null;
  private _lastWaveformLen = 0;

  private readonly service   = inject(MobileMaquetteService);
  private readonly processor = inject(MobileAudioProcessorService);

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['track']) this._lastWaveformLen = 0;
  }

  ngAfterViewChecked(): void {
    const wf = this.track.waveform;
    if (wf.length && wf.length !== this._lastWaveformLen) {
      this._lastWaveformLen = wf.length;
      this._drawWaveform(wf);
    }
    // Focus automatique sur l'input de renommage à l'ouverture
    if (this.editingName() && this.nameInputRef?.nativeElement) {
      this.nameInputRef.nativeElement.focus();
    }
  }

  // ── Waveform ─────────────────────────────────────────────────────────────────

  private _drawWaveform(wf: number[]): void {
    const canvas = this.wfCanvasRef?.nativeElement;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W     = canvas.width;
    const H     = canvas.height;
    // 12 px en bas réservés aux marqueurs de temps si la piste est > 30 s
    const showMarkers = this.track.duration >= 30;
    const waveH = showMarkers ? H - 13 : H;
    const barW  = W / wf.length;

    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#A51929' + '66';

    for (let i = 0; i < wf.length; i++) {
      const barH = Math.max(2, wf[i] * waveH);
      ctx.fillRect(i * barW + 0.5, (waveH - barH) / 2, Math.max(1, barW - 1), barH);
    }

    if (!showMarkers) return;

    // Graduations temporelles : 30 s si durée ≤ 2 min, sinon 60 s
    const duration = this.track.duration;
    const step     = duration <= 120 ? 30 : 60;
    ctx.font      = '7px system-ui, -apple-system, sans-serif';
    ctx.textAlign = 'center';

    for (let t = step; t < duration; t += step) {
      const x = (t / duration) * W;
      ctx.fillStyle = 'rgba(255,255,255,0.18)';
      ctx.fillRect(Math.round(x), waveH + 1, 1, 4);
      ctx.fillStyle = 'rgba(255,255,255,0.28)';
      ctx.fillText(this._fmtTime(t), x, H - 1);
    }
  }

  private _fmtTime(s: number): string {
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  // ── Renommage double-tap ──────────────────────────────────────────────────────

  startRename(): void {
    this.editNameValue = this.track.name;
    this.editingName.set(true);
  }

  confirmRename(): void {
    const trimmed = this.editNameValue.trim();
    if (trimmed) this.service.renameTrack(this.track.id, trimmed);
    this.editingName.set(false);
  }

  cancelRename(): void {
    this.editingName.set(false);
  }

  onNameKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter')  { event.preventDefault(); this.confirmRename(); }
    if (event.key === 'Escape') { event.preventDefault(); this.cancelRename();  }
  }

  // ── Presets EQ / Réverb ───────────────────────────────────────────────────────

  readonly clarityPresets: ReadonlyArray<{ label: string; value: number }> = [
    { label: 'Sombre',      value: 0 },
    { label: 'Medium',      value: 3 },
    { label: 'Voix claire', value: 7 },
  ];

  readonly reverbPresets: ReadonlyArray<{ label: string; value: number }> = [
    { label: 'Discret',  value: 0.05 },
    { label: 'Réaliste', value: 0.12 },
    { label: 'Concert',  value: 0.20 },
  ];

  setClarity(v: number): void { this.service.updateSettings(this.track.id, { clarityDb: v }); }
  setReverb(v: number):  void { this.service.updateSettings(this.track.id, { reverbWet: v }); }

  isActiveClarity(v: number): boolean { return Math.abs(this.track.settings.clarityDb - v) < 0.1; }
  isActiveReverb(v: number):  boolean { return Math.abs(this.track.settings.reverbWet - v) < 0.005; }

  // ── Labels lisibles ──────────────────────────────────────────────────────────

  volumeLabel(v: number): string {
    const db = Math.round(20 * Math.log10(v) * 10) / 10;
    if (!isFinite(db)) return '-∞ dB';
    return db >= 0 ? `+${db} dB` : `${db} dB`;
  }

  // ── Autotune toggle ──────────────────────────────────────────────────────────

  async toggleAutotune(): Promise<void> {
    const newVal = !this.track.settings.useAutotune;
    this.service.updateSettings(this.track.id, { useAutotune: newVal });
    if (newVal && !this.track.processedBlob) {
      await this.service.ensureAutotune(this.track.id, this.trackKey);
    }
  }

  // ── Lecture isolée ───────────────────────────────────────────────────────────

  async previewTrack(): Promise<void> {
    if (this.isPlayingPreview()) { this._stopPreview(); return; }

    const activeBlob = (this.track.settings.useAutotune && this.track.processedBlob)
      ? this.track.processedBlob
      : this.track.rawBlob;
    if (!activeBlob) return;

    try {
      // Utilise processor.decodeBlob() — gère le PCM natif brut (iOS float32,
      // Android int16) que AudioContext.decodeAudioData refuse sans container.
      this._audioCtx = new AudioContext();
      const buf = await this.processor.decodeBlob(activeBlob);
      const src = this._audioCtx.createBufferSource();
      src.buffer = buf;
      src.connect(this._audioCtx.destination);
      src.onended = () => this._stopPreview();
      src.start(0);
      this._sourceNode = src;
      this.isPlayingPreview.set(true);
    } catch { this._stopPreview(); }
  }

  private _stopPreview(): void {
    try { this._sourceNode?.stop(); } catch { /* ignore */ }
    this._sourceNode = null;
    this._audioCtx?.close();
    this._audioCtx = null;
    this.isPlayingPreview.set(false);
  }

  // ── Slider helpers ───────────────────────────────────────────────────────────

  onVolume(event: Event): void {
    this.service.updateSettings(this.track.id, { volume: +(event.target as HTMLInputElement).value });
  }

  ngOnDestroy(): void { this._stopPreview(); }
}
