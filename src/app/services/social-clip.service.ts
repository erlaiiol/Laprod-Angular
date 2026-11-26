import { Injectable, InjectionToken, NgZone, computed, inject, signal } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';

import { CLIP_CAMERA, CameraFacing, ClipAudioAnchor, ClipRecordingResult } from './clip-camera-plugin';
import { PITCH_MONITOR, SessionResult, VoiceFx } from './pitch-monitor-plugin';
import { MobileMaquetteService } from './mobile-maquette.service';
import { DEFAULT_TRACK_SETTINGS, TrackSettings } from './mobile-audio-processor.service';
import {
  AudioAnchor, androidHeardMs, CLIP_DEFAULT_SECONDS, CLIP_END_CARD_SECONDS, ClipLatencies, ClipSegment,
  clampSegment, clipLatencies, computeAlignment, positionHeardAt, segmentLength,
  syncMirePositions, validateSegment,
} from '../utils/clip-sync';
import { OverlayText, renderEndCardPng, renderOverlayPng } from '../utils/clip-overlay';
import { blobToBase64 } from '../utils/blob.utils';
import { cropTake } from '../utils/take.utils';
import { computeWaveform } from '../utils/waveform.utils';

/**
 * Mode Clip du mobile studio — orchestration (docs/roadmap.md § Chantier 4).
 *
 *   framing → preparing → countdown → rolling → rendering → ready
 *
 * Le son du tournage est un WAV rendu par le pipeline d'export du studio
 * (mix complet en Playback, backline en Rec) et joué par un moteur natif qui
 * fournit une ancre d'horloge matérielle ; la caméra date ses frames sur la
 * même horloge. Toute la synchro passe par clip-sync.ts (aucune mesure de
 * temps côté WebView). Fourni au niveau du composant : un état par ouverture.
 */

export type ClipMode  = 'playback' | 'rec';
export type ClipStage = 'framing' | 'preparing' | 'countdown' | 'rolling' | 'rendering' | 'ready';
export type ClipPlatform = 'ios' | 'android' | 'web';
type Headphone = 'wired' | 'bluetooth' | 'bluetooth-a2dp' | 'none';

/** Plateforme d'exécution — remplaçable en test. */
export const CLIP_PLATFORM = new InjectionToken<ClipPlatform>('ClipPlatform', {
  factory: () => Capacitor.getPlatform() as ClipPlatform,
});

/** Écriture de fichiers dans le cache de l'app — remplaçable en test. */
export interface ClipFileStore {
  /** Écrit le blob dans le cache et renvoie son URI file://. */
  write(name: string, blob: Blob): Promise<string>;
  /** URL lisible par la WebView (<video src>). */
  webSrc(uri: string): string;
}

export const CLIP_FILES = new InjectionToken<ClipFileStore>('ClipFiles', {
  factory: () => ({
    async write(name: string, blob: Blob): Promise<string> {
      await Filesystem.writeFile({ path: name, data: await blobToBase64(blob), directory: Directory.Cache });
      return (await Filesystem.getUri({ path: name, directory: Directory.Cache })).uri;
    },
    webSrc: (uri: string) => Capacitor.convertFileSrc(uri),
  }),
});

/** Rendu des PNG du filigrane (canvas) — remplaçable en test (jsdom n'a pas de canvas). */
export const CLIP_OVERLAY_RENDERER = new InjectionToken<{
  overlay(t: OverlayText): Promise<Blob>;
  endCard(t: OverlayText): Promise<Blob>;
}>('ClipOverlayRenderer', {
  factory: () => ({ overlay: renderOverlayPng, endCard: renderEndCardPng }),
});

