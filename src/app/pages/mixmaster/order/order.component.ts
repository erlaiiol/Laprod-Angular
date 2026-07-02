import { Component, OnInit, signal, computed, inject, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MixmasterService, MixEngineerPublic } from '../../../services/mixmaster.service';
import { AuthService } from '../../../services/auth.service';
import { ToastService } from '../../../services/toast.service';
import { MixmasterGuideComponent } from '../../../components/mixmaster-guide/mixmaster-guide.component';

type Mode = 'quick' | 'advanced';

@Component({
  selector: 'app-mixmaster-order',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, MixmasterGuideComponent],
  templateUrl: './order.component.html',
  styleUrls: ['./order.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MixmasterOrderComponent implements OnInit {

  loading     = signal(true);
  submitting  = signal(false);
  error       = signal<string | null>(null);
  engineer    = signal<MixEngineerPublic | null>(null);
  mode        = signal<Mode>('quick');

  // ── Services ─────────────────────────────────────────────────────────────
  serviceCleaning  = signal(false);
  serviceEffects   = signal(false);
  serviceArtistic  = signal(false);
  serviceMastering = signal(false);
  hasSeparatedStems = signal(false);

  /**
   * Services imposés par le palier minimum de l'ingénieur.
   * Paliers : 35%=cleaning, 55%=cleaning+mastering, 80%=cleaning+effects,
   *           100%=cleaning+effects+mastering, 160%=tout+artistique.
   */
  mandatoryServices = computed(() => {
    const eng = this.engineer();
    if (!eng?.mixmaster_reference_price || !eng.mixmaster_price_min) return new Set<string>();
    const pct = (eng.mixmaster_price_min / eng.mixmaster_reference_price) * 100;
    const m = new Set<string>();
    if (pct >= 35)  m.add('cleaning');
    if (pct >= 55 && pct < 80) { m.add('mastering'); }          // palier 55%
    if (pct >= 80)  m.add('effects');                            // palier 80% (remplace mastering seul)
    if (pct >= 100) m.add('mastering');                          // palier 100%
    if (pct >= 160 && eng.is_certified_producer_arranger) m.add('artistic');
    return m;
  });

  // ── Briefing ─────────────────────────────────────────────────────────────
  title         = signal('');
  artistMessage = signal('');
  briefVocals   = signal('');
  briefBackingVocals = signal('');
  briefAmbiance = signal('');
  briefBass     = signal('');
  briefEnergyStyle = signal('');
  briefReferences = signal('');
  briefInstruments = signal('');
  briefPercussion = signal('');
  briefEffects  = signal('');
  briefStructure = signal('');

  // ── Files ─────────────────────────────────────────────────────────────────
  stemsFile     = signal<File | null>(null);
  referenceFile = signal<File | null>(null);

  // ── Price (computed) ──────────────────────────────────────────────────────
  ref = computed(() => +(this.engineer()?.mixmaster_reference_price ?? 0));

  /** Prix brut des services cochés (sans plancher price_min). */
  rawServicesPrice = computed(() => {
    const eng = this.engineer();
    if (!eng) return 0;
    const r = eng.mixmaster_reference_price;
    if (r == null) return 0;
    let price = 0;
    if (this.serviceCleaning())   price += +r * 0.35;
    if (this.serviceEffects())    price += +r * 0.45;
    if (this.serviceMastering())  price += +r * 0.20;
    if (this.serviceArtistic())   price += +r * 0.60;
    if (this.hasSeparatedStems()) price += +r * 0.20;
    return Math.round(price * 100) / 100;
  });

  /**
   * Supplément appliqué pour atteindre le tarif minimum de l'ingénieur.
   * Positif quand les services cochés sont inférieurs à price_min.
   */
  priceMinSupplement = computed(() => {
    const priceMin = +(this.engineer()?.mixmaster_price_min ?? 0);
    const raw      = this.rawServicesPrice();
    return Math.max(0, Math.round((priceMin - raw) * 100) / 100);
  });

  /** Prix total réel = max(services, price_min). Cohérent avec le backend. */
  estimatedPrice = computed(() => {
    return this.rawServicesPrice() + this.priceMinSupplement();
  });

  depositAmount = computed(() => Math.round(this.estimatedPrice() * 0.30 * 100) / 100);

  readonly auth   = inject(AuthService);
  private route   = inject(ActivatedRoute);
  private router  = inject(Router);
  private mixSvc  = inject(MixmasterService);
  private toast   = inject(ToastService);
  private cdr     = inject(ChangeDetectorRef);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('engineerId'));
    this.mixSvc.getEngineer(id).subscribe({
      next: (res) => {
        if (res.success) {
          this.engineer.set(res.data!.engineer);
          // Pré-cocher les services obligatoires selon le palier minimum
          const m = this.mandatoryServices();
          if (m.has('cleaning'))  this.serviceCleaning.set(true);
          if (m.has('effects'))   this.serviceEffects.set(true);
          if (m.has('mastering')) this.serviceMastering.set(true);
          if (m.has('artistic'))  this.serviceArtistic.set(true);
        } else {
          this.error.set(res.feedback?.message ?? 'Ingénieur introuvable.');
        }
        this.loading.set(false);
        this.cdr.markForCheck();
      },
      error: () => {
        this.error.set('Impossible de charger les informations de l\'ingénieur.');
        this.loading.set(false);
        this.cdr.markForCheck();
      },
    });
  }

  setMode(m: Mode): void {
    this.mode.set(m);
    if (m === 'quick') {
      // Revenir aux seuls services obligatoires, supprimer les extras
      const mandatory = this.mandatoryServices();
      this.serviceCleaning.set(mandatory.has('cleaning'));
      this.serviceEffects.set(mandatory.has('effects'));
      this.serviceMastering.set(mandatory.has('mastering'));
      this.serviceArtistic.set(mandatory.has('artistic'));
      this.hasSeparatedStems.set(false);
    }
    this.cdr.markForCheck();
  }

  onStemsChange(ev: Event): void {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.stemsFile.set(f);
  }

  onReferenceChange(ev: Event): void {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.referenceFile.set(f);
  }

  submit(): void {
    if (!this.auth.isLoggedIn()) {
      this.router.navigate(['/login'], { queryParams: { returnUrl: this.router.url } });
      return;
    }
    if (this.submitting()) return;
    const stems = this.stemsFile();
    if (!stems) { this.toast.showToast({ level: 'warning', message: 'Veuillez uploader votre archive (ZIP/RAR).' }); return; }
    if (!this.title().trim()) { this.toast.showToast({ level: 'warning', message: 'Titre requis.' }); return; }
    if (this.estimatedPrice() <= 0) { this.toast.showToast({ level: 'warning', message: 'Sélectionnez au moins un service.' }); return; }

    const eng = this.engineer()!;
    const fd = new FormData();
    fd.append('stems_file', stems);
    if (this.referenceFile()) fd.append('reference_file', this.referenceFile()!);
    fd.append('title',               this.title().trim());
    fd.append('service_cleaning',    this.serviceCleaning()   ? '1' : '0');
    fd.append('service_effects',     this.serviceEffects()    ? '1' : '0');
    fd.append('service_artistic',    this.serviceArtistic()   ? '1' : '0');
    fd.append('service_mastering',   this.serviceMastering()  ? '1' : '0');
    fd.append('has_separated_stems', this.hasSeparatedStems() ? '1' : '0');
    fd.append('artist_message',      this.artistMessage());
    fd.append('brief_vocals',        this.briefVocals());
    fd.append('brief_backing_vocals', this.briefBackingVocals());
    fd.append('brief_ambiance',      this.briefAmbiance());
    fd.append('brief_bass',          this.briefBass());
    fd.append('brief_energy_style',  this.briefEnergyStyle());
    fd.append('brief_references',    this.briefReferences());
    fd.append('brief_instruments',   this.briefInstruments());
    fd.append('brief_percussion',    this.briefPercussion());
    fd.append('brief_effects_brief', this.briefEffects());
    fd.append('brief_structure',     this.briefStructure());
    fd.append('success_url', `${window.location.origin}/mix/payment-success`);
    fd.append('cancel_url',  `${window.location.origin}/mix/order/${eng.id}`);

    this.submitting.set(true);
    this.mixSvc.createOrder(eng.id, fd).subscribe({
      next: (res) => {
        if (res.success && res.data?.checkout_url) {
          window.location.href = res.data.checkout_url;
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur lors de la création de la commande.' });
          this.submitting.set(false);
        }
      },
      error: (err) => {
        this.toast.showToast({ level: 'error', message: err?.error?.feedback?.message ?? 'Erreur serveur.' });
        this.submitting.set(false);
      },
    });
  }

  imgUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/default_profile.png';
    if (path.startsWith('http')) return path;
    return `/db_assets/${path}`;
  }
}
