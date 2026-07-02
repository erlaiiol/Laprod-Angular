import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { UserService, UserProfile, UserTrack } from '../../services/user.service';
import { AuthService } from '../../services/auth.service';
import { PlayerService } from '../../services/player.service';
import { TrackService } from '../../services/track.service';
import { ToastService } from '../../services/toast.service';
import { PlaylistService, Playlist } from '../../services/playlist.service';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { ShareButtonComponent } from '../../components/share-button/share-button.component';
import { environment } from '../../../environments/environment';

const TRACKS_PER_PAGE    = 12;
const PLAYLISTS_PER_PAGE = 8;

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, RouterLink, PaginationComponent, ShareButtonComponent],
  templateUrl: './profile.component.html',
  styleUrl:    './profile.component.scss',
})
export class ProfileComponent implements OnInit {

  staticBase = `/db_assets/`;

  loading          = signal(true);
  error            = signal<string | null>(null);
  profile          = signal<UserProfile | null>(null);
  playlists        = signal<Playlist[]>([]);
  containingIds    = signal(new Set<number>());
  highlightTrackId = signal<number | null>(null);

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
    this.route.paramMap.subscribe(params => {
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

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
  }
}
