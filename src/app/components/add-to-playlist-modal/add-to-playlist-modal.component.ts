import { Component, Input, Output, EventEmitter, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { PlaylistService, Playlist } from '../../services/playlist.service';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-add-to-playlist-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './add-to-playlist-modal.component.html',
  styleUrls: ['./add-to-playlist-modal.component.scss'],
})
export class AddToPlaylistModalComponent implements OnInit {

  @Input() trackId!: number;
  @Output() closed = new EventEmitter<void>();

  playlists        = signal<Playlist[]>([]);
  loading          = signal(true);
  showCreate       = signal(false);
  newTitle         = '';
  creating         = signal(false);
  saving           = signal(false);

  // État initial (vient de l'API) — ne change qu'après sauvegarde
  initialIds       = new Set<number>();
  // État en cours d'édition (local, pas encore persisté)
  pendingIds       = signal(new Set<number>());

  hasPendingChanges = computed(() => {
    const p = this.pendingIds();
    const i = this.initialIds;
    if (p.size !== i.size) return true;
    for (const id of p) if (!i.has(id)) return true;
    return false;
  });

  // Image pour la création d'une nouvelle playlist
  newImageFile     = signal<File | null>(null);
  newImagePreview  = signal<string | null>(null);

  private playlistSvc = inject(PlaylistService);
  private auth        = inject(AuthService);
  private toast       = inject(ToastService);

  ngOnInit(): void {
    const username = this.auth.currentUser()?.username ?? '';
    this.playlistSvc.getMyPlaylists().subscribe({
      next: res => {
        this.playlists.set(res.data ?? []);
        if (this.trackId && username) {
          this.playlistSvc.getContaining(this.trackId, username).subscribe({
            next: r => {
              const ids = new Set<number>(r.data ?? []);
              this.initialIds = ids;
              this.pendingIds.set(new Set(ids));
              this.loading.set(false);
            },
            error: () => this.loading.set(false),
          });
        } else {
          this.loading.set(false);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  togglePending(pl: Playlist): void {
    const s = new Set(this.pendingIds());
    s.has(pl.id) ? s.delete(pl.id) : s.add(pl.id);
    this.pendingIds.set(s);
  }

  async saveChanges(): Promise<void> {
    if (this.saving()) return;
    this.saving.set(true);
    const toAdd    = [...this.pendingIds()].filter(id => !this.initialIds.has(id));
    const toRemove = [...this.initialIds].filter(id => !this.pendingIds().has(id));
    try {
      for (const id of toAdd)    await firstValueFrom(this.playlistSvc.addTrack(id, this.trackId));
      for (const id of toRemove) await firstValueFrom(this.playlistSvc.removeTrack(id, this.trackId));
      this.toast.showToast({ level: 'success', message: 'Playlists mises à jour.' });
      this.close();
    } catch {
      this.toast.showToast({ level: 'error', message: 'Erreur lors de la mise à jour.' });
      this.saving.set(false);
    }
  }

  onCreateImageSelected(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (!file) return;
    this.newImageFile.set(file);
    const prev = this.newImagePreview();
    if (prev) URL.revokeObjectURL(prev);
    this.newImagePreview.set(URL.createObjectURL(file));
  }

  createAndAdd(): void {
    const title = this.newTitle.trim();
    if (!title) return;
    this.creating.set(true);
    const fd = new FormData();
    fd.append('title', title);
    const img = this.newImageFile();
    if (img) fd.append('image', img);
    this.playlistSvc.createPlaylist(fd).subscribe({
      next: res => {
        const pl = res.data!;
        this.playlists.update(list => [pl, ...list]);
        this.creating.set(false);
        this.newTitle = '';
        this.newImageFile.set(null);
        const prev = this.newImagePreview();
        if (prev) URL.revokeObjectURL(prev);
        this.newImagePreview.set(null);
        this.showCreate.set(false);
        if (this.trackId) {
          const s = new Set(this.pendingIds());
          s.add(pl.id);
          this.pendingIds.set(s);
        }
      },
      error: () => {
        this.creating.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors de la création.' });
      },
    });
  }

  imgUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return `${environment.apiUrl}/db_assets/${path}`;
  }

  close(): void {
    this.closed.emit();
  }
}
