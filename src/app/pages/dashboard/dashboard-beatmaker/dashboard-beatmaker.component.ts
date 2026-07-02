import { Component, OnInit, signal, inject, effect, untracked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../services/auth.service';
import {
  DashboardService, BeatmakerDashboard, BeatmakerTrack, SaleRecord,
} from '../../../services/dashboard.service';
import { TrackService } from '../../../services/track.service';
import { CudTrackService } from '../../../services/cud-track.service';
import { ToastService } from '../../../services/toast.service';
import { PlaylistService, Playlist } from '../../../services/playlist.service';
import { LicenseService, ComposerLicense, ComposerLicensesData } from '../../../services/license.service';
import { LicenseBadgeComponent } from '../../../components/license-badge/license-badge.component';
import { UploadStatusService } from '../../../services/upload-status.service';
import { environment } from '../../../../environments/environment';

export interface TrackViewStat {
  track_id:    number;
  total_views:  number;
  unique_views: number;
}

type Tab = 'tracks' | 'sales' | 'playlists' | 'licenses';

@Component({
  selector: 'app-dashboard-beatmaker',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, LicenseBadgeComponent],
  templateUrl: './dashboard-beatmaker.component.html',
  styleUrls: ['./dashboard-beatmaker.component.scss'],
})
export class DashboardBeatmakerComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  data      = signal<BeatmakerDashboard | null>(null);
  activeTab = signal<Tab>('tracks');

  // Playlists tab state
  playlists        = signal<Playlist[]>([]);
  playlistsLoading = signal(false);
  showCreateForm   = signal(false);
  newTitle         = '';
  creating         = signal(false);
  editingId        = signal<number | null>(null);
  editTitle        = '';
  renameSaving     = signal(false);

  // Image pour la création
  newImageFile     = signal<File | null>(null);
  newImagePreview  = signal<string | null>(null);
  // Image update per-card (ID de la playlist en cours de mise à jour)
  imageUpdatingId  = signal<number | null>(null);

  viewStats        = signal<TrackViewStat[]>([]);
  viewStatsLoading = signal(false);

  soldLicenses        = signal<ComposerLicensesData | null>(null);
  soldLicensesLoading = signal(false);
  licenseFilter       = signal<'all' | 'active' | 'expired' | 'exclusive'>('all');

  readonly auth          = inject(AuthService);
  private dashboardSvc   = inject(DashboardService);
  private trackSvc       = inject(TrackService);
  private cudTrackSvc    = inject(CudTrackService);
  private router         = inject(Router);
  private toast          = inject(ToastService);
  private playlistSvc    = inject(PlaylistService);
  private licenseSvc     = inject(LicenseService);
  private uploadStatusSvc = inject(UploadStatusService);

  constructor() {
    // Quand le worker d'upload termine (toast de progression), rafraîchir
    // automatiquement la liste des beats sans que l'utilisateur recharge la page.
    effect(() => {
      const status  = this.uploadStatusSvc.status();
      const trackId = this.uploadStatusSvc.trackId();
      if (status !== 'done' || !trackId) return;

      untracked(() => {
        this.dashboardSvc.getBeatmakerDashboard().subscribe({
          next: (res) => { if (res.success) this.data.set(res.data!); },
        });
      });
    });
  }

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.dashboardSvc.getBeatmakerDashboard().subscribe({
      next: (res) => {
        if (res.success) this.data.set(res.data!);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger l\'espace beatmaker.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger l\'espace beatmaker.');
        this.loading.set(false);
      },
    });

    this.viewStatsLoading.set(true);
    this.trackSvc.getViewStats().subscribe({
      next: res => { this.viewStats.set(res.data?.stats ?? []); this.viewStatsLoading.set(false); },
      error: () => this.viewStatsLoading.set(false),
    });
  }

  validateSuggestion(trackId: number): void {
    this.cudTrackSvc.validateAiSuggestion(trackId).subscribe({
      next: () => {
        this.data.update(d => d ? {
          ...d,
          tracks: d.tracks.map(t => t.id === trackId ? { ...t, is_ai_suggested: false } : t),
        } : d);
        this.toast.showToast({ level: 'success', message: 'Suggestions validées.' });
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Erreur lors de la validation.' }),
    });
  }

  viewStatFor(trackId: number): TrackViewStat {
    return this.viewStats().find(s => s.track_id === trackId)
      ?? { track_id: trackId, total_views: 0, unique_views: 0 };
  }

  setTab(tab: Tab): void {
    this.activeTab.set(tab);
    if (tab === 'playlists' && this.playlists().length === 0) {
      this.loadPlaylists();
    }
    if (tab === 'licenses' && !this.soldLicenses()) {
      this.loadSoldLicenses();
    }
  }

  private loadSoldLicenses(): void {
    this.soldLicensesLoading.set(true);
    this.licenseSvc.getComposerLicenses().subscribe({
      next: (res) => {
        if (res.success) this.soldLicenses.set(res.data!);
        this.soldLicensesLoading.set(false);
      },
      error: () => {
        this.toast.showToast({ level: 'error', message: 'Impossible de charger vos licences vendues.' });
        this.soldLicensesLoading.set(false);
      },
    });
  }

  filteredLicenses(): ComposerLicense[] {
    const data = this.soldLicenses();
    if (!data) return [];
    const all = data.licenses;
    switch (this.licenseFilter()) {
      case 'active':    return all.filter(l => l.license_status === 'active');
      case 'expired':   return all.filter(l => l.license_status === 'expired');
      case 'exclusive': return all.filter(l => l.is_exclusive);
      default:          return all;
    }
  }

  loadPlaylists(): void {
    this.playlistsLoading.set(true);
    this.playlistSvc.getMyPlaylists().subscribe({
      next: res => { this.playlists.set(res.data ?? []); this.playlistsLoading.set(false); },
      error: () => this.playlistsLoading.set(false),
    });
  }

  onCreateImageSelected(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (!file) return;
    this.newImageFile.set(file);
    const prev = this.newImagePreview();
    if (prev) URL.revokeObjectURL(prev);
    this.newImagePreview.set(URL.createObjectURL(file));
  }

  cancelCreate(): void {
    this.showCreateForm.set(false);
    this.newTitle = '';
    const prev = this.newImagePreview();
    if (prev) URL.revokeObjectURL(prev);
    this.newImageFile.set(null);
    this.newImagePreview.set(null);
  }

  createPlaylist(): void {
    const title = this.newTitle.trim();
    if (!title) return;
    this.creating.set(true);
    const fd = new FormData();
    fd.append('title', title);
    const img = this.newImageFile();
    if (img) fd.append('image', img);
    this.playlistSvc.createPlaylist(fd).subscribe({
      next: res => {
        this.playlists.update(list => [res.data!, ...list]);
        this.cancelCreate();
        this.creating.set(false);
      },
      error: () => {
        this.creating.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors de la création.' });
      },
    });
  }

  onPlaylistImageSelected(pl: Playlist, event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (!file) return;
    this.imageUpdatingId.set(pl.id);
    const fd = new FormData();
    fd.append('title', pl.title);
    fd.append('image', file);
    this.playlistSvc.updatePlaylist(pl.id, fd).subscribe({
      next: res => {
        this.playlists.update(list => list.map(p => p.id === pl.id ? res.data! : p));
        this.imageUpdatingId.set(null);
      },
      error: () => {
        this.imageUpdatingId.set(null);
        this.toast.showToast({ level: 'error', message: "Erreur lors du changement d'image." });
      },
    });
  }

  startRename(pl: Playlist): void {
    this.editingId.set(pl.id);
    this.editTitle = pl.title;
  }

  saveRename(pl: Playlist): void {
    const title = this.editTitle.trim();
    if (!title || title === pl.title) { this.cancelRename(); return; }
    this.renameSaving.set(true);
    const fd = new FormData();
    fd.append('title', title);
    this.playlistSvc.updatePlaylist(pl.id, fd).subscribe({
      next: res => {
        this.playlists.update(list => list.map(p => p.id === pl.id ? res.data! : p));
        this.cancelRename();
        this.renameSaving.set(false);
      },
      error: () => {
        this.renameSaving.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors du renommage.' });
      },
    });
  }

  cancelRename(): void { this.editingId.set(null); this.editTitle = ''; }

  deletePlaylist(pl: Playlist): void {
    if (!confirm(`Supprimer la playlist "${pl.title}" ?`)) return;
    this.playlistSvc.deletePlaylist(pl.id).subscribe({
      next: () => this.playlists.update(list => list.filter(p => p.id !== pl.id)),
      error: () => this.toast.showToast({ level: 'error', message: 'Erreur lors de la suppression.' }),
    });
  }

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/db_assets/${path}` : '/assets/placeholders/placeholder-track.png';
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  formatLabel(format: string): string {
    const labels: Record<string, string> = { mp3: 'MP3', wav: 'WAV', stems: 'STEMS' };
    return labels[format] ?? format.toUpperCase();
  }
}
