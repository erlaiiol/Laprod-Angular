import { registerPlugin }   from '@capacitor/core';
import { InjectionToken }  from '@angular/core';

export interface PitchEvent  { hz: number; correction: number }
export interface LevelEvent  { rms: number }

export interface SessionResult {
  pcmBase64:  string;
  sampleRate: number;
  channels:   number;
  format:     'float32' | 'int16';
}

export interface InterruptedResult extends SessionResult {
  partial: true;
}

export interface PitchMonitorPlugin {
  startSession(opts: {
    useMonitor:     boolean;
    voiceGain:      number;
    reverbWet:      number;
    trackKey:       string;
    /** Active la correction de hauteur temps-réel sur le monitoring (casque filaire requis). */
    monitorAutotune?: boolean;
    /** Vitesse de correction : 'natural' (τ≈75ms), 'precise' (τ≈25ms), 'robot' (snap instantané). Défaut : 'natural'. */
    retuneSpeed?:   'natural' | 'precise' | 'robot';
  }): Promise<void>;

  stopSession(): Promise<SessionResult>;

  checkPermission():   Promise<{ microphone: 'granted' | 'denied' | 'prompt' }>;
  requestPermission(): Promise<{ microphone: 'granted' | 'denied' }>;

  /** Détecte le type de périphérique audio branché.
   * 'bluetooth' = HFP/SCO (monitoring capable) ; 'bluetooth-a2dp' = lecture seule. */
  checkHeadphones(): Promise<{ type: 'wired' | 'bluetooth' | 'bluetooth-a2dp' | 'none' }>;

  addListener(event: 'pitch',             handler: (data: PitchEvent)       => void): Promise<{ remove: () => void }>;
  addListener(event: 'level',             handler: (data: LevelEvent)       => void): Promise<{ remove: () => void }>;
  addListener(event: 'sessionInterrupted', handler: (data: InterruptedResult) => void): Promise<{ remove: () => void }>;
  removeAllListeners(): Promise<void>;
}

export const PitchMonitor = registerPlugin<PitchMonitorPlugin>('PitchMonitor');

/** Token DI permettant de remplacer PitchMonitor dans les tests. */
export const PITCH_MONITOR = new InjectionToken<PitchMonitorPlugin>('PitchMonitor', {
  factory: () => PitchMonitor,
});
