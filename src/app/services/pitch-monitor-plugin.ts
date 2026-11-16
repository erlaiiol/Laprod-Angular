import { registerPlugin }   from '@capacitor/core';
import { InjectionToken }  from '@angular/core';

export interface PitchEvent  { hz: number; correction: number }
export interface LevelEvent  { rms: number }

export interface SessionResult {
  pcmBase64:  string;
  sampleRate: number;
  channels:   number;
  format:     'float32' | 'int16';
  /** iOS, beat natif uniquement : position du beat (s) correspondant au 1er
   *  échantillon enregistré, latences casque NON compensées. */
  firstSampleBeatSec?: number;
}

/**
 * Chaîne voix appliquée au retour casque, en temps réel, côté natif — miroir
 * simplifié de la chaîne d'export (MobileAudioProcessorService._applyVocalChain) :
 * coupe-bas ("boue"), présence, clarté, réverb, volume de piste.
 */
export interface VoiceFx {
  lowCutHz:   number;
  presenceDb: number;
  clarityDb:  number;
  reverbWet:  number;   // 0–1
  volume:     number;   // gain linéaire de la piste
}

/** Retour de startSession (iOS). Android ne renvoie rien. */
export interface StartSessionInfo {
  /** true si le beat est joué par le moteur natif (même horloge que le micro). */
  nativeBeat?:      boolean;
  /** Délai (ms) avant le départ effectif du beat natif. */
  startInMs?:       number;
  /** Latences rapportées par le système (Bluetooth inclus côté sortie). */
  outputLatencyMs?: number;
  inputLatencyMs?:  number;
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
    /** iOS : chemin/URI file:// du beat à jouer dans le moteur natif. */
    beatPath?:      string;
    /** iOS : position du beat (s) au départ de la lecture native. */
    beatStartSec?:  number;
    beatVolume?:    number;
    /** iOS : départ du beat (et de l'enregistrement) différé de N ms — décompte. */
    startDelayMs?:  number;
    /** iOS : le beat boucle (échauffement). */
    loopBeat?:      boolean;
    /** false = micro ouvert pour le retour casque uniquement, rien n'est stocké. Défaut true. */
    record?:        boolean;
    /** Chaîne voix du retour casque (modifiable ensuite via setVoiceFx). */
    fx?:            VoiceFx;
  }): Promise<StartSessionInfo | void>;

  /** Met à jour la chaîne voix du retour casque — effet immédiat (iOS et Android). */
  setVoiceFx(fx: VoiceFx): Promise<void>;

  /** iOS uniquement — volume du beat natif en cours de session. */
  setBeatVolume(opts: { volume: number }): Promise<void>;

  stopSession(): Promise<SessionResult>;

  checkPermission():   Promise<{ microphone: 'granted' | 'denied' | 'prompt' }>;
  requestPermission(): Promise<{ microphone: 'granted' | 'denied' }>;

  /** Détecte le type de périphérique audio branché.
   * 'bluetooth' = HFP/SCO ; 'bluetooth-a2dp' = profil musique. Les deux permettent
   * le monitoring (avec la latence du Bluetooth, ~150-250 ms). */
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
