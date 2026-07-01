import {
  Component, OnInit, signal, computed, effect,
  inject, ChangeDetectionStrategy, ChangeDetectorRef,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { TrackService, TrackDetail } from '../../services/track.service';
import { PaymentService } from '../../services/payment.service';
import { AuthService } from '../../services/auth.service';

type Format      = 'mp3' | 'wav' | 'stems';
type Territory   = 'France' | 'Europe' | 'Monde entier';
type DurationKey = 'stream' | '3' | '5' | '10' | 'lifetime';
type PresetKey   = 'starter' | 'standard' | 'integral';
type Mode        = 'quick' | 'advanced';

const MECHANICAL_THRESHOLD  = 199.99;
const PUBLIC_SHOW_THRESHOLD = 74.99;

interface LicensePreset {
  key:         PresetKey;
  name:        string;
  tagline:     string;
  icon:        string;
  duration:    DurationKey;
  isLifetime:  boolean;
  territory:   Territory;
  mechanical:  boolean;
  publicShow:  boolean;
  arrangement: boolean;
  popular?:    boolean;
}

@Component({
  selector: 'app-track-contract-config',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './track-contract-config.component.html',
  styleUrls: ['./track-contract-config.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TrackContractConfigComponent implements OnInit {

  track    = signal<TrackDetail | null>(null);
  loading  = signal(true);
  error    = signal<string | null>(null);
  paying   = signal(false);
  format   = signal<Format>('mp3');
  mode     = signal<Mode>('quick');

  duration         = signal<DurationKey>('stream');
  territory        = signal<Territory>('France');
  isLifetime       = signal(false);
  rightMechanical  = signal(false);
  rightPublicShow  = signal(false);
  rightArrangement = signal(false);
  buyerAddress     = signal('');

  private route      = inject(ActivatedRoute);
  private trackSvc   = inject(TrackService);
  private paymentSvc = inject(PaymentService);
  readonly auth      = inject(AuthService);
  private cdr        = inject(ChangeDetectorRef);

  prices = computed(() => {
    const cp = this.track()?.contract_prices;
    return {
      duration:    { stream: 0, '3': cp?.duration_3y ?? 5, '5': cp?.duration_5y ?? 10, '10': cp?.duration_10y ?? 15, lifetime: cp?.lifetime ?? 50 } as Record<DurationKey, number>,
      territory:   { France: 0, Europe: cp?.territory_eu ?? 5, 'Monde entier': cp?.territory_world ?? 10 } as Record<Territory, number>,
      mechanical:  cp?.mechanical  ?? 30,
      publicShow:  cp?.public_show ?? 40,
      arrangement: cp?.arrangement ?? 10,
    };
  });

  basePrice = computed<number>(() => {
    const t = this.track();
    if (!t) return 0;
    const f = this.format();
    return f === 'mp3' ? (t.price_mp3 ?? 0)
         : f === 'wav' ? (t.price_wav ?? 0)
         : (t.price_stems ?? 0);
  });

  durationFee  = computed(() => this.isLifetime() ? this.prices().duration.lifetime : this.prices().duration[this.duration()]);
  territoryFee = computed(() => this.prices().territory[this.territory()]);

  // "Streaming seul" sans durée → aucun autre droit (mécanique, publique, arrangement) accordé
  streamOnly = computed(() => !this.isLifetime() && this.duration() === 'stream');

  arrangementFee = computed(() =>
    !this.streamOnly() && this.rightArrangement() ? this.prices().arrangement : 0
  );

  subtotal = computed(() =>
    this.basePrice() + this.durationFee() + this.territoryFee() + this.arrangementFee()
  );

  mechanicalAutoIncluded = computed(() => this.subtotal() >= MECHANICAL_THRESHOLD);

  mechanicalFee = computed(() =>
    !this.streamOnly() && !this.mechanicalAutoIncluded() && this.rightMechanical()
      ? this.prices().mechanical : 0
  );

  // Seuil diffusion publique calculé sur le sous-total APRÈS la mécanique
  // (identique à la logique backend : intermediate_total mis à jour après mécanique)
  subtotalWithMechanical = computed(() => this.subtotal() + this.mechanicalFee());
  publicShowAutoIncluded = computed(() => this.subtotalWithMechanical() >= PUBLIC_SHOW_THRESHOLD);

  publicShowFee = computed(() =>
    !this.streamOnly() && !this.publicShowAutoIncluded() && this.rightPublicShow()
      ? this.prices().publicShow : 0
  );

  totalPrice = computed(() =>
    this.subtotalWithMechanical() + this.publicShowFee()
  );

  sacemComposer = computed(() => (this.track() as any)?.sacem_percentage_composer ?? 50);
  sacemBuyer    = computed(() => 100 - this.sacemComposer());

  formatLabel = computed(() => ({ mp3: 'MP3 320kbps', wav: 'WAV 24-bit', stems: 'STEMS' }[this.format()]));

  durationLabel = computed(() =>
    this.isLifetime() ? 'À vie + 70 ans'
    : ({ stream: 'Streaming seul · à vie', '3': '3 ans', '5': '5 ans', '10': '10 ans', lifetime: 'À vie' } as Record<DurationKey, string>)[this.duration()]
  );

  readonly presets: readonly LicensePreset[] = [
    {
      key: 'starter', name: 'Starter', tagline: 'Streaming & réseaux sociaux',
      icon: 'bi-music-note-beamed', duration: 'stream', isLifetime: false,
      territory: 'France', mechanical: false, publicShow: false, arrangement: false,
    },
    {
      key: 'standard', name: 'Standard', tagline: 'Sorties officielles + concerts',
      icon: 'bi-vinyl-fill', duration: '5', isLifetime: false,
      territory: 'Europe', mechanical: true, publicShow: true, arrangement: false, popular: true,
    },
    {
      key: 'integral', name: 'Liberté totale', tagline: 'Tous droits · monde entier · à vie',
      icon: 'bi-globe2', duration: 'stream', isLifetime: true,
      territory: 'Monde entier', mechanical: true, publicShow: true, arrangement: true,
    },
  ];

  activePreset = computed<PresetKey | null>(() => {
    const mechEffective = this.mechanicalAutoIncluded() || this.rightMechanical();
    const showEffective = this.publicShowAutoIncluded() || this.rightPublicShow();
    for (const p of this.presets) {
      if (
        this.isLifetime()       === p.isLifetime &&
        (p.isLifetime || this.duration() === p.duration) &&
        this.territory()        === p.territory &&
        mechEffective           === p.mechanical &&
        showEffective           === p.publicShow &&
        this.rightArrangement() === p.arrangement
      ) return p.key;
    }
    return null;
  });

  constructor() {
    effect(() => { if (this.mechanicalAutoIncluded()) this.rightMechanical.set(false); });
    effect(() => { if (this.publicShowAutoIncluded())  this.rightPublicShow.set(false); });
    // Streaming seul : aucun droit d'exploitation accordé → réinitialiser les cases
    effect(() => {
      if (this.streamOnly()) {
        this.rightMechanical.set(false);
        this.rightPublicShow.set(false);
        this.rightArrangement.set(false);
      }
    });
  }

  ngOnInit(): void {
    const trackId = Number(this.route.snapshot.paramMap.get('trackId'));
    const fmt     = this.route.snapshot.paramMap.get('format') as Format;
    if (fmt && ['mp3', 'wav', 'stems'].includes(fmt)) this.format.set(fmt);

    // Quick mode default: apply cheapest (starter) preset upfront
    this.applyPreset(this.presets[0]);

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

  setMode(m: Mode): void {
    this.mode.set(m);
    if (m === 'quick') {
      this.applyPreset(this.presets[0]); // reset to starter
    }
    this.cdr.markForCheck();
  }

  applyPreset(p: LicensePreset): void {
    this.duration.set(p.duration);
    this.isLifetime.set(p.isLifetime);
    this.territory.set(p.territory);
    this.rightMechanical.set(p.mechanical);
    this.rightPublicShow.set(p.publicShow);
    this.rightArrangement.set(p.arrangement);
    this.cdr.markForCheck();
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholders/placeholder-track.png';
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
      duration_years:          this.isLifetime() ? 999 : this.duration() === 'stream' ? 0 : Number(this.duration()),
      territory:               this.territory(),
      mechanical_reproduction: !this.streamOnly() && (this.mechanicalAutoIncluded() || this.rightMechanical()),
      public_show:             !this.streamOnly() && (this.publicShowAutoIncluded() || this.rightPublicShow()),
      arrangement:             !this.streamOnly() && this.rightArrangement(),
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
