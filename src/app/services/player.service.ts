import { Injectable, inject, signal, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Track } from './track.service';
import { environment } from '../../environments/environment';

/** Contexte d'une commande de mixage en cours de lecture dans le player. */
export interface MixOrderContext {
  orderId:    number;
  orderTitle: string;
  status:     string;
  personName: string | null; // engineer (côté artiste) ou artiste (côté engineer)
}

@Injectable({ providedIn: 'root' })
export class PlayerService {

  // ── State signals ─────────────────────────────────────────────────────────
  currentTrack  = signal<Track | null>(null);
  isPlaying     = signal(false);
  currentTime   = signal(0);
  duration      = signal(0);
  volume        = signal(0.8);

  // ── Context signals ───────────────────────────────────────────────────────
  /** Track dont la page détail est ouverte — active les boutons Download/REC. */
  viewingTrack    = signal<Track | null>(null);
  /** Commande de mixage dont l'audio est lu — affiche le statut dans le player. */
  viewingMixOrder = signal<MixOrderContext | null>(null);
  /** Increments each time the player asks the detail page to open the recorder. */
  recRequested  = signal(0);

  // ── Audio element shared with WaveSurfer via `media:` option ─────────────
  // WaveSurfer owns loading (wavesurfer.load(url)) — this service only controls
  // play/pause/seek/volume after the track is loaded.
  readonly audioEl = new Audio();

  // Flag consumed by PlayerComponent: play after WaveSurfer 'ready' fires
  playOnReady = false;

  private http = inject(HttpClient);
  private tracksApiUrl  = `${environment.apiUrl}/api/tracks`;
  private favoritesUrl  = `${environment.apiUrl}/api/favorites`;

  constructor() {
    this.audioEl.volume = this.volume();

    this.audioEl.ontimeupdate = () => {
      this.currentTime.set(this.audioEl.currentTime);
    };

    this.audioEl.ondurationchange = () => {
      this.duration.set(this.audioEl.duration || 0);
    };

    this.audioEl.onended = () => {
      this.isPlaying.set(false);
      // Ne pas auto-avancer sur un audio mix order : l'utilisateur décide lui-même
      if (!this.viewingMixOrder()) {
        this.playNext();
      }
    };

    this.audioEl.onpause = () => this.isPlaying.set(false);
    this.audioEl.onplay  = () => this.isPlaying.set(true);

    // Sync volume signal → audio element
    effect(() => {
      this.audioEl.volume = this.volume();
    });
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Request playback of a track.
   * Sets the currentTrack signal — PlayerComponent's effect() watches this
   * and calls wavesurfer.load(url), then plays on 'ready'.
   * Do NOT set audioEl.src here (race condition with WaveSurfer.load()).
   */
  play(track: Track): void {
    this.playOnReady = true;

    // Do NOT call audioEl.play() here with no src set — it corrupts the
    // HTMLMediaElement state (MEDIA_ERR_SRC_NOT_SUPPORTED) and prevents
    // WaveSurfer from loading audio on the same element.
    // Document is already user-activated by the click event; the async
    // play() in WaveSurfer's 'ready' callback will be allowed by the browser.

    this.currentTrack.set(track);
    // Jouer un beat normal efface le contexte mix order (et inversement)
    this.viewingMixOrder.set(null);
    // Record listening history — uniquement si connecté (évite un 401 → refresh → logout)
    if (track.id > 0 && localStorage.getItem('access_token')) {
      this.http.post(`${this.favoritesUrl}/listening/${track.id}`, {})
        .subscribe({ error: () => {} });
    }
  }

  pause(): void {
    this.audioEl.pause();
  }

  resume(): void {
    this.audioEl.play().catch(err => console.warn('PlayerService: resume() failed', err));
  }

  togglePlay(): void {
    if (this.isPlaying()) {
      this.pause();
    } else {
      this.resume();
    }
  }

  seek(time: number): void {
    this.audioEl.currentTime = time;
  }

  setVolume(value: number): void {
    this.volume.set(Math.max(0, Math.min(1, value)));
  }

  /**
   * Joue un audio de commande de mixage (Blob URL JWT) et affiche le statut dans le player.
   * blobUrl doit être un `URL.createObjectURL(blob)` créé par le composant appelant.
   */
  playMixAudio(blobUrl: string, ctx: MixOrderContext): void {
    const track: Track = {
      id:              0,
      title:           `Référence de : ${ctx.orderTitle}`,
      stream_url:      blobUrl,
      full_stream_url: null,
      image_file:      '',
      composer_user:   { username: ctx.personName ?? '' },
      bpm:             0,
      key:             '',
      style:           '',
      price_mp3:       0,
      tags:            [],
      is_approved:     true,
    };
    this.playOnReady = true;
    this.currentTrack.set(track);
    this.viewingTrack.set(null);
    this.viewingMixOrder.set(ctx);
  }

  close(): void {
    this.audioEl.pause();
    this.audioEl.src = '';
    this.currentTrack.set(null);
    this.viewingMixOrder.set(null);
    this.isPlaying.set(false);
    this.currentTime.set(0);
    this.duration.set(0);
    this.playOnReady = false;
  }

  playNext(): void {
    const current = this.currentTrack();
    const excludeId = current?.id;
    const params = excludeId ? `?exclude_id=${excludeId}` : '';

    this.http.get<{ success: boolean; data: { track: Track } }>(
      `${this.tracksApiUrl}/random${params}`
    ).subscribe({
      next: (res) => {
        if (res.success && res.data?.track) {
          this.play(res.data.track);
        }
      },
      error: (err) => console.warn('PlayerService: playNext() failed', err)
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  buildAudioUrl(track: Track): string {
    const url = track.full_stream_url ?? track.stream_url;
    if (!url) return '';
    // Blob URLs (createObjectURL) et URLs absolues passent tels quels
    if (url.startsWith('blob:') || url.startsWith('http')) {
      return url;
    }
    return `${environment.apiUrl}${url}`;
  }

}
