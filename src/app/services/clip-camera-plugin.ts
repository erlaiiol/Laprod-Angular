import { registerPlugin } from '@capacitor/core';
import { InjectionToken } from '@angular/core';

/**
 * Plugin natif du Mode Clip (docs/roadmap.md § Chantier 4).
 *
 * Invariants (§ 4.1) :
 *  - la caméra ne capte JAMAIS d'audio (piste vidéo seule) ; l'audio du clip vient
 *    exclusivement du mix rendu par MobileAudioProcessorService.mixAndExport ;
 *  - seuls des CHEMINS de fichiers traversent le pont Capacitor, jamais de vidéo
 *    en base64 (piège § 4.6.8) ;
 *  - les instants (`*HostSec`) sont exprimés sur l'horloge matérielle de la
 *    plateforme, la même que celle du moteur audio :
 *      iOS     : horloge hôte (mach_absolute_time) en secondes ;
 *      Android : CLOCK_MONOTONIC (System.nanoTime) en secondes.
 *  - compose() refuse un clip de plus de 45 s, même si le front est contourné.
 */

export type CameraFacing = 'front' | 'back';

export interface ClipPermissions {
  camera: 'granted' | 'denied' | 'prompt';
  /** Ajout à la photothèque / galerie (jamais de lecture). */
  photos: 'granted' | 'denied' | 'prompt';
}

export interface ClipRecordingResult {
  /** URI file:// de la vidéo brute (cache, sans audio). */
  videoPath:         string;
  /** Instant de capture de la 1re frame écrite (horloge matérielle, s). */
  firstFrameHostSec: number;
  /** Durée réelle d'après les PTS (dernière − première frame + 1 frame). */
  durationSec:       number;
  frameCount:        number;
  /** Android : origine des timestamps capteur. iOS : toujours 'host'. */
  timestampSource:   'host' | 'realtime' | 'unknown';
}

/** Ancre de lecture : position `filePosSec` du fichier rendue/présentée à `hostSec`. */
export interface ClipAudioAnchor {
  filePosSec: number;
  hostSec:    number;
}

export interface ClipComposeOptions {
  videoPath:         string;
  /** WAV du mix final (position 0 = début du segment), carte de fin incluse. */
  audioPath:         string;
  videoTrimStartSec: number;
  audioSkipSec:      number;
  /** Durée utile, hors carte de fin. ≤ 45 s. */
  durationSec:       number;
  /** PNG 1080×1920 transparent superposé à toute la vidéo. */
  overlayPath:       string;
  /** PNG 1080×1920 affiché pendant `endCardSec` après le segment. */
  endCardPath:       string;
  endCardSec:        number;
  /** Caméra frontale : l'aperçu est en miroir, l'export ne l'est jamais. */
  facing:            CameraFacing;
}

export interface ClipComposeResult {
  /** URI file:// du MP4 final (cache). */
  path:        string;
  durationSec: number;
}

export interface ClipShareResult {
  /** false si l'utilisateur a fermé la feuille sans partager. */
  completed: boolean;
  /** Identifiant de la cible quand le système le donne (ex. com.burbn.instagram…). */
  target?:   string;
}

export type ClipShortcut = 'instagram-story' | 'tiktok';

export interface ClipCameraPlugin {
  checkPermissions():   Promise<ClipPermissions>;
  requestPermissions(): Promise<ClipPermissions>;

  /** Aperçu plein écran SOUS la WebView (rendue transparente pendant le Mode Clip). */
  startPreview(opts: { facing: CameraFacing }): Promise<void>;
  stopPreview(): Promise<void>;
  flipCamera(opts: { facing: CameraFacing }): Promise<void>;

  /** Démarre l'écriture de la vidéo brute (vidéo seule). */
  startRecording(): Promise<void>;
  stopRecording(): Promise<ClipRecordingResult>;
  /** Abandon (interruption) : fichier supprimé, rien n'est renvoyé. */
  cancelRecording(): Promise<void>;

  /**
   * Android uniquement : joue un WAV (AudioTrack) en différé de `delayMs`.
   * iOS joue le son du tournage via PitchMonitor (beat natif), même horloge.
   */
  playAudio(opts: { path: string; delayMs: number }): Promise<void>;
  /**
   * Arrête la lecture et renvoie l'ancre mesurée (AudioTrack.getTimestamp, début
   * de lecture), la latence de sortie rapportée (ancre − appel à play(), ms) et la
   * dérive horloge audio / horloge système entre début et fin (ms).
   */
  stopAudio(): Promise<{ anchor: ClipAudioAnchor | null; reportedLatencyMs?: number; driftMs?: number }>;

  compose(opts: ClipComposeOptions): Promise<ClipComposeResult>;

  saveToGallery(opts: { path: string }): Promise<void>;
  share(opts: { path: string; text?: string }): Promise<ClipShareResult>;

  /** Raccourcis directs (Passe 3) — l'app cible doit être installée. */
  canShareTo(opts: { target: ClipShortcut }): Promise<{ available: boolean }>;
  shareTo(opts: { target: ClipShortcut; path: string; appId?: string }): Promise<void>;

  /** Ouvre les réglages de l'app (après un refus de permission). */
  openSettings(): Promise<void>;

  /** Supprime les fichiers du Mode Clip du cache (vidéos brutes, WAV, PNG, MP4). */
  clearCache(): Promise<void>;

  addListener(event: 'interrupted', handler: (data: { reason: string }) => void): Promise<{ remove: () => void }>;
  /** Android : caméra rouverte côté natif (retour d'arrière-plan). */
  addListener(event: 'previewReady', handler: () => void): Promise<{ remove: () => void }>;
  removeAllListeners(): Promise<void>;
}

export const ClipCamera = registerPlugin<ClipCameraPlugin>('ClipCamera');

/** Token DI permettant de remplacer ClipCamera dans les tests. */
export const CLIP_CAMERA = new InjectionToken<ClipCameraPlugin>('ClipCamera', {
  factory: () => ClipCamera,
});
