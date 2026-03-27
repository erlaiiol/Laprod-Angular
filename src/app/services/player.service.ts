import { Injectable, inject, signal, effect } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Track } from './track.service';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class PlayerService {

  // ── State signals ─────────────────────────────────────────────────────────
  currentTrack  = signal<Track | null>(null);
  isPlaying     = signal(false);
  currentTime   = signal(0);
  duration      = signal(0);
  volume        = signal(0.8);

  // ── Context signals (set by TrackDetailComponent) ─────────────────────────
  /** Track whose detail page is currently open — drives player contextual buttons. */
  viewingTrack  = signal<Track | null>(null);
  /** Increments each time the player asks the detail page to open the recorder. */
  recRequested  = signal(0);

  // ── Audio element shared with WaveSurfer via `media:` option ─────────────
  // WaveSurfer owns loading (wavesurfer.load(url)) — this service only controls
  // play/pause/seek/volume after the track is loaded.
  readonly audioEl = new Audio();

  // Flag consumed by PlayerComponent: play after WaveSurfer 'ready' fires
  playOnReady = false;

  private http = inject(HttpClient);
  private tracksApiUrl = `${environment.apiUrl}/tracks`;

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
      this.playNext();
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
    this.currentTrack.set(track);
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

  close(): void {
    this.audioEl.pause();
    this.audioEl.src = '';
    this.currentTrack.set(null);
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
    if (!track.audio_file) return '';
    if (track.audio_file.startsWith('http')) return track.audio_file;
    return `${environment.apiUrl}/static/${track.audio_file}`;
  }

}
