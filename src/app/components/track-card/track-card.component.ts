// ─────────────────────────────────────────────────────────────────────────────
// COMPOSANT PRÉSENTATIONNEL TrackCard
// Rôle : afficher UN track. Ne sait pas d'où vient le track, ne fetch rien.
// Reçoit ses données de la page parente via @Input().
// Communique vers la page parente via @Output().
// ─────────────────────────────────────────────────────────────────────────────

import { Component, Input, inject, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';

import { Track, TrackService } from '../../services/track.service';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { FavoriteButtonComponent } from '../favorite-button/favorite-button.component';
import { PlaylistButtonComponent } from '../playlist-button/playlist-button.component';
import { ShareButtonComponent } from '../share-button/share-button.component';
import { environment } from '../../../environments/environment';

const MAX_TAGS = 2;

@Component({
  selector: 'app-track-card',
  standalone: true,
  imports: [CommonModule, RouterModule, FavoriteButtonComponent, PlaylistButtonComponent, ShareButtonComponent],
  templateUrl: './track-card.component.html',
  styleUrls:   ['./track-card.component.scss']
})
export class TrackCardComponent {

  @Input() track!: Track;
  @Input() galleryMode = false;

  private trackService  = inject(TrackService);
  private playerService = inject(PlayerService);
  private authService   = inject(AuthService);
  private router        = inject(Router);

  showAllTags     = signal(false);
  showAllArtists  = signal(false);

  showArtists = computed(() => this.authService.preferredCardInfoMode() === 'artists');

  // Tags filtrés par catégorie active (si filtre posé), sinon tous
  private filteredTags = computed(() => {
    const pref = this.authService.preferredTagCategory();
    if (!pref) return this.track.tags;
    const match = this.track.tags.filter(t => t.category === pref);
    return match.length > 0 ? match : this.track.tags;
  });

  visibleTags = computed(() => {
    const tags = this.filteredTags();
    return this.showAllTags() ? tags : tags.slice(0, MAX_TAGS);
  });

  hiddenTagCount = computed(() =>
    this.showAllTags() ? 0 : Math.max(0, this.filteredTags().length - MAX_TAGS)
  );

  canCollapseTags = computed(() =>
    this.showAllTags() && this.filteredTags().length > MAX_TAGS
  );

  toggleTags(event: MouseEvent): void {
    event.stopPropagation();
    this.showAllTags.update(v => !v);
  }

  toggleArtists(event: MouseEvent): void {
    event.stopPropagation();
    this.showAllArtists.update(v => !v);
  }

  getImageUrl(): string {
    return this.trackService.getStaticFileUrl(this.track.image_file);
  }

  tagBgColor(color: string): string {
    return this.trackService.darkenColor(color, 0.15);
  }

  tagBorderColor(color: string): string {
    return this.trackService.darkenColor(color, 0.35);
  }

  formatPrice(price: number): string {
    return price.toFixed(2).replace('.', ',') + ' €';
  }

  onDownloadPreviewClick(event: MouseEvent): void {
    event.stopPropagation();
    const url = this.track.stream_url.startsWith('http')
      ? this.track.stream_url
      : `${environment.apiUrl}${this.track.stream_url}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = `${this.track.title}_preview.mp3`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  onToplineClick(event: MouseEvent): void {
    event.stopPropagation();
    if (!this.authService.isLoggedIn()) {
      this.router.navigate(['/login']);
      return;
    }
    // track-detail a un effect() qui surveille recRequested() + track() :
    // dès que les deux sont vrais il pause le player et ouvre la modale.
    this.playerService.recRequested.update(n => n + 1);
    this.router.navigate(['/track', this.track.id]);
  }

  isThisTrackPlaying(): boolean {
    return this.playerService.currentTrack()?.id === this.track.id
        && this.playerService.isPlaying();
  }

  onPlay(): void {
    if (this.playerService.currentTrack()?.id === this.track.id) {
      this.playerService.togglePlay();
    } else {
      this.playerService.play(this.track);
    }
  }

}
