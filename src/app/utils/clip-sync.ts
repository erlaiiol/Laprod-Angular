/**
 * Mode Clip — calculs purs de segment et de synchronisation audio/vidéo.
 *
 * Spécification : docs/roadmap.md § Chantier 4 (§ 4.1.3, § 4.1.5, § 4.3).
 *
 * Toute la synchro du clip passe par ce module — et uniquement par lui — pour
 * qu'il n'existe qu'UNE implémentation de « quelle position de la maquette
 * correspond à cet instant ». Aucun appel à Date.now()/performance.now() ici :
 * les instants viennent exclusivement des horloges matérielles natives (PTS
 * caméra, horloge du moteur audio), exprimés en secondes sur la même base de
 * temps par plateforme. Le pont Capacitor ajoute plusieurs dizaines de ms de
 * gigue : une mesure prise côté WebView ruinerait la synchro.
 *
 * Domaine de temps « fichier » : le WAV joué pendant le tournage (mix complet en
 * mode Playback, backline en mode Rec) commence au début du segment choisi.
 * Position fichier 0 = segment.startSec dans la maquette.
 */

/** Durée maximale d'un clip (décision produit 17/11/2026). Reprise côté natif. */
export const CLIP_MAX_SECONDS = 45;
export const CLIP_DEFAULT_SECONDS = 30;
/** En dessous, un clip n'a plus de sens (et le décompte en mange une partie). */
export const CLIP_MIN_SECONDS = 5;
/** Carte de fin LaProd ajoutée après le segment. */
export const CLIP_END_CARD_SECONDS = 1.5;

export interface ClipSegment {
  startSec: number;
  endSec:   number;
}

export type SegmentError = 'TOO_LONG' | 'TOO_SHORT' | 'OUT_OF_RANGE';

/** Durée d'un segment (s). */
export function segmentLength(seg: ClipSegment): number {
  return seg.endSec - seg.startSec;
}

/**
 * Segment valide à partir d'un départ et d'une longueur souhaités : longueur
 * bornée à [MIN, MAX], segment ramené dans la maquette.
 */
export function clampSegment(startSec: number, lengthSec: number, maquetteSec: number): ClipSegment {
  const total  = Math.max(0, maquetteSec);
  const length = Math.min(Math.max(lengthSec, CLIP_MIN_SECONDS), CLIP_MAX_SECONDS, total);
  const start  = Math.min(Math.max(0, startSec), Math.max(0, total - length));
  return { startSec: start, endSec: start + length };
}

/** null si le segment est utilisable, sinon le code de refus. */
export function validateSegment(seg: ClipSegment, maquetteSec: number): SegmentError | null {
  const len = segmentLength(seg);
  // Tolérance d'1 ms : les bornes viennent de sliders en flottants.
  if (len > CLIP_MAX_SECONDS + 1e-3) return 'TOO_LONG';
  if (len < CLIP_MIN_SECONDS - 1e-3) return 'TOO_SHORT';
  if (seg.startSec < 0 || seg.endSec > maquetteSec + 1e-3) return 'OUT_OF_RANGE';
  return null;
}

// ── Latences casque ───────────────────────────────────────────────────────────

export interface HeadphoneLatencyInput {
  bluetooth:    boolean;
  /** Latence Bluetooth réglée au métronome (ms), null si jamais calibrée. */
  calibratedMs: number | null;
  /** Latence de sortie rapportée par le système (ms). */
  outputMs:     number;
  /** Latence d'entrée rapportée par le système (ms). */
  inputMs:      number;
}

export interface ClipLatencies {
  /**
   * À retirer du début d'une prise voix (cf. _finalizeRecording du studio) :
   * le chanteur entend le beat en retard (sortie) et sa voix arrive en retard
   * dans le tap (entrée).
   */
  takeCropMs: number;
  /**
   * Playback : retard entre le rendu d'un échantillon par le moteur et le
   * moment où l'utilisateur l'entend (sortie seule). C'est ce que suivent les lèvres.
   */
  heardMs:    number;
  /**
   * Rec : décalage de la vidéo, déduit du recadrage de la prise pour que la
   * voix et les lèvres tombent au même endroit (= takeCropMs − entrée).
   */
  recVideoMs: number;
}

/**
 * Source unique des latences du studio et du clip.
 *
 * - takeCropMs : inchangé par rapport au studio (cf. _takeLatencyMs).
 * - recVideoMs : takeCropMs − entrée. Par construction, la prise et la vidéo
 *   reçoivent le même décalage pour un même instant physique (positionHeardAt +
 *   voiceTapToPosition) — c'est ce qui compte en Rec : lèvres = voix.
 * - heardMs : ce que l'oreille entend réellement. Le réglage Bluetooth au
 *   métronome mesure des tapes sur un clic ENTENDU (sortie + réaction, sans
 *   micro dans la boucle) : c'est directement la latence entendue.
 * Hors Bluetooth calibré, heardMs = recVideoMs = sortie.
 */