/** Contexte du studio, fourni par MobileStudioComponent à l'ouverture. */
export interface ClipStudioContext {
  trackId:        number;
  trackKey:       string;
  beatmaker:      string;
  username:       string;
  beatStreamUrl:  string;
  accessToken:    string;
  beatBlob:       Blob | null;
  /** Durée de la maquette (beat) en secondes. */
  maquetteSec:    number;
  headphone:      Headphone | null;
  /** Latence Bluetooth réglée au métronome (ms), null si jamais calibrée. */
  calibratedBtMs: number | null;
  /** Options de session micro du studio (monitoring, autotune, chaîne voix). */
  sessionOpts:    () => {
    useMonitor: boolean; voiceGain: number; fx: VoiceFx; reverbWet: number;
    trackKey: string; monitorAutotune: boolean; retuneSpeed: 'natural' | 'precise' | 'robot';
  };
}

/** Le son part pile à la fin du décompte (3 s), comme une prise du studio. */
export const CLIP_COUNTDOWN_MS = 3000;
/** Marge après la fin du segment avant l'arrêt automatique. */
const AUTO_STOP_MARGIN_MS = 300;
const WAVEFORM_POINTS = 120;
const MIX_BEAT_GAIN = 0.355;

/** Messages utilisateur — codes stables, textes humains (R14). */
export const CLIP_ERRORS: Record<string, string> = {
  CAMERA_DENIED:    'L\'accès à la caméra est refusé. Autorise-le dans les réglages du téléphone pour filmer un clip.',
  PHOTOS_DENIED:    'L\'accès à la galerie est refusé. Autorise l\'ajout de photos dans les réglages du téléphone.',
  MIC_DENIED:       'L\'accès au micro est refusé. Autorise-le dans les réglages du téléphone.',
  NEED_HEADPHONES:  'Branche un casque pour chanter pendant la vidéo : sans casque, la musique serait réenregistrée par le micro. Le mode Playback reste disponible.',
  NEED_TRACK:       'Enregistre au moins une voix avant de filmer un clip en Playback.',
  SEGMENT_TOO_LONG: 'Un clip dure 45 secondes au maximum.',
  SEGMENT_TOO_SHORT:'Choisis un passage d\'au moins 5 secondes.',
  SEGMENT_RANGE:    'Le passage choisi dépasse la fin de la maquette.',
  INTERRUPTED:      'Tournage interrompu. Ta maquette est intacte, tu peux recommencer.',
  SYNC:             'Le son et l\'image n\'ont pas pu être calés. Réessaie.',
  TOO_SHORT:        'Le clip est trop court : filme au moins 5 secondes.',
  FAILED:           'Le clip n\'a pas pu être créé. Réessaie.',
  SAVE_FAILED:      'Le clip n\'a pas pu être enregistré dans la galerie.',
  SHARE_FAILED:     'Le partage n\'a pas pu s\'ouvrir.',
};

function isBluetooth(h: Headphone | null): boolean {
  return h === 'bluetooth' || h === 'bluetooth-a2dp';
}

@Injectable()
export class SocialClipService {
  private readonly cam       = inject(CLIP_CAMERA);
  private readonly pm        = inject(PITCH_MONITOR);
  private readonly files     = inject(CLIP_FILES);
  private readonly platform  = inject(CLIP_PLATFORM);
  private readonly maquette  = inject(MobileMaquetteService);
  private readonly zone      = inject(NgZone);
  private readonly overlays  = inject(CLIP_OVERLAY_RENDERER);

  readonly stage      = signal<ClipStage>('framing');
  readonly mode       = signal<ClipMode>('playback');
  readonly facing     = signal<CameraFacing>('front');
  readonly segment    = signal<ClipSegment>({ startSec: 0, endSec: CLIP_DEFAULT_SECONDS });
  readonly countdown  = signal<number | null>(null);
  readonly elapsedSec = signal(0);
  readonly progress   = signal(0);
  readonly progressLabel = signal('');
  readonly errorCode  = signal<string | null>(null);
  readonly errorMsg   = computed(() => {
    const c = this.errorCode();
    return c ? (CLIP_ERRORS[c] ?? CLIP_ERRORS['FAILED']) : null;
  });
  readonly resultUri  = signal<string | null>(null);
  readonly resultSrc  = computed(() => {
    const u = this.resultUri();
    return u ? this.files.webSrc(u) : null;
  });
  /** Identifiant du clip monté — compte un clip une seule fois même s'il est enregistré PUIS partagé. */
  readonly clipUid    = signal<string | null>(null);
  /** Rec : la prise n'a pas trouvé de piste libre — utilisée pour le clip seulement. */
  readonly clipOnlyTake = signal(false);
  /** Mire de synchro (build debug) : clics dans le mix, cf. scripts/clip_sync_check.py. */
  readonly mire       = signal(false);
  readonly previewOn  = signal(false);

