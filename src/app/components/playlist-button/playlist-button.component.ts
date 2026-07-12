import { ChangeDetectionStrategy, Component, Input, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Track } from '../../services/track.service';
import { environment } from '../../../environments/environment';
import { ImgFallbackDirective } from '../../directives/img-fallback.directive';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-playlist-button',
  standalone: true,
  imports: [CommonModule, ImgFallbackDirective],
  templateUrl: './playlist-button.component.html',
  styleUrls: ['./playlist-button.component.scss'],
})
export class PlaylistButtonComponent {

  @Input() track!: Track;

  private router = inject(Router);

  coverUrl(): string {
    const img = this.track.first_playlist_image;
    if (!img) return '/assets/placeholders/placeholder-track.png';
    if (img.startsWith('http')) return img;
    return `${environment.apiUrl}/db_assets/${img}`;
  }

  goToPlaylists(event: MouseEvent): void {
    event.stopPropagation();
    this.router.navigate(
      ['/profile', this.track.composer_user.username],
      { queryParams: { highlight_track: this.track.id } },
    );
  }
}
