import { ChangeDetectionStrategy, Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import {
  PromoService, PromoCode, PromoContext, PromoScope, PromoServiceKey,
  PROMO_PERCENTS, SERVICE_LABELS,
} from '../../services/promo.service';
import { ToastService } from '../../services/toast.service';
import { AuthService } from '../../services/auth.service';
import { ImgFallbackDirective } from '../../directives/img-fallback.directive';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-promo-codes',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, ImgFallbackDirective],
  templateUrl: './promo-codes.component.html',
  styleUrls: ['./promo-codes.component.scss'],
})
export class PromoCodesComponent implements OnInit {

  private promoService = inject(PromoService);
  private toast        = inject(ToastService);
  private auth         = inject(AuthService);
  private router       = inject(Router);

  readonly percents      = PROMO_PERCENTS;
  readonly serviceLabels = SERVICE_LABELS;

  // ── State ──────────────────────────────────────────────────────────────────

  loading   = signal(true);
  saving    = signal(false);
  codes     = signal<PromoCode[]>([]);
  context   = signal<PromoContext | null>(null);
  canCreate = signal(false);

  showForm  = signal(false);
  editingId = signal<number | null>(null);

  // ── Formulaire ─────────────────────────────────────────────────────────────

  fCode          = signal('');
  fPercent       = signal<number>(10);
  fScope         = signal<PromoScope>('track');
  fAppliesToAll  = signal(false);
  fOncePerUser   = signal(false);
  fExpiresAt     = signal<string>('');
  fMaxRedemptions = signal<string>('');
  fTrackIds      = signal<number[]>([]);
  fServiceKeys   = signal<PromoServiceKey[]>([]);

  // ── Dérivés ────────────────────────────────────────────────────────────────

  /** L'utilisateur peut-il proposer des prestations mix/master ? */
  canSellServices = computed(() => (this.context()?.service_keys.length ?? 0) > 0);

  availableServices = computed(() => this.context()?.service_keys ?? []);
  availableTracks   = computed(() => this.context()?.tracks ?? []);

  trackCodes     = computed(() => this.codes().filter(c => c.scope === 'track'));
  mixmasterCodes = computed(() => this.codes().filter(c => c.scope === 'mixmaster'));

  /** Aperçu « ce que touche le vendeur » — la remise est financée sur SA part,
   *  la commission de 10 % suit le montant réellement encaissé. */
  simulation = computed(() => {
    const gross    = 100;
    const percent  = this.fPercent();
    const discount = Math.round(gross * percent) / 100;
    const net      = gross - discount;
    const fee      = Math.round(net * 10) / 100;
    return { gross, discount, net, fee, seller: net - fee };
  });

  codeError = computed(() => {
    const code = this.fCode().trim();
    if (!code) return null;
    if (code.length < 4 || code.length > 15) return 'Entre 4 et 15 caractères.';
    if (!/^[a-zA-Z0-9]+$/.test(code)) return 'Lettres et chiffres uniquement.';
    return null;
  });

  /** Date minimale sélectionnable : demain. Un code qui expire aujourd'hui à 00h00
   *  serait mort-né. */
  minExpiryDate = computed(() => {
    const d = new Date();
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  });

  expiryError = computed(() => {
    const raw = this.fExpiresAt();
    if (!raw) return "Une date d'expiration est obligatoire.";
    if (raw < this.minExpiryDate()) return "La date d'expiration doit être dans le futur.";
    return null;
  });

  formValid = computed(() => {
    if (this.codeError() || !this.fCode().trim()) return false;
    if (this.expiryError()) return false;
    if (this.fAppliesToAll()) return true;
    return this.fScope() === 'track'
      ? this.fTrackIds().length > 0
      : this.fServiceKeys().length > 0;
  });

  // ── Cycle de vie ───────────────────────────────────────────────────────────

  ngOnInit(): void {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.promoService.list().subscribe({
      next: res => {
        this.codes.set(res.data?.promo_codes ?? []);
        this.canCreate.set(res.data?.can_create ?? false);
        this.loading.set(false);
      },
      error: () => {
        this.toast.showToast({ level: 'error', message: 'Impossible de charger vos codes promo.' });
        this.loading.set(false);
      },
    });

    this.promoService.context().subscribe({
      next: res => this.context.set(res.data ?? null),
      error: () => {},
    });
  }

  // ── Formulaire ─────────────────────────────────────────────────────────────

  openCreate(): void {
    this.editingId.set(null);
    this.fCode.set('');
    this.fPercent.set(10);
    this.fScope.set('track');
    this.fAppliesToAll.set(false);
    this.fOncePerUser.set(false);
    this.fExpiresAt.set('');
    this.fMaxRedemptions.set('');
    this.fTrackIds.set([]);
    this.fServiceKeys.set([]);
    this.showForm.set(true);
  }

