import { Injectable, OnDestroy, signal } from '@angular/core';

/**
 * Métronome audio pour le Mobile Studio.
 *
 * Gère son propre AudioContext + scheduler en avance de phase (lookahead 150 ms,
 * tick toutes les 50 ms) pour minimiser la gigue de timing.
 * Le signal `active` reflète l'état courant et peut être lu directement dans
 * les templates Angular (OnPush compatible).
 *
 * Usage :
 *   metronome.toggle(bpm, audioEl.currentTime);   // démarre ou arrête
 *   metronome.restart(bpm, audioEl.currentTime);  // redémarre (retour d'arrière-plan)
 *   metronome.stop();                             // arrêt garanti (ngOnDestroy du parent)
 */
@Injectable()
export class MobileMetronomeService implements OnDestroy {

  readonly active = signal(false);

  private _ctx:       AudioContext | null                   = null;
  private _scheduler: ReturnType<typeof setInterval> | null = null;
  private _nextNote   = 0;
  private _beatIdx    = 0;

  toggle(bpm: number, audioCurrentTime: number): void {
    if (this.active()) { this.stop(); } else { this._start(bpm, audioCurrentTime); }
  }

  /** Arrête puis redémarre — utile lors d'un retour au premier plan. */
  restart(bpm: number, audioCurrentTime: number): void {
    this.stop();
    this._start(bpm, audioCurrentTime);
  }

  stop(): void {
    clearInterval(this._scheduler!);
    this._scheduler = null;
    this._ctx?.close();
    this._ctx = null;
    this.active.set(false);
  }

  private _start(bpm: number, audioCurrentTime: number): void {
    if (!bpm) return;
    this._ctx         = new AudioContext();
    const beatInterval = 60 / bpm;
    const phase        = audioCurrentTime % beatInterval;
    this._nextNote     = this._ctx.currentTime + (beatInterval - phase);
    this._beatIdx      = 0;
    this._scheduler    = setInterval(() => this._tick(bpm), 50);
    this.active.set(true);
  }

  private _tick(bpm: number): void {
    const ctx = this._ctx;
    if (!ctx) return;
    const beatInterval = 60 / bpm;
    const lookahead    = 0.15;
    while (this._nextNote < ctx.currentTime + lookahead) {
      this._click(this._nextNote, this._beatIdx === 0);
      this._nextNote += beatInterval;
      this._beatIdx   = (this._beatIdx + 1) % 4;
    }
  }

  private _click(when: number, accent: boolean): void {
    const ctx = this._ctx;
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

  ngOnDestroy(): void { this.stop(); }
}
