import {
  Component,
  OnDestroy,
  AfterViewInit,
  ViewChild,
  ElementRef,
  HostListener,
  inject,
  effect,
  signal,
  computed,
  ChangeDetectionStrategy
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import WaveSurfer from 'wavesurfer.js';
import { PlayerService } from '../../services/player.service';
import { TrackService } from '../../services/track.service';
import { MixOrderContext } from '../../services/player.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-player',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './player.component.html',
  styleUrls: ['./player.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class PlayerComponent implements AfterViewInit, OnDestroy {

  @ViewChild('waveformContainer') waveformContainer!: ElementRef<HTMLDivElement>;

  player   = inject(PlayerService);
  trackSvc = inject(TrackService);

  /** Whether the player is in track_detail context (viewingTrack is set). */
  isDetailContext    = computed(() => this.player.viewingTrack() !== null);
  /** Whether the player is showing a mix order reference/preview. */
  isMixOrderContext  = computed(() => this.player.viewingMixOrder() !== null);

  /** True when the currently playing track IS the viewing track → actions work directly. */
  isViewingTrackLoaded = computed(() => {
    const v = this.player.viewingTrack();
    const c = this.player.currentTrack();
    return !!v && !!c && v.id === c.id;
  });

  showConfirmModal = signal(false);
  private pendingAction: 'download' | 'rec' | null = null;

  private wavesurfer: WaveSurfer | null = null;

  constructor() {
    effect(() => {
      const track = this.player.currentTrack();
      if (!track || !this.wavesurfer) return;
      const url = this.player.buildAudioUrl(track);
      if (url) this.wavesurfer.load(url);
    });
  }

  ngAfterViewInit(): void {
    this.wavesurfer = WaveSurfer.create({
      container:     this.waveformContainer.nativeElement,
      waveColor:     '#4a5568',
      progressColor: '#ffffff',
      cursorColor:   '#ffffff',
      height:        48,
      barWidth:      2,
      barGap:        1,
      barRadius:     2,
      media: this.player.audioEl,
    });

    this.wavesurfer.on('ready', () => {
      if (this.player.playOnReady) {
        this.player.playOnReady = false;
        this.player.audioEl.play().catch(err =>
          console.warn('PlayerComponent: autoplay blocked', err)
        );
      }
    });

    this.wavesurfer.on('interaction', (newTime) => {
      this.player.seek(newTime);
    });

    // Fix race condition: effect() in constructor may have fired before
    // ngAfterViewInit (this.wavesurfer was null → early return → no load).
    // If a track is already queued, load it now that WaveSurfer is ready.
    const pending = this.player.currentTrack();
    if (pending && this.player.playOnReady) {
      const url = this.player.buildAudioUrl(pending);
      if (url) this.wavesurfer.load(url);
    }
  }

  @HostListener('window:keydown.space', ['$event'])
  onSpacebar(event: Event): void {
    if (!this.player.currentTrack()) return;
    const tag = (event.target as HTMLElement).tagName;
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag)) return;
    if ((event.target as HTMLElement).isContentEditable) return;
    event.preventDefault();
    this.player.togglePlay();
  }

  // ── Contextual actions ───────────────────────────────────────────────────

  onDownloadClick(): void {
    if (this.isViewingTrackLoaded()) {
      this.doDownload();
    } else {
      this.pendingAction = 'download';
      this.showConfirmModal.set(true);
    }
  }

  onRecClick(): void {
    if (this.isViewingTrackLoaded()) {
      this.player.recRequested.update(n => n + 1);
    } else {
      this.pendingAction = 'rec';
      this.showConfirmModal.set(true);
    }
  }

  confirmLoadTrack(): void {
    const viewing = this.player.viewingTrack();
    if (viewing) this.player.play(viewing);
    this.showConfirmModal.set(false);
    if (this.pendingAction === 'rec') {
      setTimeout(() => this.player.recRequested.update(n => n + 1), 250);
    } else if (this.pendingAction === 'download') {
      setTimeout(() => this.doDownload(), 250);
    }
    this.pendingAction = null;
  }

  cancelModal(): void {
    this.showConfirmModal.set(false);
    this.pendingAction = null;
  }

  private doDownload(): void {
    const track = this.player.currentTrack();
    if (!track) return;
    // Toujours télécharger la preview (stream_url), jamais le MP3 complet
    const previewUrl = track.stream_url.startsWith('http')
      ? track.stream_url
      : `${environment.apiUrl}${track.stream_url}`;
    const a = document.createElement('a');
    a.href = previewUrl;
    a.download = `${track.title}.mp3`;
    a.click();
  }

  // ── Template helpers ─────────────────────────────────────────────────────

  getImageUrl(): string {
    const track = this.player.currentTrack();
    if (!track?.image_file) return 'assets/placeholders/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(track.image_file);
  }

  mixStatusLabel(ctx: MixOrderContext): string {
    const labels: Record<string, string> = {
      awaiting_acceptance: 'En attente',
      accepted:            'Acceptée',
      processing:          'En cours',
      delivered:           'Livrée',
      revision1:           'Révision 1',
      revision2:           'Révision 2',
      completed:           'Terminée',
      rejected:            'Refusée',
      refunded:            'Remboursée',
    };
    return labels[ctx.status] ?? ctx.status;
  }

  formatTime(seconds: number): string {
    if (!seconds || isNaN(seconds) || !isFinite(seconds)) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  onVolumeChange(event: Event): void {
    const val = parseFloat((event.target as HTMLInputElement).value);
    this.player.setVolume(val);
  }

  ngOnDestroy(): void {
    this.wavesurfer?.destroy();
    this.wavesurfer = null;
  }

}