  readonly segmentSec = computed(() => segmentLength(this.segment()));
  /** Durée réelle du clip monté (hors carte de fin) — un arrêt anticipé la raccourcit. */
  readonly clipDurationSec = signal(0);

  private ctx: ClipStudioContext | null = null;
  private seq = 0;                       // invalide les étapes asynchrones d'un tournage abandonné
  private anchor: AudioAnchor | null = null;
  private lat: ClipLatencies = { takeCropMs: 0, heardMs: 0, recVideoMs: 0 };
  /** Ouverture en cours : incrémenté à chaque open()/close() pour ignorer une ouverture dépassée. */
  private openGen = 0;
  /** Piste ajoutée à la maquette par la dernière prise Rec (retirée si l'on recommence). */
  private addedTrackId: string | null = null;
  /** Dérive horloge audio / horloge système mesurée sur le dernier tournage (Android, ms). */
  readonly driftMs = signal<number | null>(null);
  private tourAudioUri: string | null = null;
  private overlayUri: string | null = null;
  private endCardUri: string | null = null;
  private pmOpen = false;
  private audioOpen = false;
  private camRecording = false;
  private timers: Array<ReturnType<typeof setTimeout>> = [];
  private ticker: ReturnType<typeof setInterval> | null = null;
  private handles: Array<{ remove: () => void }> = [];
  private interruptedPcm: SessionResult | null = null;

  // ── Ouverture / fermeture ──────────────────────────────────────────────────

  async open(ctx: ClipStudioContext): Promise<void> {
    const gen = ++this.openGen;
    this.ctx = ctx;
    this.addedTrackId = null;
    this.segment.set(clampSegment(0, CLIP_DEFAULT_SECONDS, ctx.maquetteSec));
    this.errorCode.set(null);
    await this.cam.clearCache().catch(() => {});

    const perms = await this.cam.checkPermissions().catch(() => null);
    if (gen !== this.openGen) return;              // fermé entre-temps : aucune demande
    let camera = perms?.camera ?? 'prompt';
    if (camera !== 'granted') camera = (await this.cam.requestPermissions().catch(() => null))?.camera ?? 'denied';
    if (gen !== this.openGen) return;              // fermé pendant la demande de permission
    if (camera !== 'granted') { this.errorCode.set('CAMERA_DENIED'); return; }

    const handle = await this.cam.addListener('interrupted', () =>
      this.zone.run(() => this.onCameraInterrupted()));
    if (gen !== this.openGen) { handle.remove(); return; }
    this.handles.push(handle);
    const ready = await this.cam.addListener('previewReady', () =>
      this.zone.run(() => { if (this.stage() === 'framing') this.previewOn.set(true); }));
    if (gen !== this.openGen) { ready.remove(); return; }
    this.handles.push(ready);
    // Retour d'arrière-plan : iOS reprend seul la capture ; Android rouvre la
    // caméra côté natif (surfaceCreated) — rien à relancer d'ici.
    try {
      await this.startPreview();
    } catch {
      if (gen === this.openGen) this.errorCode.set('FAILED');
    }
    // Fermé pendant l'ouverture de la caméra : on ne laisse pas l'aperçu allumé.
    if (gen !== this.openGen) await this.cam.stopPreview().catch(() => {});
  }

