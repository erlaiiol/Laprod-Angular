import { ChangeDetectionStrategy, Component, OnInit, signal, computed, inject, DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { UserService, UserProfile, UserTrack } from '../../services/user.service';
import { AuthService, PlanKey, PLAN_ORDER } from '../../services/auth.service';
import { PlayerService } from '../../services/player.service';
import { TrackService, Track } from '../../services/track.service';
import { ToastService } from '../../services/toast.service';
import { PlaylistService, Playlist } from '../../services/playlist.service';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { ShareButtonComponent } from '../../components/share-button/share-button.component';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { BetaBadgeComponent } from '../../components/beta-badge/beta-badge.component';
import { environment } from '../../../environments/environment';
import { FormatDatePipe } from '../../pipes/format-date.pipe';
import { ImgFallbackDirective } from '../../directives/img-fallback.directive';

const TRACKS_PER_PAGE    = 12;
const PLAYLISTS_PER_PAGE = 8;

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, RouterLink, PaginationComponent, ShareButtonComponent, TrackCardComponent, BetaBadgeComponent, FormatDatePipe, ImgFallbackDirective],
  templateUrl: './profile.component.html',
  styleUrl:    './profile.component.scss',
})
export class ProfileComponent implements OnInit {

  staticBase = `${environment.apiUrl}/db_assets/`;

  loading          = signal(true);
  error            = signal<string | null>(null);
  profile          = signal<UserProfile | null>(null);
  playlists        = signal<Playlist[]>([]);
  containingIds    = signal(new Set<number>());
  highlightTrackId = signal<number | null>(null);

  displayMode = signal<'list' | 'gallery' | 'compact'>(
    (localStorage.getItem('laprod_display_mode') as 'list' | 'gallery' | 'compact') ?? 'gallery'
  );

  // Pagination tracks
  trackPage = signal(1);
  tracksTotalPages = computed(() =>
    Math.max(1, Math.ceil((this.profile()?.tracks.length ?? 0) / TRACKS_PER_PAGE))
  );
  pagedTracks = computed(() => {
    const tracks = this.profile()?.tracks ?? [];
    const start  = (this.trackPage() - 1) * TRACKS_PER_PAGE;
    return tracks.slice(start, start + TRACKS_PER_PAGE);
  });

  // Pagination playlists
  playlistPage = signal(1);
  playlistsTotalPages = computed(() =>
    Math.max(1, Math.ceil(this.playlists().length / PLAYLISTS_PER_PAGE))
  );
  pagedPlaylists = computed(() => {
    const pls   = this.playlists();
    const start = (this.playlistPage() - 1) * PLAYLISTS_PER_PAGE;
    return pls.slice(start, start + PLAYLISTS_PER_PAGE);
  });

  private playlistSvc = inject(PlaylistService);
  private destroyRef  = inject(DestroyRef);

  // ── Hub de rôles (propre profil uniquement) ─────────────────────────────────
  // Espaces + outils vendeur affichés selon les rôles réellement possédés,
  // éditables à tout moment via /profile/edit. Plus de notion de "vue active".
  isArtist                = computed(() => this.auth.isArtist());
  isBeatmaker             = computed(() => this.auth.isBeatmaker());
  isMixEngineer           = computed(() => this.auth.isMixEngineer());
  isCertifiedMixEngineer  = computed(() => this.auth.isCertifiedMixEngineer());
  isProducer              = computed(() => this.auth.isProducer());
  mixSamplePending        = computed(() => this.auth.mixSamplePending());
  showSellerTools         = computed(() => this.isBeatmaker() || this.isCertifiedMixEngineer());
  showWallet              = computed(() => this.isBeatmaker() || this.isMixEngineer());

  constructor(
    private route:    ActivatedRoute,
    private router:   Router,
    private userSvc:  UserService,
    readonly auth:    AuthService,
    private player:   PlayerService,
    private trackSvc: TrackService,
    private toast:    ToastService,
  ) {}