  openEdit(code: PromoCode): void {
    this.editingId.set(code.id);
    this.fCode.set(code.code);
    this.fPercent.set(code.percent);
    this.fScope.set(code.scope);
    this.fAppliesToAll.set(code.applies_to_all);
    this.fOncePerUser.set(code.once_per_user);
    this.fExpiresAt.set(code.expires_at ? code.expires_at.slice(0, 10) : '');
    this.fMaxRedemptions.set(code.max_redemptions != null ? String(code.max_redemptions) : '');
    this.fTrackIds.set([...code.track_ids]);
    this.fServiceKeys.set([...code.service_keys]);
    this.showForm.set(true);
  }

  closeForm(): void {
    this.showForm.set(false);
  }

  toggleTrack(id: number): void {
    this.fTrackIds.update(ids =>
      ids.includes(id) ? ids.filter(t => t !== id) : [...ids, id],
    );
  }

  toggleService(key: PromoServiceKey): void {
    this.fServiceKeys.update(keys =>
      keys.includes(key) ? keys.filter(k => k !== key) : [...keys, key],
    );
  }

  selectAllTracks(): void {
    this.fTrackIds.set(this.availableTracks().map(t => t.id));
  }

  selectAllServices(): void {
    this.fServiceKeys.set([...this.availableServices()]);
  }

  isTrackSelected(id: number): boolean       { return this.fTrackIds().includes(id); }
  isServiceSelected(k: PromoServiceKey): boolean { return this.fServiceKeys().includes(k); }

  setScope(scope: PromoScope): void {
    this.fScope.set(scope);
    // Le périmètre de l'autre portée n'a plus de sens : on le vide pour ne pas
    // envoyer des ids de beats sur un code mix/master (et inversement).
    this.fTrackIds.set([]);
    this.fServiceKeys.set([]);
  }

  submit(): void {
    if (!this.formValid() || this.saving()) return;
    this.saving.set(true);

    const max = this.fMaxRedemptions().trim();
    const payload = {
      code:            this.fCode().trim().toUpperCase(),
      percent:         this.fPercent(),
      scope:           this.fScope(),
      applies_to_all:  this.fAppliesToAll(),
      once_per_user:   this.fOncePerUser(),
      expires_at:      this.fExpiresAt() || null,
      max_redemptions: max ? Number(max) : null,
      ...(this.fAppliesToAll()
        ? {}
        : this.fScope() === 'track'
          ? { track_ids: this.fTrackIds() }
          : { service_keys: this.fServiceKeys() }),
    };

    const id  = this.editingId();
    const req = id ? this.promoService.update(id, payload) : this.promoService.create(payload);

    req.subscribe({
      next: res => {
        this.toast.showToast({ level: 'success', message: res.feedback?.message || 'Code promo enregistré.' });
        this.saving.set(false);
        this.showForm.set(false);
        this.reload();
      },
      error: err => {
        this.saving.set(false);
        this.toast.showToast({
          level: 'error',
          message: err?.error?.message || "Impossible d'enregistrer ce code promo.",
        });
      },
    });
  }

  toggleActive(code: PromoCode): void {
    this.promoService.setActive(code.id, !code.is_active).subscribe({
      next: res => {
        this.toast.showToast({ level: 'success', message: res.feedback?.message || 'Code promo mis à jour.' });
        this.reload();
      },
      error: err => this.toast.showToast({
        level: 'error',
        message: err?.error?.message || 'Impossible de mettre à jour ce code.',
      }),
    });
  }

  remove(code: PromoCode): void {
    const used = code.redemption_count > 0;
    const question = used
      ? `« ${code.code} » a déjà été utilisé ${code.redemption_count} fois. Il sera désactivé et conservé dans votre historique. Continuer ?`
      : `Supprimer définitivement le code « ${code.code} » ?`;
    if (!confirm(question)) return;

    this.promoService.remove(code.id).subscribe({
      next: res => {
        this.toast.showToast({ level: 'info', message: res.feedback?.message || 'Code promo supprimé.' });
        this.reload();
      },
      error: err => this.toast.showToast({
        level: 'error',
        message: err?.error?.message || 'Impossible de supprimer ce code.',
      }),
    });
  }

  goPremium(): void {
    this.router.navigate(['/premium']);
  }

  // ── Affichage ──────────────────────────────────────────────────────────────

  statusOf(code: PromoCode): { label: string; kind: string } {
    if (!code.is_active)   return { label: 'Désactivé', kind: 'off' };
    if (code.is_expired)   return { label: 'Expiré',    kind: 'off' };
    if (code.is_exhausted) return { label: 'Épuisé',    kind: 'off' };
    return { label: 'Actif', kind: 'on' };
  }

  scopeLabel(code: PromoCode): string {
    if (code.applies_to_all) {
      return code.scope === 'track' ? 'Tous mes beats' : 'Toutes mes prestations';
    }
    return code.scope === 'track'
      ? `${code.track_ids.length} beat${code.track_ids.length > 1 ? 's' : ''}`
      : code.service_keys.map(k => this.serviceLabels[k]).join(', ');
  }

  usageLabel(code: PromoCode): string {
    if (code.max_redemptions == null) {
      return `${code.redemption_count} utilisation${code.redemption_count > 1 ? 's' : ''}`;
    }
    return `${code.redemption_count} / ${code.max_redemptions}`;
  }
}
