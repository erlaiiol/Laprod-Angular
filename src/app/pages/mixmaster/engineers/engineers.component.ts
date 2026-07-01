import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MixmasterService, MixEngineerPublic } from '../../../services/mixmaster.service';
import { AuthService } from '../../../services/auth.service';
import { PlayerService } from '../../../services/player.service';
import { Track } from '../../../services/track.service';
import { MixmasterGuideComponent } from '../../../components/mixmaster-guide/mixmaster-guide.component';
import { PaginationComponent } from '../../../components/pagination/pagination.component';
import { ShareButtonComponent } from '../../../components/share-button/share-button.component';

const PER_PAGE = 9;

@Component({
  selector: 'app-mixmaster-engineers',
  standalone: true,
  imports: [CommonModule, RouterModule, MixmasterGuideComponent, PaginationComponent, ShareButtonComponent],
  templateUrl: './engineers.component.html',
  styleUrls: ['./engineers.component.scss'],
})
export class MixmasterEngineersComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  engineers = signal<MixEngineerPublic[]>([]);

  page       = signal(1);
  totalPages = computed(() =>
    Math.max(1, Math.ceil(this.engineers().length / PER_PAGE))
  );
  pagedEngineers = computed(() => {
    const start = (this.page() - 1) * PER_PAGE;
    return this.engineers().slice(start, start + PER_PAGE);
  });

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

  goToPage(p: number): void {
    this.page.set(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  imgUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/default_profile.png';
    if (path.startsWith('http')) return path;
    return `/db_assets/${path}`;
  }

  playSample(relativeUrl: string, label: 'Brut' | 'Traité', eng: MixEngineerPublic): void {
    const current = this.player.currentTrack();
    if (current?.stream_url === relativeUrl) {
      this.player.togglePlay();
      return;
    }
    const track: Track = {
      id:            0,
      title:         label === 'Brut' ? 'Version brute' : 'Version traitée',
      stream_url:      relativeUrl,
      full_stream_url: null,
      image_file:      '',
      composer_user:   { username: eng.username },
      bpm:             0,
      key:             '',
      style:           '',
      price_mp3:       0,
      tags:            [],
      is_approved:         true,
      playlist_count:      0,
      first_playlist_image: null,
    };
    this.player.play(track);
  }

  isPlayingSample(relativeUrl: string): boolean {
    return this.player.currentTrack()?.stream_url === relativeUrl && this.player.isPlaying();
  }

  priceRange(e: MixEngineerPublic): string {
    const min = e.mixmaster_price_min;
    const max = e.price_max;
    if (min == null || !max) return 'Prix sur demande';
    return `${(+min).toFixed(2)}€ — ${(+max).toFixed(2)}€`;
  }
}
