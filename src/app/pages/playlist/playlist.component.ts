import { Component, OnInit, signal, inject, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { switchMap, of } from 'rxjs';

import { PlaylistService, PlaylistDetail } from '../../services/playlist.service';
import { Track } from '../../services/track.service';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { FavoritesService } from '../../services/favorites.service';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-playlist',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, TrackCardComponent],
  templateUrl: './playlist.component.html',
  styleUrls: ['./playlist.component.scss'],
})
export class PlaylistComponent implements OnInit {

  playlist = signal<PlaylistDetail | null>(null);
  loading  = signal(true);
  error    = signal<string | null>(null);

  // ── État édition ────────────────────────────────────────────────────────────
  editMode         = signal(false);
  editTitle        = '';
  editImageFile    = signal<File | null>(null);
  editImagePreview = signal<string | null>(null);
  metaSaving       = signal(false);
  removingIds      = signal<Set<number>>(new Set());

  isOwner = computed(() => {
    const u = this.auth.currentUser();
    const p = this.playlist();
    return !!(u && p && u.username === p.beatmaker_username);
  });

  private route       = inject(ActivatedRoute);
  private playlistSvc = inject(PlaylistService);
  private favSvc      = inject(FavoritesService);
  readonly auth       = inject(AuthService);
  private toast       = inject(ToastService);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) { this.error.set('Identifiant invalide.'); this.loading.set(false); return; }

    const openEdit = this.route.snapshot.queryParamMap.get('edit') === '1';

    this.playlistSvc.getPlaylist(id).pipe(
      switchMap(res => {
        if (!res.success || !res.data) return of(res);
        const ids = res.data.tracks.map((t: Track) => t.id);
        if (this.auth.isLoggedIn() && ids.length > 0) {
          return this.favSvc.prefetch(ids).pipe(switchMap(() => of(res)));
        }
        return of(res);
      })
    ).subscribe({
      next: res => {
        if (res.success && res.data) {
          this.playlist.set(res.data);
          if (openEdit && this.isOwner()) {
            this.enterEditMode();
          }
        } else {
          this.error.set('Impossible de charger la playlist.');
        }
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de contacter le serveur.');
        this.loading.set(false);
      },
    });
  }

  coverUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return `${environment.apiUrl}/db_assets/${path}`;
  }

  // ── Édition ─────────────────────────────────────────────────────────────────

  enterEditMode(): void {
    this.editTitle = this.playlist()!.title;
    this.editMode.set(true);
  }

  cancelEdit(): void {
    this.editMode.set(false);
    const prev = this.editImagePreview();
    if (prev) URL.revokeObjectURL(prev);
    this.editImageFile.set(null);
    this.editImagePreview.set(null);
  }

  onEditImageSelected(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (!file) return;
    this.editImageFile.set(file);
    const prev = this.editImagePreview();
    if (prev) URL.revokeObjectURL(prev);
    this.editImagePreview.set(URL.createObjectURL(file));
  }

  saveMeta(): void {
    const title = this.editTitle.trim();
    if (!title || this.metaSaving()) return;
    const pl = this.playlist()!;
    this.metaSaving.set(true);
    const fd = new FormData();
    fd.append('title', title);
    const img = this.editImageFile();
    if (img) fd.append('image', img);
    this.playlistSvc.updatePlaylist(pl.id, fd).subscribe({
      next: res => {
        this.playlist.update(p => p ? { ...p, title: res.data!.title, image_file: res.data!.image_file } : p);
        this.cancelEdit();
        this.metaSaving.set(false);
      },
      error: () => {
        this.metaSaving.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors de la sauvegarde.' });
      },
    });
  }

  removeTrack(trackId: number): void {
    const pl = this.playlist();
    if (!pl || this.removingIds().has(trackId)) return;
    this.removingIds.update(s => new Set([...s, trackId]));
    this.playlistSvc.removeTrack(pl.id, trackId).subscribe({
      next: () => {
        this.playlist.update(p =>
          p ? { ...p, tracks: p.tracks.filter((t: Track) => t.id !== trackId), track_count: p.track_count - 1 } : p
        );
        this.removingIds.update(s => { const n = new Set(s); n.delete(trackId); return n; });
      },
      error: () => {
        this.removingIds.update(s => { const n = new Set(s); n.delete(trackId); return n; });
        this.toast.showToast({ level: 'error', message: 'Erreur lors du retrait du track.' });
      },
    });
  }
}
