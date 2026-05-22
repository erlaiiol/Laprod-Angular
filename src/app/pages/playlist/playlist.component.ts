import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { switchMap, of } from 'rxjs';

import { PlaylistService, PlaylistDetail } from '../../services/playlist.service';
import { Track } from '../../services/track.service';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { FavoritesService } from '../../services/favorites.service';
import { AuthService } from '../../services/auth.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-playlist',
  standalone: true,
  imports: [CommonModule, RouterModule, TrackCardComponent],
  templateUrl: './playlist.component.html',
  styleUrls: ['./playlist.component.scss'],
})
export class PlaylistComponent implements OnInit {

  playlist = signal<PlaylistDetail | null>(null);
  loading  = signal(true);
  error    = signal<string | null>(null);

  private route       = inject(ActivatedRoute);
  private playlistSvc = inject(PlaylistService);
  private favSvc      = inject(FavoritesService);
  private auth        = inject(AuthService);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) { this.error.set('Identifiant invalide.'); this.loading.set(false); return; }

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
}