  async close(): Promise<void> {
    this.openGen++;
    await this.abort(null);
    this.handles.forEach(h => h.remove());
    this.handles = [];
    await this.cam.stopPreview().catch(() => {});
    this.previewOn.set(false);
    await this.cam.clearCache().catch(() => {});
    this.ctx = null;
  }

  private async startPreview(): Promise<void> {
    await this.cam.startPreview({ facing: this.facing() });
    this.previewOn.set(true);
  }

  async flip(): Promise<void> {
    if (this.stage() !== 'framing') return;
    const next: CameraFacing = this.facing() === 'front' ? 'back' : 'front';
    this.facing.set(next);
    await this.cam.flipCamera({ facing: next }).catch(() => {});
  }

  setMode(m: ClipMode): void {
    if (this.stage() !== 'framing') return;
    this.mode.set(m);
    this.errorCode.set(null);
  }

  /** Déplace/redimensionne le passage filmé (toujours ≤ 45 s, dans la maquette). */
  setSegment(startSec: number, lengthSec: number): void {
    if (this.stage() !== 'framing' || !this.ctx) return;
    this.segment.set(clampSegment(startSec, lengthSec, this.ctx.maquetteSec));
  }

  // ── Tournage ───────────────────────────────────────────────────────────────

  /** Erreur bloquante avant tournage, ou null. */
  preflight(): string | null {
    const ctx = this.ctx;
    if (!ctx) return 'FAILED';
    const segErr = validateSegment(this.segment(), ctx.maquetteSec);
    if (segErr === 'TOO_LONG') return 'SEGMENT_TOO_LONG';
    if (segErr === 'TOO_SHORT') return 'SEGMENT_TOO_SHORT';
    if (segErr === 'OUT_OF_RANGE') return 'SEGMENT_RANGE';
    if (this.mode() === 'playback' && !this.maquette.tracks().some(t => t.rawBlob)) return 'NEED_TRACK';
    // Même politique que le studio : sans casque, la backline serait réenregistrée.
    if (this.mode() === 'rec' && (!ctx.headphone || ctx.headphone === 'none')) return 'NEED_HEADPHONES';
    return null;
  }

  async record(): Promise<void> {
    if (this.stage() !== 'framing' || !this.ctx) return;
    const blocking = this.preflight();
    if (blocking) { this.errorCode.set(blocking); return; }

    const ctx = this.ctx;
    const seq = ++this.seq;
    const rec = this.mode() === 'rec';
    this.errorCode.set(null);
    this.clipOnlyTake.set(rec && !this.maquette.canAddTrack());
    this.interruptedPcm = null;
    this.stage.set('preparing');
    this.progressLabel.set(rec ? 'Préparation de la musique…' : 'Préparation de ta maquette…');
    this.progress.set(0);

    try {
      if (rec || this.platform === 'ios') {
        const perm = await this.pm.checkPermission().catch(() => null);
        if (perm?.microphone !== 'granted') {
          const req = await this.pm.requestPermission().catch(() => null);
          if (req?.microphone !== 'granted') throw new ClipError('MIC_DENIED');
        }
      }

      // Son du tournage : mix complet (Playback) ou backline sans la future prise (Rec).
      const text: OverlayText = { username: ctx.username, beatmaker: ctx.beatmaker };
      const [tourWav, overlay, endCard] = await Promise.all([
        this.renderMix(this.segment(), 0, [], true),
        this.overlays.overlay(text),
        this.overlays.endCard(text),
      ]);
      this.ensure(seq);
      const stamp = Date.now();
      [this.tourAudioUri, this.overlayUri, this.endCardUri] = await Promise.all([
        this.files.write(`clip-tour-${stamp}.wav`, tourWav),
        this.files.write(`clip-overlay-${stamp}.png`, overlay),
        this.files.write(`clip-endcard-${stamp}.png`, endCard),
      ]);
      this.ensure(seq);

      this.stage.set('countdown');
      // La caméra écrit dès le décompte (piège § 4.6.2) : l'allumage du capteur
      // ne retarde jamais le départ du son ; l'excédent est rogné au montage.
      this.camRecording = true;              // posé AVANT l'await : un abandon concurrent l'annulera
      await this.cam.startRecording();
      this.ensure(seq);

      const startInMs = await this.startTourAudio(ctx, rec);
      this.ensure(seq);

      await this.runCountdown(startInMs, seq);
      this.ensure(seq);

      this.stage.set('rolling');
      this.elapsedSec.set(0);
      const t0 = performance.now();          // affichage du chrono uniquement
      this.ticker = setInterval(() => this.zone.run(() =>
        this.elapsedSec.set(Math.min(this.segmentSec(), (performance.now() - t0) / 1000))), 250);
      this.timers.push(setTimeout(() => this.zone.run(() => void this.stop()),
        this.segmentSec() * 1000 + AUTO_STOP_MARGIN_MS));
    } catch (e) {
      // Abandonné entre-temps : abort() a pu passer AVANT qu'une ressource native
      // ne soit ouverte (await en cours) — on libère ce que ce tournage a démarré.
      if (seq !== this.seq) { await this.releaseNative(); return; }
      await this.abort(e instanceof ClipError ? e.code : 'FAILED');
    }
  }

