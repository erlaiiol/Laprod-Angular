import {
  Component, OnInit, signal, computed,
  inject, ChangeDetectionStrategy, ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { TrackService, TrackDetail } from '../../services/track.service';
import { PaymentService } from '../../services/payment.service';
import { AuthService } from '../../services/auth.service';

type Format    = 'mp3' | 'wav' | 'stems';
type Territory = 'France' | 'Europe' | 'Monde entier';
type DurationKey = '3' | '5' | '10' | 'lifetime';

const DURATION_FEES: Record<DurationKey, number> = {
  '3': 5, '5': 10, '10': 15, 'lifetime': 50,
};

const TERRITORY_FEES: Record<Territory, number> = {
  'France': 0, 'Europe': 5, 'Monde entier': 10,
};

const MECHANICAL_PRICE   = 30;
const PUBLIC_SHOW_PRICE  = 40;
const ARRANGEMENT_PRICE  = 10;
const MECHANICAL_THRESHOLD  = 199.99;
const PUBLIC_SHOW_THRESHOLD = 74.99;

@Component({
  selector: 'app-contract-config',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './contract-config.component.html',
  styleUrls: ['./contract-config.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ContractConfigComponent implements OnInit {

  track    = signal<TrackDetail | null>(null);
  loading  = signal(true);
  error    = signal<string | null>(null);
  paying   = signal(false);
  format   = signal<Format>('mp3');

  duration   = signal<DurationKey>('3');
  territory  = signal<Territory>('Monde entier');
  isLifetime = signal(false);

  rightMechanical  = signal(false);
  rightPublicShow  = signal(false);
  rightArrangement = signal(false);

  buyerAddress = signal('');

  private route      = inject(ActivatedRoute);
  private trackSvc   = inject(TrackService);
  private paymentSvc = inject(PaymentService);
  readonly auth      = inject(AuthService);
  private cdr        = inject(ChangeDetectorRef);

  basePrice = computed<number>(() => {
    const t = this.track();
    if (!t) return 0;
    const f = this.format();
    return f === 'mp3' ? (t.price_mp3 ?? 0)
         : f === 'wav' ? (t.price_wav ?? 0)
         : (t.price_stems ?? 0);
  });

  durationFee  = computed(() => this.isLifetime() ? DURATION_FEES.lifetime : DURATION_FEES[this.duration()]);
  territoryFee = computed(() => TERRITORY_FEES[this.territory()]);
  arrangementFee = computed(() => this.rightArrangement() ? ARRANGEMENT_PRICE : 0);

  subtotal = computed(() =>
    this.basePrice() + this.durationFee() + this.territoryFee() + this.arrangementFee()
  );

  mechanicalAutoIncluded = computed(() => this.subtotal() >= MECHANICAL_THRESHOLD);
  publicShowAutoIncluded = computed(() => this.subtotal() >= PUBLIC_SHOW_THRESHOLD);

  mechanicalFee = computed(() =>
    this.mechanicalAutoIncluded() ? 0 : this.rightMechanical() ? MECHANICAL_PRICE : 0
  );
  publicShowFee = computed(() =>
    this.publicShowAutoIncluded() ? 0 : this.rightPublicShow() ? PUBLIC_SHOW_PRICE : 0
  );

  totalPrice = computed(() =>
    this.subtotal() + this.mechanicalFee() + this.publicShowFee()
  );

  composerEarnings = computed(() => Math.round(this.totalPrice() * 0.9 * 100) / 100);
  sacemComposer    = computed(() => (this.track() as any)?.sacem_percentage_composer ?? 50);
  sacemBuyer       = computed(() => 100 - this.sacemComposer());

  formatLabel = computed(() => ({ mp3: 'MP3 320kbps', wav: 'WAV 24-bit', stems: 'STEMS' }[this.format()]));

  durationLabel = computed(() =>
    this.isLifetime() ? 'À vie + 70 ans'
    : ({ '3': '3 ans', '5': '5 ans', '10': '10 ans', 'lifetime': 'À vie' } as Record<DurationKey, string>)[this.duration()]
  );

  readonly DURATION_FEES     = DURATION_FEES;
  readonly TERRITORY_FEES    = TERRITORY_FEES;
  readonly MECHANICAL_PRICE  = MECHANICAL_PRICE;
  readonly PUBLIC_SHOW_PRICE = PUBLIC_SHOW_PRICE;
  readonly ARRANGEMENT_PRICE = ARRANGEMENT_PRICE;

  ngOnInit(): void {
    const trackId = Number(this.route.snapshot.paramMap.get('trackId'));
    const fmt     = this.route.snapshot.paramMap.get('format') as Format;
    if (fmt && ['mp3', 'wav', 'stems'].includes(fmt)) this.format.set(fmt);

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
      },
    });
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(path);
  }

  toggleLifetime(): void {
    this.isLifetime.update(v => !v);
    this.cdr.markForCheck();
  }

  setDuration(val: DurationKey): void {
    this.duration.set(val);
    this.isLifetime.set(false);
    this.cdr.markForCheck();
  }

  onConfirm(): void {
    if (this.paying()) return;
    this.paying.set(true);
    this.error.set(null);
    this.cdr.markForCheck();

    const track = this.track();
    if (!track) { this.paying.set(false); return; }

    this.paymentSvc.createCheckout(track.id, this.format(), {
      is_lifetime:             this.isLifetime(),
      duration_years:          this.isLifetime() ? 999 : Number(this.duration()),
      territory:               this.territory(),
      mechanical_reproduction: this.mechanicalAutoIncluded() || this.rightMechanical(),
      public_show:             this.publicShowAutoIncluded() || this.rightPublicShow(),
      arrangement:             this.rightArrangement(),
      total_price:             Math.round(this.totalPrice() * 100) / 100,
      buyer_address:           this.buyerAddress(),
      buyer_email:             this.auth.currentUser()?.email,
    }).subscribe({
      next: (res) => {
        if (res.success && res.data?.checkout_url) {
          this.paymentSvc.redirectToCheckout(res.data.checkout_url);
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur de paiement.');
          this.paying.set(false);
          this.cdr.markForCheck();
        }
      },
      error: (err) => {
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur.');
        this.paying.set(false);
        this.cdr.markForCheck();
      },
    });
  }
}