  ngOnInit(): void {
    // paramMap ne complète jamais : sans teardown, l'abonnement survivrait
    // à chaque destruction du composant.
    this.route.paramMap
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(params => {
        const username = params.get('username') ?? '';
        this.loadProfile(username);
      });
  }

  loadProfile(username: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.playlists.set([]);
    this.containingIds.set(new Set());
    this.trackPage.set(1);
    this.playlistPage.set(1);

    const highlightTrack = Number(this.route.snapshot.queryParamMap.get('highlight_track')) || null;
    this.highlightTrackId.set(highlightTrack);

    this.userSvc.getProfile(username).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.profile.set(res.data.user);
          if (res.data.user.roles.is_beatmaker) {
            this.loadPlaylists(username, highlightTrack);
          }
        } else {
          this.error.set(res.feedback?.message ?? 'Profil introuvable.');
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger le profil.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger le profil.');
      },
    });
  }

  private loadPlaylists(username: string, highlightTrackId: number | null): void {
    this.playlistSvc.getByBeatmaker(username).subscribe({
      next: res => {
        this.playlists.set(res.data ?? []);
        if (highlightTrackId && (res.data ?? []).length > 0) {
          this.playlistSvc.getContaining(highlightTrackId, username).subscribe({
            next: r => this.containingIds.set(new Set(r.data ?? [])),
          });
        }
      },
    });
  }

  goToTrackPage(p: number): void {
    this.trackPage.set(p);
    document.querySelector('.tracks-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  goToPlaylistPage(p: number): void {
    this.playlistPage.set(p);
    document.querySelector('.playlists-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  playlistImgUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return `${environment.apiUrl}/db_assets/${path}`;
  }

  /** Le badge « Master Pro » est acquis par l'abonnement, à partir du Semi-Pro
   *  (l'autre voie étant la certification par un admin, testée séparément). */
  hasMasterProBadge(p: UserProfile): boolean {
    const plan = (p.subscription_plan ?? 'free') as PlanKey;
    return PLAN_ORDER.indexOf(plan) >= PLAN_ORDER.indexOf('semi_pro');
  }

  isOwnProfile(): boolean {
    const currentUser = this.auth.currentUser();
    const profile     = this.profile();
    return !!(currentUser && profile && currentUser.id === profile.id);
  }

  playTrack(track: UserTrack): void {
    this.player.play({
      id:         track.id,
      title:      track.title,
      stream_url: track.stream_url,
      image_file: track.image_file,
      price_mp3:  track.price_mp3,
      composer_user: { username: this.profile()?.username ?? '' },
    } as any);
  }

  tagBgColor(color: string | null): string {
    return this.trackSvc.darkenColor(color ?? '#6b7280', 0.15);
  }

  tagBorderColor(color: string | null): string {
    return this.trackSvc.darkenColor(color ?? '#6b7280', 0.35);
  }

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }


  setDisplayMode(mode: 'list' | 'gallery' | 'compact'): void {
    this.displayMode.set(mode);
    localStorage.setItem('laprod_display_mode', mode);
  }

  asTrack(t: UserTrack): Track {
    return {
      id:                   t.id,
      title:                t.title,
      composer_user:        { username: this.profile()!.username },
      stream_url:           t.stream_url,
      image_file:           t.image_file,
      image_thumb:          t.image_thumb,
      image_large:          t.image_large,
      bpm:                  t.bpm,
      key:                  t.key,
      style:                t.style ?? '',
      price_mp3:            t.price_mp3 ?? 0,
      tags:                 t.tags.map(tag => ({ ...tag, category: tag.category ?? '', color: tag.color ?? '' })),
      similar_artists:      t.similar_artists,
      is_approved:          t.is_approved,
      is_ai_suggested:      false,
      full_stream_url:      null,
      playlist_count:       0,
      first_playlist_image: null,
    };
  }
}
