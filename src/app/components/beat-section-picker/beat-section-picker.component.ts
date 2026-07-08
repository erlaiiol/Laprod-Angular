import {
  Component, Input, Output, EventEmitter, OnInit, OnDestroy,
  ChangeDetectionStrategy, ChangeDetectorRef, inject, signal, computed,
  ViewChildren, ViewChild, QueryList, ElementRef, AfterViewInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  BeatExtenderService, BeatAnalysis, BeatSection, InsertionMode, ExtendedBeatResult,
} from '../../services/beat-extender.service';
import { NativeShellService } from '../../services/native-shell.service';
import { PlayerService }      from '../../services/player.service';

// ── Composant ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-beat-section-picker',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './beat-section-picker.component.html',
  styleUrls: ['./beat-section-picker.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BeatSectionPickerComponent implements OnInit, AfterViewInit, OnDestroy {

  @Input({ required: true }) beatUrl!:     string;
  @Input({ required: true }) accessToken!: string;
  @Input({ required: true }) bpm!:         number;

  /** Émet le résultat étendu (blob + métadonnées de split) au parent. */
  @Output() extended  = new EventEmitter<ExtendedBeatResult>();
  @Output() cancelled = new EventEmitter<void>();

  @ViewChildren('sectionCanvas') canvasRefs!: QueryList<ElementRef<HTMLCanvasElement>>;
  @ViewChild('globalCanvas')     globalCanvasRef?: ElementRef<HTMLCanvasElement>;

  // ── Signaux ───────────────────────────────────────────────────────────────────

  loading        = signal(true);
  errorMsg       = signal<string | null>(null);
  analysis       = signal<BeatAnalysis | null>(null);
  rawSamples     = signal<Float32Array | null>(null);
  sampleRate     = signal(44_100);
  selectedIdx    = signal<number | null>(null);
  insertMode     = signal<InsertionMode>('after');
  previewing     = signal(false);
  previewingIdx  = signal<number | null>(null);  // index de la section en écoute

  readonly sections   = computed(() => this.analysis()?.sections ?? []);
  readonly canApply   = computed(() => this.selectedIdx() !== null);

  readonly currentDurationSec = computed(() => {
    const a = this.analysis();
    if (!a) return 0;
    return a.usableSamples / this.sampleRate();
  });

  readonly extendedDurationSec = computed(() => {
    const a   = this.analysis();
    const idx = this.selectedIdx();
    if (!a || idx === null) return null;
    const section      = a.sections[idx];
    const xfadeSamples = Math.round(a.samplesPerMeasure * 0.5);
    const rawLen       = a.usableSamples + section.lengthSamples - xfadeSamples;
    return Math.min(rawLen, a.maxDurationSamples) / this.sampleRate();
  });

  readonly wouldBeCapped = computed(() => {
    const a   = this.analysis();
    const idx = this.selectedIdx();
    if (!a || idx === null) return false;
    const section      = a.sections[idx];
    const xfadeSamples = Math.round(a.samplesPerMeasure * 0.5);
    return (a.usableSamples + section.lengthSamples - xfadeSamples) > a.maxDurationSamples;
  });

  // ── Internals ─────────────────────────────────────────────────────────────────

  private _previewCtx:  AudioContext | null = null;
  private _previewSrc:  AudioBufferSourceNode | null = null;
  private readonly svc         = inject(BeatExtenderService);
  private readonly cdr         = inject(ChangeDetectorRef);
  private readonly nativeShell = inject(NativeShellService);
  private readonly player      = inject(PlayerService);
  private _popBackHandler: (() => void) | null = null;

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  async ngOnInit(): Promise<void> {
    this._popBackHandler = this.nativeShell.pushBackHandler(() => {
      this.cancelled.emit();
      return true;
    });

    try {
      const { analysis, rawSamples, sampleRate } = await this.svc.analyzeBeat(
        this.beatUrl,
        this.bpm,
        this.accessToken,
      );
      this.analysis.set(analysis);
      this.rawSamples.set(rawSamples);
      this.sampleRate.set(sampleRate);
      this.loading.set(false);
      this.cdr.markForCheck();
      // Wait one tick for @if (!loading()) to render the canvases into the DOM
      setTimeout(() => {
        this._drawAllWaveforms();
        this._drawGlobalWaveform();
      }, 0);
    } catch {
      this.errorMsg.set('Impossible d\'analyser le beat. Vérifiez votre connexion.');
      this.loading.set(false);
      this.cdr.markForCheck();
    }
  }

  ngAfterViewInit(): void {
    // The section canvases live inside @if (!loading()), so they appear after
    // analysis completes. requestAnimationFrame waits for layout before drawing.
    this.canvasRefs.changes.subscribe(() => {
      requestAnimationFrame(() => {
        this._drawAllWaveforms();
        this._drawGlobalWaveform();
      });
    });
  }

  // ── Sélection & mode ─────────────────────────────────────────────────────────

  selectSection(idx: number): void {
    this.selectedIdx.set(this.selectedIdx() === idx ? null : idx);
    this._drawGlobalWaveform();
    this.cdr.markForCheck();
  }

  setMode(mode: InsertionMode): void {
    this.insertMode.set(mode);
    this.cdr.markForCheck();
  }

  // ── Aperçu d'une section individuelle ────────────────────────────────────────

  async previewSection(idx: number): Promise<void> {
    // Toggle: re-tapper sur la même section arrête l'écoute
    if (this.previewingIdx() === idx) {
      this._stopPreview();
      this.previewingIdx.set(null);
      this.previewing.set(false);
      this.cdr.markForCheck();
      return;
    }

    this._stopPreview();
    this.previewing.set(false);
    this.previewingIdx.set(null);

    const a   = this.analysis();
    const raw = this.rawSamples();
    const sr  = this.sampleRate();
    if (!a || !raw) return;

    const section = a.sections[idx];

    // Stopper toute piste audio en cours (beat du studio ou autre)
    this.player.audioEl.pause();

    try {
      this._previewCtx = new AudioContext();
      const slice = raw.slice(section.startSample, section.startSample + section.lengthSamples);
      const buf   = this._previewCtx.createBuffer(1, slice.length, sr);
      buf.copyToChannel(slice, 0);
      const src = this._previewCtx.createBufferSource();
      src.buffer = buf;
      src.connect(this._previewCtx.destination);
      src.onended = () => {
        this.previewingIdx.set(null);
        this.cdr.markForCheck();
        this._stopPreview();
      };
      src.start(0);
      this._previewSrc = src;
      this.previewingIdx.set(idx);
      this.cdr.markForCheck();
    } catch {
      this.previewingIdx.set(null);
      this.cdr.markForCheck();
    }
  }

  // ── Aperçu du beat étendu ─────────────────────────────────────────────────────

  async previewExtended(): Promise<void> {
    this._stopPreview();
    this.previewingIdx.set(null);

    const idx = this.selectedIdx();
    const a   = this.analysis();
    const raw = this.rawSamples();
    if (idx === null || !a || !raw) return;

    // Stopper toute piste audio en cours
    this.player.audioEl.pause();

    const result = this.svc.createExtendedBeat(raw, this.sampleRate(), a, idx, this.insertMode());
    const ab     = await result.blob.arrayBuffer();

    try {
      this._previewCtx = new AudioContext();
      const buf = await this._previewCtx.decodeAudioData(ab);
      const src = this._previewCtx.createBufferSource();
      src.buffer = buf;
      src.connect(this._previewCtx.destination);
      src.onended = () => {
        this.previewing.set(false);
        this.cdr.markForCheck();
        this._stopPreview();
      };
      src.start(0);
      this._previewSrc = src;
      this.previewing.set(true);
      this.cdr.markForCheck();
    } catch {
      this.previewing.set(false);
    }
  }

  stopPreview(): void {
    this._stopPreview();
    this.previewing.set(false);
    this.previewingIdx.set(null);
    this.cdr.markForCheck();
  }

  private _stopPreview(): void {
    try { this._previewSrc?.stop(); } catch { /* ignore */ }
    this._previewSrc = null;
    this._previewCtx?.close();
    this._previewCtx = null;
  }

  // ── Appliquer ─────────────────────────────────────────────────────────────────

  applyExtension(): void {
    const idx = this.selectedIdx();
    const a   = this.analysis();
    const raw = this.rawSamples();
    if (idx === null || !a || !raw) return;

    this._stopPreview();
    const result = this.svc.createExtendedBeat(raw, this.sampleRate(), a, idx, this.insertMode());
    this.extended.emit(result);
  }

  // ── Waveform globale (vue d'ensemble du beat + section sélectionnée) ──────────

  private _drawGlobalWaveform(): void {
    const canvas = this.globalCanvasRef?.nativeElement;
    const raw    = this.rawSamples();
    const a      = this.analysis();
    if (!canvas || !raw || !a) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const W           = canvas.offsetWidth || 320;
    const H           = 64;
    canvas.width      = W;
    canvas.height     = H;
    const total       = a.usableSamples;
    const selectedIdx = this.selectedIdx();

    ctx.clearRect(0, 0, W, H);

    // 1. Fonds de section alternés + sélection
    for (const s of a.sections) {
      const x0 = Math.round((s.startSample / total) * W);
      const x1 = Math.round(((s.startSample + s.lengthSamples) / total) * W);
      ctx.fillStyle = (selectedIdx === s.index)
        ? 'rgba(229,50,60,0.14)'
        : (s.index % 2 === 0 ? 'rgba(255,255,255,0.022)' : 'rgba(255,255,255,0.04)');
      ctx.fillRect(x0, 0, x1 - x0, H);
    }

    // 2. Barres waveform (1px par barre = résolution maximale)
    for (let b = 0; b < W; b++) {
      const sStart = Math.floor((b / W) * total);
      const sEnd   = Math.min(Math.ceil(((b + 1) / W) * total), total);
      let rms = 0;
      for (let i = sStart; i < sEnd; i++) rms += raw[i] * raw[i];
      rms = Math.sqrt(rms / Math.max(1, sEnd - sStart));
      const barH = Math.max(2, Math.round(rms * 5 * H));

      const samplePos  = (b / W) * total;
      const sel        = selectedIdx !== null ? a.sections[selectedIdx] : null;
      const inSelected = sel !== null && sel !== undefined &&
        samplePos >= sel.startSample &&
        samplePos < sel.startSample + sel.lengthSamples;

      ctx.fillStyle = inSelected ? 'rgba(229,50,60,0.90)' : 'rgba(255,255,255,0.28)';
      ctx.fillRect(b, Math.round((H - barH) / 2), 1, barH);
    }

    // 3. Séparateurs de section + labels
    ctx.font      = '9px system-ui,-apple-system,sans-serif';
    ctx.textAlign = 'center';
    for (const s of a.sections) {
      const x0 = Math.round((s.startSample / total) * W);
      const x1 = Math.round(((s.startSample + s.lengthSamples) / total) * W);

      // Ligne séparatrice
      ctx.strokeStyle = 'rgba(255,255,255,0.10)';
      ctx.lineWidth   = 1;
      ctx.beginPath();
      ctx.moveTo(x0 + 0.5, 0);
      ctx.lineTo(x0 + 0.5, H);
      ctx.stroke();

      // Label court en haut de la section
      const labelX  = x0 + (x1 - x0) / 2;
      const shortNm = s.name.length > 5 ? s.name.slice(0, 4) + '…' : s.name;
      ctx.fillStyle = (selectedIdx === s.index)
        ? 'rgba(229,50,60,0.95)'
        : 'rgba(255,255,255,0.28)';
      ctx.fillText(shortNm, labelX, 11);
    }

    // 4. Encadré rouge autour de la section sélectionnée
    if (selectedIdx !== null && a.sections[selectedIdx]) {
      const sel = a.sections[selectedIdx];
      const x0  = Math.round((sel.startSample / total) * W);
      const x1  = Math.round(((sel.startSample + sel.lengthSamples) / total) * W);
      ctx.strokeStyle = 'rgba(229,50,60,0.70)';
      ctx.lineWidth   = 2;
      ctx.strokeRect(x0 + 1, 1, x1 - x0 - 2, H - 2);
    }
  }

  // ── Waveforms des cartes de section ──────────────────────────────────────────

  private _drawAllWaveforms(): void {
    const secs = this.sections();
    const refs = this.canvasRefs?.toArray() ?? [];
    refs.forEach((ref, i) => {
      if (secs[i]) this._drawWaveform(ref.nativeElement, secs[i]);
    });
  }

  private _drawWaveform(canvas: HTMLCanvasElement, section: BeatSection): void {
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Synchronise la résolution du canvas avec son rendu CSS
    const W = canvas.offsetWidth || 240;
    const H = 48;
    canvas.width  = W;
    canvas.height = H;

    const wf   = section.waveform;
    const barW = W / wf.length;

    ctx.clearRect(0, 0, W, H);

    for (let i = 0; i < wf.length; i++) {
      const barH  = Math.max(2, wf[i] * H * 0.9);
      const alpha = 0.4 + wf[i] * 0.6;
      ctx.fillStyle = `rgba(229, 50, 60, ${alpha.toFixed(2)})`;
      ctx.fillRect(i * barW + 0.5, (H - barH) / 2, Math.max(1, barW - 1.5), barH);
    }
  }

  // ── Helpers template ─────────────────────────────────────────────────────────

  sectionIcon(name: string): string {
    const n = name.replace(/\s+\d+$/, '');
    const icons: Record<string, string> = {
      'Intro':       'bi-play-circle',
      'Couplet':     'bi-music-note',
      'Pré-refrain': 'bi-arrow-up-circle',
      'Refrain':     'bi-star-fill',
      'Pont':        'bi-pause-circle',
      'Outro':       'bi-stop-circle',
    };
    return icons[n] ?? 'bi-music-note';
  }

  energyLabel(s: BeatSection): string {
    const pct = Math.round(s.rms * 1_000);
    if (pct > 70) return 'Fort';
    if (pct > 40) return 'Moyen';
    return 'Calme';
  }

  formatDuration(s: number): string {
    const m   = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  }

  ngOnDestroy(): void {
    this._popBackHandler?.(); this._popBackHandler = null;
    this._stopPreview();
  }
}
