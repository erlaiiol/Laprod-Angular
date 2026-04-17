import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MixmasterService, MixEngineerPublic } from '../../../services/mixmaster.service';
import { AuthService } from '../../../services/auth.service';
import { PlayerService } from '../../../services/player.service';
import { Track } from '../../../services/track.service';
import { environment } from '../../../../environments/environment';
import { MixmasterGuideComponent } from '../../../components/mixmaster-guide/mixmaster-guide.component';

@Component({
  selector: 'app-mixmaster-engineers',
  standalone: true,
  imports: [CommonModule, RouterModule, MixmasterGuideComponent],
  templateUrl: './engineers.component.html',
  styleUrls: ['./engineers.component.scss'],
})
export class MixmasterEngineersComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  engineers = signal<MixEngineerPublic[]>([]);

  readonly auth   = inject(AuthService);
  readonly player = inject(PlayerService);
  private mixSvc  = inject(MixmasterService);

  ngOnInit(): void {
    this.mixSvc.getEngineers().subscribe({
      next: (res) => {
        if (res.success) this.engineers.set(res.data!.engineers);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de charger la liste des ingénieurs.');
        this.loading.set(false);
      },
    });
  }

  imgUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/default_profile.png';
    if (path.startsWith('http')) return path;
    return `/db_assets/${path}`;
  }

  /** Joue ou met en pause un sample engineer dans le player bas. */
  playSample(relativeUrl: string, label: 'Brut' | 'Traité', eng: MixEngineerPublic): void {
    const current = this.player.currentTrack();
    if (current?.stream_url === relativeUrl) {
      this.player.togglePlay();
      return;
    }
    const track: Track = {
      id:            0,
      title:         label === 'Brut' ? 'Version brute' : 'Version traitée',
      stream_url:    relativeUrl,
      image_file:    '',          // placeholder affiché dans le player
      composer_user: { username: eng.username },
      bpm:           0,
      key:           '',
      style:         '',
      price_mp3:     0,
      tags:          [],
      is_approved:   true,
    };
    this.player.play(track);
  }

  isPlayingSample(relativeUrl: string): boolean {
    return this.player.currentTrack()?.stream_url === relativeUrl && this.player.isPlaying();
  }

  priceRange(e: MixEngineerPublic): string {
    const ref = e.mixmaster_reference_price;
    const max = Math.round(
      (ref * 0.35 + ref * 0.45 + ref * 0.20 + ref * 0.20
       + (e.is_certified_producer_arranger ? ref * 0.60 : 0)) * 100
    ) / 100;
    return `${e.mixmaster_price_min.toFixed(2)}€ — ${max.toFixed(2)}€`;
  }
}