  /** Démarre le son du tournage ; renvoie le délai (ms) avant son départ effectif. */
  private async startTourAudio(ctx: ClipStudioContext, rec: boolean): Promise<number> {
    const opts = ctx.sessionOpts();
    const bt = isBluetooth(ctx.headphone);

    if (this.platform === 'ios') {
      // iOS : le son est joué par le moteur natif de PitchMonitor (même horloge
      // que le tap micro et que la caméra) — exactement comme une prise du studio.
      this.handles.push(await this.pm.addListener('sessionInterrupted', data =>
        this.zone.run(() => this.onPmInterrupted(data))));
      this.pmOpen = true;                    // avant l'await (cf. releaseNative)
      const info = await this.pm.startSession({
        ...opts,
        useMonitor:      rec && opts.useMonitor,
        monitorAutotune: rec && opts.monitorAutotune,
        record:          rec,
        beatPath:        this.tourAudioUri!,
        beatStartSec:    0,
        beatVolume:      1,
        startDelayMs:    CLIP_COUNTDOWN_MS,
      });
      if (!info?.nativeBeat || info.beatStartHostSec == null) throw new ClipError('SYNC');
      this.anchor = { filePosSec: 0, hostSec: info.beatStartHostSec };
      this.lat = clipLatencies({
        bluetooth:    bt,
        calibratedMs: bt ? ctx.calibratedBtMs : null,
        outputMs:     info.outputLatencyMs ?? 0,
        inputMs:      info.inputLatencyMs ?? 0,
      });
      return info.startInMs ?? CLIP_COUNTDOWN_MS;
    }

    // Android : AudioTrack dans ClipCamera ; l'ancre vient de getTimestamp()
    // (instant de PRÉSENTATION, latence de sortie déjà incluse) → rien à ajouter.
    if (rec) {
      this.handles.push(await this.pm.addListener('sessionInterrupted', data =>
        this.zone.run(() => this.onPmInterrupted(data))));
      this.pmOpen = true;
      await this.pm.startSession({ ...opts, record: true });
    }
    this.audioOpen = true;
    await this.cam.playAudio({ path: this.tourAudioUri!, delayMs: CLIP_COUNTDOWN_MS });
    // Latence entendue connue à l'arrêt seulement (cf. stop() → androidHeardMs).
    this.lat = { takeCropMs: 0, heardMs: 0, recVideoMs: 0 };
    return CLIP_COUNTDOWN_MS;
  }

  private runCountdown(ms: number, seq: number): Promise<void> {
    return new Promise(resolve => {
      const deadline = performance.now() + ms;   // affichage seulement, jamais la synchro
      const tick = () => {
        if (seq !== this.seq) { this.countdown.set(null); resolve(); return; }
        const remaining = deadline - performance.now();
        if (remaining <= 0) { this.countdown.set(null); resolve(); return; }
        this.countdown.set(Math.ceil(remaining / 1000));
        this.timers.push(setTimeout(() => this.zone.run(tick), 50));
      };
      tick();
    });
  }

