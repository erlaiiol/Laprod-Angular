import { Component, OnInit, signal, computed, inject, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { TrackService, TrackDetail } from '../../services/track.service';

type Format = 'mp3' | 'wav' | 'stems';
type Duration = '3ans' | '5ans' | '10ans' | 'vie';
type Territory = 'france' | 'europe' | 'monde';

const DURATION_MULTIPLIERS: Record<Duration, number> = {
  '3ans': 1.0,
  '5ans': 1.3,
  '10ans': 1.6,
  'vie': 2.2
};

const TERRITORY_MULTIPLIERS: Record<Territory, number> = {
  'france': 1.0,
  'europe': 1.4,
  'monde':  2.0
};

const SACEM_COMPOSER_PCT: Record<Duration, number> = {
  '3ans':  70,
  '5ans':  65,
  '10ans': 60,
  'vie':   55
};

@Component({
  selector: 'app-contract-config',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './contract-config.component.html',
  styleUrls: ['./contract-config.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ContractConfigComponent implements OnInit {

  track   = signal<TrackDetail | null>(null);
  loading = signal(true);
  error   = signal<string | null>(null);
  format  = signal<Format>('mp3');

  // Rights
  rightMechanical    = signal(false);
  rightPerformance   = signal(false);
  rightArrangement   = signal(false);

  duration   = signal<Duration>('3ans');
  territory  = signal<Territory>('france');

  private route    = inject(ActivatedRoute);
  private trackSvc = inject(TrackService);
  private cdr      = inject(ChangeDetectorRef);

  // ── Computed values ───────────────────────────────────────────────────────

  basePrice = computed<number>(() => {
    const t = this.track();
    if (!t) return 0;
    const f = this.format();
    const raw = f === 'mp3' ? t.price_mp3 : f === 'wav' ? t.price_wav : t.price_stems;
    return (raw ?? 0) + 5;
  });

  totalPrice = computed<string>(() => {
    const base = this.basePrice();
    const rights = (this.rightMechanical() ? 0.15 : 0)
                 + (this.rightPerformance() ? 0.20 : 0)
                 + (this.rightArrangement() ? 0.10 : 0);
    return (base * (1 + rights)
          * DURATION_MULTIPLIERS[this.duration()]
          * TERRITORY_MULTIPLIERS[this.territory()]).toFixed(2);
  });

  composerPct = computed(() => SACEM_COMPOSER_PCT[this.duration()]);
  buyerPct    = computed(() => 100 - SACEM_COMPOSER_PCT[this.duration()]);

  formatLabel = computed(() => ({ mp3: 'MP3', wav: 'WAV', stems: 'STEMS' }[this.format()]));

  ngOnInit(): void {
    const trackId = Number(this.route.snapshot.paramMap.get('trackId'));
    const fmt     = this.route.snapshot.paramMap.get('format') as Format;
    if (fmt && ['mp3','wav','stems'].includes(fmt)) this.format.set(fmt);

    this.trackSvc.getTrackDetail(trackId).subscribe({
      next: (res) => {
        if (res.success) this.track.set(res.data.track);
        else this.error.set('Track introuvable.');
        this.loading.set(false);
        this.cdr.markForCheck();
      },
      error: () => {
        this.error.set('Impossible de contacter le serveur.');
        this.loading.set(false);
        this.cdr.markForCheck();
      }
    });
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(path);
  }

  onConfirm(): void {
    alert('Paiement Stripe — à venir.\n\nTotal : ' + this.totalPrice() + '€');
  }

}
