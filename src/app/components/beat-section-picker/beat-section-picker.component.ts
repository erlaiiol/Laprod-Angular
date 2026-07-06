import {
  Component, Input, Output, EventEmitter, OnInit, OnDestroy,
  ChangeDetectionStrategy, ChangeDetectorRef, inject, signal, computed,
  ViewChildren, QueryList, ElementRef, AfterViewInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  BeatExtenderService, BeatAnalysis, BeatSection, InsertionMode,
} from '../../services/beat-extender.service';
import { NativeShellService } from '../../services/native-shell.service';

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

  /** Émet le WAV blob étendu — le parent le stocke et ferme le picker. */
  @Output() extended  = new EventEmitter<Blob>();
  @Output() cancelled = new EventEmitter<void>();

  @ViewChildren('sectionCanvas') canvasRefs!: QueryList<ElementRef<HTMLCanvasElement>>;

  // ── Signaux ───────────────────────────────────────────────────────────────────

  loading      = signal(true);
  errorMsg     = signal<string | null>(null);
  analysis     = signal<BeatAnalysis | null>(null);
  rawSamples   = signal<Float32Array | null>(null);
  sampleRate   = signal(44_100);
  selectedIdx  = signal<number | null>(null);
  insertMode   = signal<InsertionMode>('after');
  previewing   = signal(false);

  readonly sections   = computed(() => this.analysis()?.sections ?? []);
  readonly canApply   = computed(() => this.selectedIdx() !== null);

  /** Durée actuelle du beat utilisable (avant extension). */
  readonly currentDurationSec = computed(() => {
    const a = this.analysis();
    if (!a) return 0;
    return a.usableSamples / this.sampleRate();
  });

  /** Durée estimée après extension + plafond (approximation mode 'end'). */
  readonly extendedDurationSec = computed(() => {
    const a   = this.analysis();
    const idx = this.selectedIdx();
    if (!a || idx === null) return null;
    const section      = a.sections[idx];
    const xfadeSamples = Math.round(a.samplesPerMeasure * 0.5); // CROSSFADE_MEASURES
    const rawLen       = a.usableSamples + section.lengthSamples - xfadeSamples;
    return Math.min(rawLen, a.maxDurationSamples) / this.sampleRate();
  });

  /** Vrai si l'extension dépasserait le plafond et sera tronquée. */
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
  private _popBackHandler: (() => void) | null = null;

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  async ngOnInit(): Promise<void> {
    // Overlay plein écran : le bouton retour Android doit l'annuler plutôt que
    // quitter l'app ou remonter au handler du parent (mobile-studio).
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
    } catch {
      this.errorMsg.set('Impossible d\'analyser le beat. Vérifiez votre connexion.');
      this.loading.set(false);
      this.cdr.markForCheck();
    }
  }

  ngAfterViewInit(): void {
    // Premier dessin des waveforms quand les canvas sont dans le DOM
    this.canvasRefs.changes.subscribe(() => this._drawAllWaveforms());
    this._drawAllWaveforms();
  }

  // ── Sélection & mode ─────────────────────────────────────────────────────────

  selectSection(idx: number): void {
    this.selectedIdx.set(this.selectedIdx() === idx ? null : idx);
    this.cdr.markForCheck();
  }

  setMode(mode: InsertionMode): void {
    this.insertMode.set(mode);
    this.cdr.markForCheck();
  }

  // ── Aperçu du beat étendu ─────────────────────────────────────────────────────

  async previewExtended(): Promise<void> {
    this._stopPreview();
    const idx = this.selectedIdx();
    const a   = this.analysis();
    const raw = this.rawSamples();
    if (idx === null || !a || !raw) return;

    const blob = this.svc.createExtendedBeat(raw, this.sampleRate(), a, idx, this.insertMode());
    const ab   = await blob.arrayBuffer();

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
    const blob = this.svc.createExtendedBeat(raw, this.sampleRate(), a, idx, this.insertMode());
    this.extended.emit(blob);
  }

  // ── Waveforms ─────────────────────────────────────────────────────────────────

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

    const W    = canvas.width;
    const H    = canvas.height;
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
    const n = name.replace(/\s+\d+$/, '');   // retire le numéro éventuel
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
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  }

  ngOnDestroy(): void {
    this._popBackHandler?.(); this._popBackHandler = null;
    this._stopPreview();
  }
}
