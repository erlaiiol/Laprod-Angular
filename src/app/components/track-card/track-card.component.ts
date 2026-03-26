// ─────────────────────────────────────────────────────────────────────────────
// COMPOSANT PRÉSENTATIONNEL TrackCard
// Rôle : afficher UN track. Ne sait pas d'où vient le track, ne fetch rien.
// Reçoit ses données de la page parente via @Input().
// Communique vers la page parente via @Output().
// ─────────────────────────────────────────────────────────────────────────────

import { Component, Input, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

import { Track, TrackService } from '../../services/track.service';
import { PlayerService } from '../../services/player.service';


@Component({
  selector: 'app-track-card',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './track-card.component.html',
  styleUrls:   ['./track-card.component.scss']
})
export class TrackCardComponent {

  @Input() track!: Track;

  private trackService  = inject(TrackService);
  private playerService = inject(PlayerService);

  getImageUrl(): string {
    return this.trackService.getStaticFileUrl(this.track.image_file);
  }

  tagBgColor(color: string): string {
    return this.trackService.darkenColor(color, 0.15);
  }

  tagBorderColor(color: string): string {
    return this.trackService.darkenColor(color, 0.35);
  }

  onPlay(): void {
    this.playerService.play(this.track);
  }

}