  /** Caméra coupée (appel, arrière-plan, erreur) : seul un tournage en cours est perdu. */
  private onCameraInterrupted(): void {
    const s = this.stage();
    if (s === 'preparing' || s === 'countdown' || s === 'rolling') void this.abort('INTERRUPTED');
    else if (s === 'framing') this.previewOn.set(false);
  }

  private onPmInterrupted(data: SessionResult): void {
    this.pmOpen = false;
    if (this.stage() !== 'rolling') { void this.abort('INTERRUPTED'); return; }
    // Prise partielle conservée (comportement du studio) : le clip est monté
    // sur ce qui a été filmé jusque-là, s'il est assez long.
    this.interruptedPcm = data;
    void this.stop();
  }

  /** Fin du tournage (bouton, fin du segment, interruption micro) → montage. */
  async stop(): Promise<void> {
    if (this.stage() !== 'rolling' || !this.ctx) return;
    const ctx = this.ctx;
    const seq = this.seq;
    const rec = this.mode() === 'rec';
    this.clearTimers();
    this.stage.set('rendering');
    this.progressLabel.set('Montage du clip…');
    this.progress.set(5);

    try {
      const video: ClipRecordingResult = await this.cam.stopRecording();
      this.camRecording = false;

      let pcm: SessionResult | null = this.interruptedPcm;
      if (this.platform === 'ios') {
        if (this.pmOpen) { pcm = await this.pm.stopSession(); this.pmOpen = false; }
      } else {
        const r = await this.cam.stopAudio();
        this.audioOpen = false;
        this.anchor = r.anchor ? toAnchor(r.anchor) : null;
        this.driftMs.set(r.driftMs ?? null);
        // L'ancre AudioTrack inclut la latence de sortie rapportée par l'appareil ;
        // un casque Bluetooth qui ne la rapporte pas est rattrapé par son réglage.
        const heard = androidHeardMs(isBluetooth(ctx.headphone), ctx.calibratedBtMs, r.reportedLatencyMs ?? 0);
        this.lat = { takeCropMs: 0, heardMs: heard, recVideoMs: heard };
        if (rec && this.pmOpen) { pcm = await this.pm.stopSession(); this.pmOpen = false; }
      }
      await this.pm.removeAllListeners().catch(() => {});
      const anchor = this.anchor;
      if (!anchor) throw new ClipError('SYNC');

      const align = computeAlignment({
        firstFrameHostSec: video.firstFrameHostSec,
        videoDurationSec:  video.durationSec,
        anchor,
        // Playback : les lèvres suivent ce qui est entendu. Rec : elles suivent la
        // voix, recalée comme une prise du studio (même décalage, cf. clipLatencies).
        heardMs:           rec ? this.lat.recVideoMs : this.lat.heardMs,
        segmentSec:        this.segmentSec(),
      });
      if (align === 'NO_OVERLAP') throw new ClipError('TOO_SHORT');

      // Rec : la prise rejoint la maquette (ou reste « clip seulement »).
      let extraTakes: Array<{ rawBlob: Blob; settings: TrackSettings; beatStartSec: number }> = [];
      if (rec) {
        if (!pcm) throw new ClipError('FAILED');
        extraTakes = this.placeTake(pcm, anchor, ctx);
      }
      this.ensure(seq);

      // Audio final : le passage réellement filmé + la carte de fin en fondu.
      // Re-rendu dans tous les cas : l'arrêt anticipé garde ainsi un fondu propre.
      this.progressLabel.set('Mixage du son…');
      this.progress.set(30);
      const seg = this.segment();
      const finalSeg = { startSec: seg.startSec, endSec: seg.startSec + align.audioSkipSec + align.durationSec };
      const finalWav = await this.renderMix(finalSeg, CLIP_END_CARD_SECONDS, extraTakes);
      this.ensure(seq);
      const audioUri = await this.files.write(`clip-final-${Date.now()}.wav`, finalWav);
      this.ensure(seq);

      this.progressLabel.set('Assemblage de la vidéo…');
      this.progress.set(60);
      const out = await this.cam.compose({
        videoPath:         video.videoPath,
        audioPath:         audioUri,
        videoTrimStartSec: align.videoTrimStartSec,
        audioSkipSec:      align.audioSkipSec,
        durationSec:       align.durationSec,
        overlayPath:       this.overlayUri!,
        endCardPath:       this.endCardUri!,
        endCardSec:        CLIP_END_CARD_SECONDS,
        facing:            this.facing(),
      });
      this.ensure(seq);
      this.progress.set(100);
      this.resultUri.set(out.path);
      this.clipDurationSec.set(align.durationSec);
      this.clipUid.set(newClipUid());
      this.stage.set('ready');
      await this.cam.stopPreview().catch(() => {});
      this.previewOn.set(false);
    } catch (e) {
      // Montage raté : la « Prise clip » déjà posée ne doit pas rester dans la maquette
      // (elle entrerait dans la backline de l'essai suivant).
      if (this.addedTrackId) { this.maquette.removeTrack(this.addedTrackId); this.addedTrackId = null; }
      if (seq !== this.seq) return;
      await this.abort(e instanceof ClipError ? e.code : 'FAILED');
    }
  }

