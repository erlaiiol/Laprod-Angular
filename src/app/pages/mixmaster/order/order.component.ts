import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MixmasterService, MixEngineerPublic } from '../../../services/mixmaster.service';
import { AuthService } from '../../../services/auth.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';
import { MixmasterGuideComponent } from '../../../components/mixmaster-guide/mixmaster-guide.component';

@Component({
  selector: 'app-mixmaster-order',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, MixmasterGuideComponent],
  templateUrl: './order.component.html',
  styleUrls: ['./order.component.scss'],
})
export class MixmasterOrderComponent implements OnInit {

  loading     = signal(true);
  submitting  = signal(false);
  error       = signal<string | null>(null);
  engineer    = signal<MixEngineerPublic | null>(null);

  // ── Services ─────────────────────────────────────────────────────────────
  serviceCleaning  = signal(false);
  serviceEffects   = signal(false);
  serviceArtistic  = signal(false);
  serviceMastering = signal(false);
  hasSeparatedStems = signal(false);

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
  estimatedPrice = computed(() => {
    const eng = this.engineer();
    if (!eng) return 0;
    const ref = eng.mixmaster_reference_price;
    let price = 0;
    if (this.serviceCleaning())  price += ref * 0.35;
    if (this.serviceEffects())   price += ref * 0.45;
    if (this.serviceArtistic())  price += ref * 0.20;
    if (this.serviceMastering()) price += ref * (eng.is_certified_producer_arranger ? 0.60 : 0.20);
    if (this.hasSeparatedStems()) price += ref * 0.20;
    return Math.round(price * 100) / 100;
  });

  depositAmount = computed(() => Math.round(this.estimatedPrice() * 0.30 * 100) / 100);

  readonly auth   = inject(AuthService);
  private route   = inject(ActivatedRoute);
  private router  = inject(Router);
  private mixSvc  = inject(MixmasterService);
  private toast   = inject(ToastService);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }
    const id = Number(this.route.snapshot.paramMap.get('engineerId'));
    this.mixSvc.getEngineer(id).subscribe({
      next: (res) => {
        if (res.success) this.engineer.set(res.data!.engineer);
        else this.error.set(res.feedback?.message ?? 'Ingénieur introuvable.');
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de charger les informations de l\'ingénieur.');
        this.loading.set(false);
      },
    });
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
    fd.append('service_cleaning',    String(this.serviceCleaning()));
    fd.append('service_effects',     String(this.serviceEffects()));
    fd.append('service_artistic',    String(this.serviceArtistic()));
    fd.append('service_mastering',   String(this.serviceMastering()));
    fd.append('has_separated_stems', String(this.hasSeparatedStems()));
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
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-avatar.png';
  }
}
