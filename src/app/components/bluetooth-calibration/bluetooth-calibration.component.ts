import {
  Component, Output, EventEmitter, OnInit, OnDestroy,
  ChangeDetectionStrategy, ChangeDetectorRef, inject, signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { NativeShellService } from '../../services/native-shell.service';

// ─── Algorithme de mesure ──────────────────────────────────────────────────
//
// On joue N_BEATS clics de métronome à BPM_CAL BPM via AudioContext (timing précis).
// L'utilisateur tape en rythme avec ce qu'il ENTEND (son retardé par la latence BT).
// Pour chaque tap, on calcule la phase dans le cycle de beat :
//   phase = (tapTime − firstBeatTime) mod beatInterval
// La médiane des phases (après warmup) = latence_BT + temps_réaction.
// On soustrait REACTION_MS (constante physiologique ~150 ms) pour isoler la latence.
// Résultat clampé à [0, MAX_LATENCY_MS].

const BPM_CAL       = 100;         // 100 BPM = 600 ms/beat (plus lent → plus facile à taper)
const N_BEATS       = 10;          // beats joués (les 3 premiers servent de warmup)
const WARMUP_TAPS   = 3;           // taps ignorés
const REACTION_MS   = 150;         // temps de réaction humain médian (ms)
const MAX_LATENCY_MS = 600;        // cap de la valeur retournée
const BEAT_INTERVAL = 60_000 / BPM_CAL;  // ms
const CLICK_FREQ_HZ = 880;         // A5 — perçant, distinct du beat musical
const CLICK_DUR_S   = 0.04;

type CalibState = 'intro' | 'playing' | 'result' | 'error';

// ── Composant ─────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-bluetooth-calibration',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './bluetooth-calibration.component.html',
  styleUrls: ['./bluetooth-calibration.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BluetoothCalibrationComponent implements OnInit, OnDestroy {

  @Output() done      = new EventEmitter<number>();   // latence en ms
  @Output() cancelled = new EventEmitter<void>();

  // ── Signaux ───────────────────────────────────────────────────────────────

  state        = signal<CalibState>('intro');
  tapCount     = signal(0);
  measuredMs   = signal<number | null>(null);
  beatsLeft    = signal(N_BEATS);
  tapFeedback  = signal(false);   // pulse visuel au tap

  private readonly cdr         = inject(ChangeDetectorRef);
  private readonly nativeShell = inject(NativeShellService);
  private _popBackHandler: (() => void) | null = null;

  // ── Audio internals ───────────────────────────────────────────────────────

  private _ctx:              AudioContext | null = null;
  private _firstBeatTime:    number = 0;          // AudioContext.currentTime du 1er beat
  private _taps:             number[] = [];       // times relatifs au 1er beat (secondes)
  private _beatTimers:       ReturnType<typeof setTimeout>[] = [];  // updates UI beatsLeft
  private _endTimer:         ReturnType<typeof setTimeout> | null = null;

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  ngOnInit(): void {
    // Overlay plein écran : le bouton retour Android doit l'annuler plutôt que
    // quitter l'app ou remonter au handler du parent (mobile-studio).
    this._popBackHandler = this.nativeShell.pushBackHandler(() => {
      this.cancel();
      return true;
    });
  }

  // ── Démarrage ─────────────────────────────────────────────────────────────

  async start(): Promise<void> {
    this._reset();

    try {
      this._ctx = new AudioContext();
      if (this._ctx.state === 'suspended') await this._ctx.resume();
    } catch {
      this.state.set('error');
      this.cdr.markForCheck();
      return;
    }

    this.state.set('playing');
    this.tapCount.set(0);
    this.beatsLeft.set(N_BEATS);
    this.cdr.markForCheck();

    this._scheduleBeats();
  }

  // ── Tap utilisateur ───────────────────────────────────────────────────────

  onTap(): void {
    if (this.state() !== 'playing' || !this._ctx) return;
    this._taps.push(this._ctx.currentTime - this._firstBeatTime);
    this.tapCount.update(n => n + 1);

    // Feedback visuel bref
    this.tapFeedback.set(true);
    setTimeout(() => { this.tapFeedback.set(false); this.cdr.markForCheck(); }, 80);
    this.cdr.markForCheck();
  }

  // ── Application du résultat ───────────────────────────────────────────────

  apply(): void {
    const ms = this.measuredMs();
    if (ms !== null) this.done.emit(ms);
  }

  retry(): void { this.start(); }

  // ── Annulation ────────────────────────────────────────────────────────────

  cancel(): void {
    this._reset();
    this.cancelled.emit();
  }

  // ── Scheduling des beats ──────────────────────────────────────────────────

  private _scheduleBeats(): void {
    if (!this._ctx) return;

    // Premier beat dans 1 s — laisse le temps à AudioContext de chauffer
    const startOffset = 1.0;
    this._firstBeatTime = this._ctx.currentTime + startOffset;
    const beatIntervalS = BEAT_INTERVAL / 1000;

    for (let i = 0; i < N_BEATS; i++) {
      const t = this._firstBeatTime + i * beatIntervalS;
      this._scheduleClick(t);

      // Mettre à jour beatsLeft via setTimeout (approximatif, uniquement pour l'UI)
      const delayMs = (startOffset + i * beatIntervalS) * 1000;
      this._beatTimers.push(setTimeout(() => {
        this.beatsLeft.update(n => Math.max(0, n - 1));
        this.cdr.markForCheck();
      }, delayMs));
    }

    // Fin de la session : calculer le résultat
    const totalMs = (startOffset + N_BEATS * beatIntervalS) * 1000 + 300;
    this._endTimer = setTimeout(() => this._computeResult(), totalMs);
  }

  private _scheduleClick(t: number): void {
    if (!this._ctx) return;
    const osc  = this._ctx.createOscillator();
    const gain = this._ctx.createGain();
    osc.frequency.value = CLICK_FREQ_HZ;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.6, t + 0.005);
    gain.gain.exponentialRampToValueAtTime(0.001, t + CLICK_DUR_S);
    osc.connect(gain).connect(this._ctx.destination);
    osc.start(t);
    osc.stop(t + CLICK_DUR_S + 0.01);
  }

  // ── Calcul de la latence ──────────────────────────────────────────────────

  private _computeResult(): void {
    const beatIntervalS = BEAT_INTERVAL / 1000;
    const validTaps = this._taps.slice(WARMUP_TAPS);

    if (validTaps.length < 2) {
      // Pas assez de taps
      this.state.set('error');
      this.cdr.markForCheck();
      return;
    }

    // Phase de chaque tap dans le cycle de beat
    const phases = validTaps.map(t => {
      const phase = ((t % beatIntervalS) + beatIntervalS) % beatIntervalS;
      return phase * 1000;  // → ms
    });

    // Médiane (robuste aux outliers)
    const sorted = [...phases].sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];

    // Soustraction de la réaction humaine, clamp [0, MAX]
    const latency = Math.round(Math.max(0, Math.min(MAX_LATENCY_MS, median - REACTION_MS)));

    this.measuredMs.set(latency);
    this.state.set('result');
    this.cdr.markForCheck();
  }

  // ── Helpers template ──────────────────────────────────────────────────────

  qualityLabel(ms: number): string {
    if (ms < 80)  return 'Excellent';
    if (ms < 150) return 'Bon';
    if (ms < 250) return 'Moyen';
    return 'Élevé';
  }

  qualityColor(ms: number): string {
    if (ms < 80)  return '#4caf81';
    if (ms < 150) return '#e5c14b';
    if (ms < 250) return '#f97316';
    return '#e5323c';
  }

  readonly totalTaps   = N_BEATS;
  readonly neededTaps  = WARMUP_TAPS + 1;

  // ── Cleanup ───────────────────────────────────────────────────────────────

  private _reset(): void {
    this._beatTimers.forEach(clearTimeout);
    this._beatTimers = [];
    if (this._endTimer) { clearTimeout(this._endTimer); this._endTimer = null; }
    this._ctx?.close().catch(() => {});
    this._ctx         = null;
    this._taps        = [];
    this._firstBeatTime = 0;
  }

  ngOnDestroy(): void {
    this._popBackHandler?.(); this._popBackHandler = null;
    this._reset();
  }
}
