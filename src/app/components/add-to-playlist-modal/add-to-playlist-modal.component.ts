import { Component, Input, Output, EventEmitter, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
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

  playlists      = signal<Playlist[]>([]);
  containingIds  = signal(new Set<number>());
  loading        = signal(true);
  showCreate     = signal(false);
  newTitle       = '';
  creating       = signal(false);

  private playlistSvc = inject(PlaylistService);
  private auth        = inject(AuthService);
  private toast       = inject(ToastService);

  ngOnInit(): void {
    const username = this.auth.currentUser()?.username ?? '';
    this.playlistSvc.getMyPlaylists().subscribe({
      next: res => {
        this.playlists.set(res.data ?? []);
        // Charger les IDs de playlists contenant ce track
        if (this.trackId && username) {
          this.playlistSvc.getContaining(this.trackId, username).subscribe({
            next: r => {
              this.containingIds.set(new Set(r.data ?? []));
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

  toggle(pl: Playlist, event: Event): void {
    const checked = (event.target as HTMLInputElement).checked;
    if (checked) {
      this.playlistSvc.addTrack(pl.id, this.trackId).subscribe({
        next: () => {
          const ids = new Set(this.containingIds());
          ids.add(pl.id);
          this.containingIds.set(ids);
          this.playlists.update(list =>
            list.map(p => p.id === pl.id ? { ...p, track_count: p.track_count + 1 } : p)
          );
        },
        error: () => this.toast.showToast({ level: 'error', message: 'Impossible d\'ajouter le track.' }),
      });
    } else {
      this.playlistSvc.removeTrack(pl.id, this.trackId).subscribe({
        next: () => {
          const ids = new Set(this.containingIds());
          ids.delete(pl.id);
          this.containingIds.set(ids);
          this.playlists.update(list =>
            list.map(p => p.id === pl.id ? { ...p, track_count: Math.max(0, p.track_count - 1) } : p)
          );
        },
        error: () => this.toast.showToast({ level: 'error', message: 'Impossible de retirer le track.' }),
      });
    }
  }

  createAndAdd(): void {
    const title = this.newTitle.trim();
    if (!title) return;
    this.creating.set(true);
    const fd = new FormData();
    fd.append('title', title);
    this.playlistSvc.createPlaylist(fd).subscribe({
      next: res => {
        const pl = res.data!;
        this.playlists.update(list => [pl, ...list]);
        this.creating.set(false);
        this.newTitle = '';
        this.showCreate.set(false);
        // Ajouter le track à la nouvelle playlist si trackId présent
        if (this.trackId) {
          this.playlistSvc.addTrack(pl.id, this.trackId).subscribe({
            next: () => {
              const ids = new Set(this.containingIds());
              ids.add(pl.id);
              this.containingIds.set(ids);
            },
          });
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