  /**
   * Pose la prise faite pendant la vidéo dans la maquette. Mêmes règles que
   * _finalizeRecording (cropTake) et même horloge que la vidéo :
   *  - iOS : position sous le 1er échantillon gardé, mesurée par le moteur
   *    natif, puis latences casque retirées (takeCropMs) ;
   *  - Android : instant de capture du 1er échantillon → positionHeardAt, la
   *    fonction qui place aussi la vidéo (latence déjà dans les timestamps).
   */
  private placeTake(pcm: SessionResult, anchor: AudioAnchor, ctx: ClipStudioContext)
      : Array<{ rawBlob: Blob; settings: TrackSettings; beatStartSec: number }> {
    let fileStart: number;
    let cropSec: number;
    if (this.platform === 'ios') {
      if (pcm.firstSampleBeatSec == null) throw new ClipError('SYNC');
      fileStart = pcm.firstSampleBeatSec;      // beatStartSec = 0 : domaine fichier
      cropSec   = this.lat.takeCropMs / 1000;
    } else {
      if (pcm.firstSampleHostSec == null) throw new ClipError('SYNC');
      fileStart = positionHeardAt(pcm.firstSampleHostSec, anchor, this.lat.recVideoMs);
      cropSec   = 0;
    }
    // Voix captée avant le départ du son (décompte) : retirée, la piste démarre au segment.
    if (fileStart < 0) { cropSec += -fileStart; fileStart = 0; }
    const take = cropTake(pcm, cropSec);
    if (take.voiceSec < 0.2) throw new ClipError('TOO_SHORT');
    const beatStartSec = this.segment().startSec + fileStart;
    const waveform = computeWaveform(take.rms, WAVEFORM_POINTS);

    if (!this.clipOnlyTake() && this.maquette.canAddTrack()) {
      // Chemin normal du studio : une vraie piste, réglable et supprimable ensuite.
      if (this.addedTrackId) this.maquette.removeTrack(this.addedTrackId);
      const id = this.maquette.addTrack();
      this.addedTrackId = id;
      this.maquette.renameTrack(id, 'Prise clip');
      this.maquette.setRecording(id);
      this.maquette.setRecorded(id, take.rawBlob, waveform, take.voiceSec, beatStartSec);
      return [];
    }
    this.clipOnlyTake.set(true);
    return [{ rawBlob: take.rawBlob, settings: { ...DEFAULT_TRACK_SETTINGS }, beatStartSec }];
  }

