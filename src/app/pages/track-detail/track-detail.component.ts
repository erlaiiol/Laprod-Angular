import {
  Component, OnInit, OnDestroy, signal, inject, computed,
  ChangeDetectionStrategy, ChangeDetectorRef, effect
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { TrackService, TrackDetail, PublishedTopline } from '../../services/track.service';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { ToplineService } from '../../services/topline.service';
import { ToplineRecorderComponent } from '../../components/topline-recorder/topline-recorder.component';
import { FavoriteButtonComponent } from '../../components/favorite-button/favorite-button.component';
import { AddToPlaylistModalComponent } from '../../components/add-to-playlist-modal/add-to-playlist-modal.component';
import { FavoritesService } from '../../services/favorites.service';
import { ToastService } from '../../services/toast.service';

@Component({
  selector: 'app-track-detail',
  standalone: true,
  imports: [CommonModule, RouterModule, ToplineRecorderComponent, FavoriteButtonComponent, AddToPlaylistModalComponent],
  templateUrl: './track-detail.component.html',
  styleUrls: ['./track-detail.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class TrackDetailComponent implements OnInit, OnDestroy {

  track             = signal<TrackDetail | null>(null);
  loading           = signal(true);
  error             = signal<string | null>(null);
  showRecorder      = signal(false);
  showPlaylistModal = signal(false);

  private route       = inject(ActivatedRoute);
  private trackSvc    = inject(TrackService);
  private toplineSvc  = inject(ToplineService);
  private http        = inject(HttpClient);
  player              = inject(PlayerService);
  auth                = inject(AuthService);
  private cdr         = inject(ChangeDetectorRef);
  private toast       = inject(ToastService);

  // Cache blob URLs pour les toplines privées (libérés dans ngOnDestroy)
  private toplineBlobUrls = new Map<number, string>();
  

  constructor() {
    // Bouton REC du player → ouvre la modale + pause
    effect(() => {
      if (this.player.recRequested() > 0 && this.track()) {
        this.player.pause();
        this.showRecorder.set(true);
        this.cdr.markForCheck();
      }
    });
  }

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) { this.error.set('ID invalide'); this.loading.set(false); return; }

    this.trackSvc.getTrackDetail(id).subscribe({
      next: (res) => {
        if (res.success && res.data?.track) {
          const t = res.data.track;
          // Fusionner toplines publiées + toplines privées de l'utilisateur courant
          const myPrivate = (t.my_toplines ?? []).filter(tl => !tl.is_published);
          const merged = [
            ...t.toplines,
            ...myPrivate.filter(p => !t.toplines.some(pub => pub.id === p.id)),
          ];
          this.track.set({ ...t, toplines: merged });
          this.player.viewingTrack.set(t as any);
        } else {
          this.error.set('Track introuvable.');
        }
        this.loading.set(false);
        this.cdr.markForCheck();
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger ce beat.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger ce beat.');
        this.loading.set(false);
        this.cdr.markForCheck();
      }
    });
  }

  ngOnDestroy(): void {
    this.player.viewingTrack.set(null);
    this.player.recRequested.set(0);
    this.toplineBlobUrls.forEach(url => URL.revokeObjectURL(url));
    this.toplineBlobUrls.clear();
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholders/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(path);
  }

  tagBgColor(color: string): string     { return this.trackSvc.darkenColor(color, 0.15); }
  tagBorderColor(color: string): string { return this.trackSvc.darkenColor(color, 0.35); }

  formatDate(iso: string | null): string {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  isThisTrackPlaying(): boolean {
    const t = this.track();
    return !!t && this.player.currentTrack()?.id === t.id && this.player.isPlaying();
  }

  playThisTrack(): void {
    const t = this.track();
    if (!t) return;
    if (this.player.currentTrack()?.id === t.id) {
      this.player.togglePlay();
    } else {
      this.player.play(t as any);
    }
  }

  playTopline(tl: PublishedTopline): void {
    const t = this.track();
    if (!t) return;

    const doPlay = (streamUrl: string) => {
      this.player.play({
        id:            tl.id,
        title:         `Topline par ${tl.artist_user.username}`,
        composer_user: tl.artist_user as any,
        stream_url:      streamUrl,
        full_stream_url: null,
        image_file:      t.image_file,
        bpm:             t.bpm,
        key:             t.key,
        style:           t.style,
        price_mp3:       0,
        tags:            [],
        is_approved:        true,
        playlist_count:     0,
        first_playlist_image: null,
      });
    };

    // Topline publique : stream direct
    if (tl.is_published) {
      doPlay(tl.stream_url);
      return;
    }

    // Topline privée : fetch blob avec JWT
    const cached = this.toplineBlobUrls.get(tl.id);
    if (cached) {
      if (this.player.currentTrack()?.stream_url === cached) {
        this.player.togglePlay();
      } else {
        doPlay(cached);
      }
      return;
    }

    this.http.get(`${environment.apiUrl}${tl.stream_url}`, {
      headers:      { Authorization: `Bearer ${this.auth.getToken()}` },
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        this.toplineBlobUrls.set(tl.id, url);
        doPlay(url);
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de charger cette topline.' }),
    });
  }

  toggleRecorder(): void {
    const next = !this.showRecorder();
    if (next) this.player.pause();
    this.showRecorder.set(next);
    this.cdr.markForCheck();
  }

  onToplinePublished(tl: PublishedTopline): void {
    const t = this.track();
    if (!t) return;
    this.track.set({ ...t, toplines: [...t.toplines, tl] });
    this.showRecorder.set(false);
    this.cdr.markForCheck();
  }

  isOwnTopline(tl: PublishedTopline): boolean {
    return this.auth.currentUser()?.id === tl.artist_id;
  }

  unpublishTopline(tl: PublishedTopline): void {
    this.toplineSvc.unpublishTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success) {
          const t = this.track();
          if (!t) return;
          this.track.set({ ...t, toplines: t.toplines.map(x => x.id === tl.id ? { ...x, is_published: false } : x) });
          this.cdr.markForCheck();
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de contacter le serveur.' }),
    });
  }

  republishTopline(tl: PublishedTopline): void {
    this.toplineSvc.publishTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success) {
          const t = this.track();
          if (!t) return;
          this.track.set({ ...t, toplines: t.toplines.map(x => x.id === tl.id ? { ...x, is_published: true } : x) });
          this.cdr.markForCheck();
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de contacter le serveur.' }),
    });
  }

  deleteTopline(tl: PublishedTopline): void {
    this.toplineSvc.deleteTopline(tl.id).subscribe({
      next: (res) => {
        if (res.success) {
          const t = this.track();
          if (!t) return;
          this.track.set({ ...t, toplines: t.toplines.filter(x => x.id !== tl.id) });
          this.cdr.markForCheck();
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de contacter le serveur.' }),
    });
  }

  canEditTrack = computed(() => {
    const user = this.auth.currentUser();
    const t = this.track();
    if (!user || !t) return false;
    return user.id === t.composer_user.id || user.roles?.is_admin;
  });

  isExclusiveSold = computed(() => this.track()?.is_exclusive_sold === true);

}
