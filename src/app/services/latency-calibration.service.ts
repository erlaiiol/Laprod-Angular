import { Injectable } from '@angular/core';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface CalibrationEntry {
  latencyMs:  number;
  deviceType: 'wired' | 'bluetooth' | 'bluetooth-a2dp' | 'none';
  ts:         number;   // Date.now() au moment de la calibration
}

// ── Service ───────────────────────────────────────────────────────────────────
//
// Stocke la latence audio mesurée lors de la calibration Bluetooth.
// Utilisée comme `latencyHintMs` dans MixAndExportOptions pour rogner
// le début du vocal enregistré et le réaligner avec le beat.

@Injectable({ providedIn: 'root' })
export class LatencyCalibrationService {

  private readonly KEY = 'laprod_audio_latency_v1';

  // ── Lecture ───────────────────────────────────────────────────────────────

  getEntry(): CalibrationEntry | null {
    try {
      const raw = localStorage.getItem(this.KEY);
      return raw ? (JSON.parse(raw) as CalibrationEntry) : null;
    } catch {
      return null;
    }
  }

  /** Latence en ms à utiliser pour rogner le vocal. 0 si non calibré. */
  get latencyMs(): number {
    return this.getEntry()?.latencyMs ?? 0;
  }

  get deviceType(): CalibrationEntry['deviceType'] | null {
    return this.getEntry()?.deviceType ?? null;
  }

  hasCalibration(): boolean {
    return this.getEntry() !== null;
  }

  // ── Écriture ──────────────────────────────────────────────────────────────

  save(latencyMs: number, deviceType: CalibrationEntry['deviceType']): void {
    const entry: CalibrationEntry = { latencyMs, deviceType, ts: Date.now() };
    localStorage.setItem(this.KEY, JSON.stringify(entry));
  }

  clear(): void {
    localStorage.removeItem(this.KEY);
  }
}