  /**
   * `tour` : son joué PENDANT le tournage (Playback ou backline) — toujours sans
   * réverb, comme le retour casque. Le rendu final du clip, lui, la garde.
   */
  private renderMix(seg: ClipSegment, tailSec: number,
                    extraTakes: Array<{ rawBlob: Blob; settings: TrackSettings; beatStartSec: number }> = [],
                    tour = false): Promise<Blob> {
    const ctx = this.ctx!;
    return this.maquette.exportMaquette({
      beatStreamUrl: ctx.beatStreamUrl,
      beatGain:      MIX_BEAT_GAIN,
      accessToken:   ctx.accessToken,
      trackKey:      ctx.trackKey,
      latencyHintMs: 0,                    // latence déjà retirée de chaque prise
      beatBlob:      ctx.beatBlob ?? undefined,
      segment:       seg,
      format:        'wav',
      tailSec,
      allowEmpty:    true,
      extraTakes,
      noReverb:      tour,
      clickMarksSec: this.mire() ? syncMirePositions(segmentLength(seg)) : undefined,
    });
  }

  /** Réglages de l'app (permission refusée) — le studio reste utilisable. */
  openSettings(): void {
    void this.cam.openSettings().catch(() => {});
  }

  // ── Résultat ───────────────────────────────────────────────────────────────

  async saveToGallery(): Promise<boolean> {
    const path = this.resultUri();
    if (!path) return false;
    try {
      await this.cam.saveToGallery({ path });
      return true;
    } catch (e) {
      this.errorCode.set(isDenied(e) ? 'PHOTOS_DENIED' : 'SAVE_FAILED');
      return false;
    }
  }

  /**
   * Recommencer : retour au cadrage. La « Prise clip » ajoutée par le tournage
   * précédent est retirée — sinon elle serait dans la backline du suivant et
   * chaque essai consommerait une piste. Celle du clip GARDÉ (fermeture) reste.
   */
  async retake(): Promise<void> {
    await this.abort(null);
    if (this.addedTrackId) {
      this.maquette.removeTrack(this.addedTrackId);
      this.addedTrackId = null;
    }
    this.resultUri.set(null);
    await this.startPreview().catch(() => this.errorCode.set('FAILED'));
  }

  // ── Abandon ────────────────────────────────────────────────────────────────

  /** Coupe tout ce qui tourne et revient au cadrage (code = message à afficher). */
  async abort(code: string | null): Promise<void> {
    this.seq++;
    this.clearTimers();
    this.countdown.set(null);
    await this.releaseNative();
    this.anchor = null;
    this.stage.set('framing');
    this.errorCode.set(code);
  }

  /** Libère caméra, son et micro ouverts par un tournage (appels idempotents). */
  private async releaseNative(): Promise<void> {
    if (this.camRecording) { this.camRecording = false; await this.cam.cancelRecording().catch(() => {}); }
    if (this.audioOpen)    { this.audioOpen = false;    await this.cam.stopAudio().catch(() => {}); }
    if (this.pmOpen)       { this.pmOpen = false;       await this.pm.stopSession().catch(() => {}); }
    await this.pm.removeAllListeners().catch(() => {});
  }

  private clearTimers(): void {
    this.timers.forEach(t => clearTimeout(t));
    this.timers = [];
    if (this.ticker) { clearInterval(this.ticker); this.ticker = null; }
  }

  private ensure(seq: number): void {
    if (seq !== this.seq) throw new ClipError('ABORTED');
  }
}

class ClipError extends Error {
  constructor(readonly code: string) { super(code); }
}

function newClipUid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r % 4) + 8).toString(16);
  });
}

function toAnchor(a: ClipAudioAnchor): AudioAnchor {
  return { filePosSec: a.filePosSec, hostSec: a.hostSec };
}

function isDenied(e: unknown): boolean {
  const msg = (e as { message?: string; code?: string })?.message ?? '';
  return /denied|refus|permission/i.test(msg) || (e as { code?: string })?.code === 'DENIED';
}
