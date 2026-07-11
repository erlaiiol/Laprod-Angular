import {
  Component, OnInit, OnDestroy, signal, inject, computed,
  ChangeDetectionStrategy, ChangeDetectorRef, effect, untracked
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { TrackService, TrackDetail, PublishedTopline, OwnedLicense } from '../../services/track.service';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { FilterStateService } from '../../services/filter-state.service';
import { ToplineService } from '../../services/topline.service';
import { ToplineStatusService } from '../../services/topline-status.service';
import { ToplineRecorderComponent } from '../../components/topline-recorder/topline-recorder.component';
import { FavoriteButtonComponent } from '../../components/favorite-button/favorite-button.component';
import { AddToPlaylistModalComponent } from '../../components/add-to-playlist-modal/add-to-playlist-modal.component';
import { ShareButtonComponent } from '../../components/share-button/share-button.component';
import { LicenseBadgeComponent } from '../../components/license-badge/license-badge.component';
import { FavoritesService } from '../../services/favorites.service';
import { ToastService } from '../../services/toast.service';
import { FormatDatePipe } from '../../pipes/format-date.pipe';

@Component({
  selector: 'app-track-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, ToplineRecorderComponent, FavoriteButtonComponent, AddToPlaylistModalComponent, ShareButtonComponent, LicenseBadgeComponent, FormatDatePipe],
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
  confirmFormat     = signal<'mp3' | 'wav' | 'stems' | null>(null);

  editingToplineId  = signal<number | null>(null);
  editingDesc       = signal('');

  private route             = inject(ActivatedRoute);
  private router            = inject(Router);
  private trackSvc          = inject(TrackService);
  private toplineSvc        = inject(ToplineService);
  private toplineStatusSvc  = inject(ToplineStatusService);
  private http              = inject(HttpClient);
  player                    = inject(PlayerService);
  auth                      = inject(AuthService);
  private cdr               = inject(ChangeDetectorRef);
  private toast             = inject(ToastService);
  private filterState       = inject(FilterStateService);

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

    // Quand le worker topline termine (toast de progression), rafraîchir
    // automatiquement la liste si la topline appartient au track affiché.
    // untracked() sur track() évite de ré-entrer dans l'effect après track.set().
    effect(() => {
      const status      = this.toplineStatusSvc.status();
      const toplineId   = this.toplineStatusSvc.toplineId();
      const beatTrackId = this.toplineStatusSvc.beatTrackId();
      if (status !== 'done' || !toplineId) return;

      const track = untracked(() => this.track());
      if (!track || beatTrackId !== track.id) return;

      untracked(() => {
        this.toplineSvc.getMyToplines(track.id).subscribe({
          next: (res) => {
            if (!res.success || !res.data?.toplines) return;
            const fresh   = res.data.toplines;
            const current = this.track();
            if (!current) return;
            // Garder les toplines publiées d'autres artistes + toutes les miennes
            const merged = [
              ...current.toplines.filter(t => t.is_published && !fresh.some(f => f.id === t.id)),
              ...fresh,
            ];
            this.track.set({ ...current, toplines: merged });
            this.cdr.markForCheck();
          },
        });
      });
    });
  }

  ngOnInit(): void {
    const id       = Number(this.route.snapshot.paramMap.get('id'));
    const autoplay = !!this.route.snapshot.queryParamMap.get('autoplay');
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
          this.trackSvc.recordView(t.id, 'detail');
          if (autoplay) this.player.play(t as any, 'share');
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

  goBack(): void {
    this.router.navigate(['/']);
  }

  onTagClick(tagName: string): void {
    if (!this.filterState.addTag(tagName)) return;
    this.toast.showToast({ level: 'info', message: `#${tagName} ajouté aux filtres` });
  }

  onStyleClick(style: string | null): void {
    if (!style) return;
    if (!this.filterState.addStyle(style)) return;
    this.toast.showToast({ level: 'info', message: `Style « ${style} » ajouté aux filtres` });
  }

  onArtistClick(name: string): void {
    if (!this.filterState.addSimilarArtist(name)) return;
    this.toast.showToast({ level: 'info', message: `Artiste « ${name} » ajouté aux filtres` });
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholders/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(path);
  }

  tagBgColor(color: string): string     { return this.trackSvc.darkenColor(color, 0.15); }
  tagBorderColor(color: string): string { return this.trackSvc.darkenColor(color, 0.35); }


  isThisTrackPlaying(): boolean {
    const t = this.track();
    return !!t && this.player.currentTrack()?.id === t.id && this.player.isPlaying();
  }

  playThisTrack(): void {
    const t = this.track();
    if (!t) return;
    if (this.player.isPlaying() && this.player.currentTrack()?.id === t.id) {
      this.player.pause();
    } else {
      // Toujours appeler play() — gère aussi la reprise du même track
      // et le cas où playOnReady était bloqué sur même URL.
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

  startEditDesc(tl: PublishedTopline): void {
    this.editingToplineId.set(tl.id);
    this.editingDesc.set(tl.description ?? '');
    this.cdr.markForCheck();
  }

  cancelEditDesc(): void {
    this.editingToplineId.set(null);
    this.editingDesc.set('');
    this.cdr.markForCheck();
  }

  saveDesc(tl: PublishedTopline): void {
    const desc = this.editingDesc().trim();
    this.toplineSvc.updateDescription(tl.id, desc).subscribe({
      next: (res) => {
        if (res.success) {
          const t = this.track();
          if (t) {
            this.track.set({
              ...t,
              toplines: t.toplines.map(x => x.id === tl.id ? { ...x, description: desc || null } : x),
            });
          }
          this.editingToplineId.set(null);
          this.editingDesc.set('');
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.toast.showToast({ level: 'error', message: 'Impossible de contacter le serveur.' });
        this.cdr.markForCheck();
      },
    });
  }

  ownedLicense(format: 'mp3' | 'wav' | 'stems'): OwnedLicense | null {
    return this.track()?.owned_licenses?.[format] ?? null;
  }

  requestBuy(format: 'mp3' | 'wav' | 'stems'): void {
    if (this.ownedLicense(format)) {
      this.confirmFormat.set(format);
    } else {
      this.router.navigate(['/contract', this.track()!.id, format]);
    }
  }

  cancelBuy(): void {
    this.confirmFormat.set(null);
  }

  proceedBuy(): void {
    const fmt = this.confirmFormat();
    const t   = this.track();
    if (!fmt || !t) return;
    this.confirmFormat.set(null);
    this.router.navigate(['/contract', t.id, fmt]);
  }

  canEditTrack = computed(() => {
    const user = this.auth.currentUser();
    const t = this.track();
    if (!user || !t) return false;
    return user.id === t.composer_user.id || user.roles?.is_admin;
  });

  isExclusiveSold = computed(() => this.track()?.is_exclusive_sold === true);

}