export function clipLatencies(i: HeadphoneLatencyInput): ClipLatencies {
  const input = Math.max(0, i.inputMs || 0);
  const calibrated = i.bluetooth && i.calibratedMs !== null ? Math.max(0, i.calibratedMs) : null;
  const takeCropMs = calibrated ?? Math.max(0, (i.outputMs || 0) + input);
  return {
    takeCropMs,
    recVideoMs: Math.max(0, takeCropMs - input),
    heardMs:    calibrated ?? Math.max(0, i.outputMs || 0),
  };
}

/**
 * Android : AudioTrack.getTimestamp() donne l'instant de présentation, latence
 * de sortie RAPPORTÉE par l'appareil incluse (`reportedMs` = ancre − appel à
 * play()). Un casque Bluetooth dont le délai n'est pas rapporté se rattrape avec
 * le réglage au métronome : on n'ajoute que ce qui manque.
 */
export function androidHeardMs(bluetooth: boolean, calibratedMs: number | null, reportedMs: number): number {
  if (!bluetooth || calibratedMs === null) return 0;
  return Math.max(0, calibratedMs - Math.max(0, reportedMs));
}

// ── Ancrage horloge ───────────────────────────────────────────────────────────

/**
 * Position `filePosSec` du fichier audio joué, rendue par le moteur audio à
 * l'instant `hostSec` (horloge matérielle de la plateforme, en secondes).
 * iOS : heure machine du départ programmé du beat natif (AVAudioEngine).
 * Android : instant de présentation donné par AudioTrack.getTimestamp().
 */
export interface AudioAnchor {
  filePosSec: number;
  hostSec:    number;
}

/**
 * Position du fichier que l'utilisateur ENTEND à l'instant physique `hostSec`.
 * Les lèvres suivent ce qui est entendu (Playback), et la voix chantée à cet
 * instant est posée à cette même position (Rec) — cf. docs § 4.3.
 */
export function positionHeardAt(hostSec: number, anchor: AudioAnchor, heardMs: number): number {
  return anchor.filePosSec + (hostSec - anchor.hostSec) - heardMs / 1000;
}

/**
 * Position où le studio pose l'échantillon voix capté (tap natif) à
 * `tapHostSec`, après le recadrage de la prise (takeCropMs) — miroir exact de
 * l'algorithme de _finalizeRecording : startSec = position sous le 1er
 * échantillon gardé, puis takeCropMs retirés du début de la voix.
 */
export function voiceTapToPosition(tapHostSec: number, anchor: AudioAnchor, takeCropMs: number): number {
  return anchor.filePosSec + (tapHostSec - anchor.hostSec) - takeCropMs / 1000;
}

// ── Alignement final du clip ─────────────────────────────────────────────────

export interface AlignmentInput {
  /** Instant (horloge matérielle, s) de capture de la 1re frame de la vidéo brute. */
  firstFrameHostSec: number;
  /** Durée de la vidéo brute (s), mesurée sur ses PTS réels. */
  videoDurationSec:  number;
  anchor:            AudioAnchor;
  heardMs:           number;
  /** Durée du segment (s) — l'audio final commence à la position fichier 0. */
  segmentSec:        number;
}

export interface ClipAlignment {
  /** Secondes de vidéo brute à couper au début (caméra partie avant le son). */
  videoTrimStartSec: number;
  /** Secondes d'audio à sauter au début (caméra partie après le son). */
  audioSkipSec:      number;
  /** Durée utile du clip, hors carte de fin. */
  durationSec:       number;
}

export type AlignmentError = 'NO_OVERLAP';

/**
 * Découpe vidéo/audio pour que chaque frame tombe sur ce qui était entendu
 * au moment où elle a été filmée. La caméra démarre pendant le décompte
 * (piège § 4.6.2) : le cas nominal est videoTrimStartSec > 0, audioSkipSec = 0.
 */
export function computeAlignment(i: AlignmentInput): ClipAlignment | AlignmentError {
  const p0 = positionHeardAt(i.firstFrameHostSec, i.anchor, i.heardMs);
  const videoTrimStartSec = p0 < 0 ? -p0 : 0;
  const audioSkipSec      = p0 > 0 ? p0 : 0;
  const durationSec = Math.min(i.segmentSec - audioSkipSec, i.videoDurationSec - videoTrimStartSec);
  if (!(durationSec >= CLIP_MIN_SECONDS - 1e-3)) return 'NO_OVERLAP';
  return { videoTrimStartSec, audioSkipSec, durationSec: Math.min(durationSec, CLIP_MAX_SECONDS) };
}

// ── Contrôle de dérive (mire de synchro, build debug) ───────────────────────

/** Seuils de la mire de synchro — docs § 4.3, identiques pour les deux modes. */
export const SYNC_THRESHOLDS = {
  meanAbsMs:      40,
  audioLeadMs:    30,
  driftMs:        10,
  repeatSpreadMs: 15,
} as const;

/** Positions (s, domaine fichier) des clics de la mire : toutes les 2 s. */
export const SYNC_MIRE_INTERVAL_SEC = 2;
export function syncMirePositions(segmentSec: number): number[] {
  const out: number[] = [];
  for (let t = SYNC_MIRE_INTERVAL_SEC; t < segmentSec; t += SYNC_MIRE_INTERVAL_SEC) out.push(t);
  return out;
}
