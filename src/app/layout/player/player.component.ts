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
  untracked,
  ChangeDetectionStrategy
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, Router } from '@angular/router';
// Import type-only : wavesurfer.js n'entre pas dans le bundle initial,
// il est chargé dynamiquement à la première lecture (voir initWavesurfer).
import type WaveSurfer from 'wavesurfer.js';
import { PlayerService } from '../../services/player.service';
import { TrackService } from '../../services/track.service';
import { AuthService } from '../../services/auth.service';
import { MixOrderContext } from '../../services/player.service';
import { environment } from '../../../environments/environment';
import { ImgFallbackDirective } from '../../directives/img-fallback.directive';

@Component({
  selector: 'app-player',
  standalone: true,
  imports: [CommonModule, RouterLink, ImgFallbackDirective],
  templateUrl: './player.component.html',
  styleUrls: ['./player.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class PlayerComponent implements AfterViewInit, OnDestroy {

  @ViewChild('waveformContainer') waveformContainer!: ElementRef<HTMLDivElement>;

  player   = inject(PlayerService);
  trackSvc = inject(TrackService);
  auth     = inject(AuthService);
  private router = inject(Router);

  /** Whether the player is in track_detail context (viewingTrack is set). */
  isDetailContext    = computed(() => this.player.viewingTrack() !== null);
  /** Whether the player is showing a mix order reference/preview. */
  isMixOrderContext  = computed(() => this.player.viewingMixOrder() !== null);

  /** Always true: buildAudioUrl() only ever uses stream_url (preview).
   *  full_stream_url requires an Authorization header that <audio> cannot send. */
  isPreview = computed(() => !!this.player.currentTrack());

  /** True when the currently playing track IS the viewing track → actions work directly. */
  isViewingTrackLoaded = computed(() => {
    const v = this.player.viewingTrack();
    const c = this.player.currentTrack();
    return !!v && !!c && v.id === c.id;
  });

  showConfirmModal = signal(false);
  private pendingAction: 'download' | 'rec' | null = null;

  private wavesurfer: WaveSurfer | null = null;
  private initPromise: Promise<void> | null = null;
  private destroyed = false;
  // La vue doit exister avant de créer WaveSurfer (#waveformContainer) ;
  // signal lu dans l'effect pour qu'il se rejoue après ngAfterViewInit.
  private viewReady = signal(false);
  // Dernière URL chargée dans WaveSurfer — évite les rechargements quand seul
  // le contexte change (ex: viewingTrack s'active sur le même track en lecture).
  private _lastLoadedUrl = '';
  private _lastLoadedTrackId = 0;

  constructor() {
    effect(() => {
      const track = this.player.currentTrack();
      if (!track || !this.viewReady()) return;
      const url = this.player.buildAudioUrl(track);
      if (!url) return;

      if (!this.wavesurfer) {
        // Première lecture : on charge le moteur à la demande, puis on
        // recharge le track le plus récent (il a pu changer pendant l'import).
        this.initPromise ??= this.initWavesurfer();
        this.initPromise.then(() => {
          if (this.destroyed || !this.wavesurfer) return;
          const latest = untracked(() => this.player.currentTrack());
          if (!latest) return;
          const latestUrl = this.player.buildAudioUrl(latest);
          if (latestUrl) this.loadIfNeeded(latest.id, latestUrl);
        });
        return;
      }

      this.loadIfNeeded(track.id, url);
    });
  }

  ngAfterViewInit(): void {
    this.viewReady.set(true);
  }

  private async initWavesurfer(): Promise<void> {
    const { default: WaveSurfer } = await import('wavesurfer.js');
    if (this.destroyed) return;

    const ws = WaveSurfer.create({
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

    ws.on('ready', () => {
      if (this.player.playOnReady) {
        this.player.playOnReady = false;
        this.player.audioEl.play().catch(err =>
          console.warn('PlayerComponent: autoplay blocked', err)
        );
      }
    });

    ws.on('interaction', (newTime) => {
      this.player.seek(newTime);
    });

    this.wavesurfer = ws;
  }

  private loadIfNeeded(trackId: number, url: string): void {
    if (url === this._lastLoadedUrl) {
      // Même URL → WaveSurfer ne recharge pas, 'ready' ne refirend pas.
      // Si play() a posé playOnReady, on joue directement.
      if (this.player.playOnReady) {
        this.player.playOnReady = false;
        this.player.audioEl.play().catch(err => console.warn('PlayerComponent: play() direct failed', err));
      }
      return;
    }
    // Même track en cours de lecture, URL différente → changement de contexte
    // (ex: viewingTrack effacé en quittant track-detail). Ne pas recharger pour
    // ne pas couper la lecture. On met à jour la référence silencieusement.
    if (trackId > 0
        && trackId === this._lastLoadedTrackId
        && untracked(() => this.player.isPlaying())) {
      this._lastLoadedUrl = url;
      return;
    }
    this._lastLoadedUrl = url;
    this._lastLoadedTrackId = trackId;
    this.wavesurfer!.load(url);
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
    if (!this.auth.isLoggedIn()) {
      this.router.navigate(['/login']);
      return;
    }
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
    // Pochette miniature de la barre du player → variante thumb.
    return this.trackSvc.getStaticFileUrl(track.image_thumb ?? track.image_file);
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
    this.destroyed = true;
    this.wavesurfer?.destroy();
    this.wavesurfer = null;
  }

}
