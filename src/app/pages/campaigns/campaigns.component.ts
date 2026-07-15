import { ChangeDetectionStrategy, Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import {
  CampaignService, Campaign, CampaignContext, CampaignSegment, CampaignTemplate,
  SEGMENT_LABELS, SEGMENT_HINTS,
} from '../../services/campaign.service';
import { ToastService } from '../../services/toast.service';

const SUBJECT_MAX = 120;
const BODY_MAX    = 2000;

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-campaigns',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './campaigns.component.html',
  styleUrls: ['./campaigns.component.scss'],
})
export class CampaignsComponent implements OnInit {

  private campaignSvc = inject(CampaignService);
  private toast       = inject(ToastService);
  private route       = inject(ActivatedRoute);
  private router      = inject(Router);

  readonly segmentLabels = SEGMENT_LABELS;
  readonly segmentHints  = SEGMENT_HINTS;
  readonly subjectMax    = SUBJECT_MAX;
  readonly bodyMax       = BODY_MAX;
  readonly segments: CampaignSegment[] = ['buyers', 'favorites', 'listeners', 'affinity', 'all'];

  // ── State ──────────────────────────────────────────────────────────────────

  loading   = signal(true);
  saving    = signal(false);
  campaigns = signal<Campaign[]>([]);
  context   = signal<CampaignContext | null>(null);
  canCreate = signal(false);

  showForm  = signal(false);
  editingId = signal<number | null>(null);

  // Formulaire
  fSubject = signal('');
  fBody    = signal('');
  fSegment = signal<CampaignSegment>('buyers');
  fPromoId = signal<number | null>(null);
  fSlot    = signal<string>('');

  // ── Dérivés ────────────────────────────────────────────────────────────────

  quota      = computed(() => this.context()?.quota ?? null);
  slots      = computed(() => this.context()?.slots ?? []);
  promoCodes = computed(() => this.context()?.promo_codes ?? []);
  templates  = computed(() => this.context()?.templates ?? []);

  /** Applique un mail-type : pré-remplit le formulaire, que le vendeur complète.
   *  On ne remplace un champ QUE s'il est vide OU si le formulaire est neuf —
   *  cliquer un second modèle ne doit pas écraser un texte déjà retouché sans
   *  prévenir. */
  applyTemplate(t: CampaignTemplate): void {
    const untouched = !this.fSubject().trim() && !this.fBody().trim();
    if (untouched || confirm('Remplacer le contenu actuel par ce modèle ?')) {
      this.fSubject.set(t.subject);
      this.fBody.set(t.body);
      this.fSegment.set(t.segment);
      this.fPromoId.set(t.promo_code_id);
    }
  }

  audienceOf(segment: CampaignSegment): number {
    return this.context()?.audiences?.[segment] ?? 0;
  }

  /** Audience du segment choisi — ce qui sera réellement touché. */
  selectedAudience = computed(() => this.audienceOf(this.fSegment()));

  isSuperPremium = computed(() => this.fSegment() === 'all');
  superPrice     = computed(() => this.context()?.super_premium_price ?? 0);

  subjectError = computed(() => {
    const s = this.fSubject().trim();
    if (!s) return null;
    return s.length < 3 ? 'Sujet trop court.' : null;
  });

  bodyError = computed(() => {
    const b = this.fBody().trim();
    if (!b) return null;
    return b.length < 10 ? 'Message trop court.' : null;
  });

  formValid = computed(() =>
    this.fSubject().trim().length >= 3 &&
    this.fBody().trim().length >= 10 &&
    !this.subjectError() && !this.bodyError(),
  );

  /** Peut-on encore engager une campagne ? */
  quotaExhausted = computed(() => (this.quota()?.remaining ?? 0) <= 0);

  // ── Cycle de vie ───────────────────────────────────────────────────────────

  ngOnInit(): void {
    // Retour de Stripe après paiement Super Premium.
    const sessionId = this.route.snapshot.queryParamMap.get('session_id');
    if (sessionId) {
      this.campaignSvc.verifyPayment(sessionId).subscribe({
        next: res => {
          this.toast.showToast({
            level: 'success',
            message: res.feedback?.message ?? 'Paiement confirmé.',
          });
          this.router.navigate(['/campagnes'], { replaceUrl: true });
          this.reload();
        },
        error: err => this.toast.showToast({
          level: 'error',
          message: err?.error?.feedback?.message ?? 'Paiement non confirmé.',
        }),
      });
    }
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.campaignSvc.list().subscribe({
      next: res => {
        this.campaigns.set(res.data?.campaigns ?? []);
        this.canCreate.set(res.data?.can_create ?? false);
        this.loading.set(false);
      },
      error: () => {
        this.toast.showToast({ level: 'error', message: 'Impossible de charger vos campagnes.' });
        this.loading.set(false);
      },
    });

    this.campaignSvc.context().subscribe({
      next:  res => this.context.set(res.data ?? null),
      error: () => this.context.set(null),
    });
  }

  // ── Formulaire ─────────────────────────────────────────────────────────────

  openCreate(): void {
    this.editingId.set(null);
    this.fSubject.set('');
    this.fBody.set('');
    this.fSegment.set('buyers');
    this.fPromoId.set(null);
    this.fSlot.set('');
    this.showForm.set(true);
  }

  openEdit(c: Campaign): void {
    this.editingId.set(c.id);
    this.fSubject.set(c.subject);
    this.fBody.set(c.body);
    this.fSegment.set(c.segment);
    this.fPromoId.set(c.promo_code_id);
    this.fSlot.set(c.scheduled_for ?? '');
    this.showForm.set(true);
  }

  closeForm(): void { this.showForm.set(false); }

  /** Enregistre le brouillon. La planification est une étape SÉPARÉE et explicite :
   *  on n'envoie jamais un mailing par accident en cliquant « enregistrer ». */
  saveDraft(): void {
    if (!this.formValid() || this.saving()) return;
    this.saving.set(true);

    const payload = {
      subject:       this.fSubject().trim(),
      body:          this.fBody().trim(),
      segment:       this.fSegment(),
      promo_code_id: this.fPromoId(),
    };

    const id  = this.editingId();
    const req = id ? this.campaignSvc.update(id, payload) : this.campaignSvc.create(payload);

    req.subscribe({
      next: res => {
        this.saving.set(false);
        this.editingId.set(res.data?.campaign.id ?? null);
        this.toast.showToast({
          level: 'success',
          message: res.feedback?.message ?? 'Brouillon enregistré.',
        });
        this.reload();
      },
      error: err => {
        this.saving.set(false);
        this.toast.showToast({
          level: 'error',
          message: err?.error?.feedback?.message ?? 'Impossible d\'enregistrer.',
        });
      },
    });
  }

  schedule(c: Campaign): void {
    const slot = this.fSlot();
    if (!slot) {
      this.toast.showToast({ level: 'warning', message: 'Choisissez un créneau d\'envoi.' });
      return;
    }
    this.campaignSvc.schedule(c.id, slot).subscribe({
      next: res => {
        this.toast.showToast({
          level: 'success',
          message: res.feedback?.message ?? 'Campagne planifiée.',
        });
        this.showForm.set(false);
        this.reload();
      },
      error: err => this.toast.showToast({
        level: 'error',
        message: err?.error?.feedback?.message ?? 'Planification impossible.',
      }),
    });
  }

  payAndUnlock(c: Campaign): void {
    this.campaignSvc.checkoutSuperPremium(c.id).subscribe({
      next: res => {
        if (res.data?.checkout_url) window.location.href = res.data.checkout_url;
      },
      error: err => this.toast.showToast({
        level: 'error',
        message: err?.error?.feedback?.message ?? 'Paiement impossible.',
      }),
    });
  }

  cancel(c: Campaign): void {
    if (!confirm(`Annuler l'envoi de « ${c.subject} » ? Elle repassera en brouillon.`)) return;
    this.campaignSvc.cancel(c.id).subscribe({
      next: () => { this.toast.showToast({ level: 'info', message: 'Campagne annulée.' }); this.reload(); },
      error: err => this.toast.showToast({
        level: 'error',
        message: err?.error?.feedback?.message ?? 'Annulation impossible.',
      }),
    });
  }

  remove(c: Campaign): void {
    if (!confirm(`Supprimer définitivement « ${c.subject} » ?`)) return;
    this.campaignSvc.remove(c.id).subscribe({
      next: () => { this.toast.showToast({ level: 'info', message: 'Campagne supprimée.' }); this.reload(); },
      error: err => this.toast.showToast({
        level: 'error',
        message: err?.error?.feedback?.message ?? 'Suppression impossible.',
      }),
    });
  }

  // ── Affichage ──────────────────────────────────────────────────────────────

  statusLabel(c: Campaign): { label: string; kind: string } {
    switch (c.status) {
      case 'draft':     return { label: 'Brouillon',  kind: 'draft' };
      case 'scheduled': return { label: 'Planifiée',  kind: 'scheduled' };
      case 'sending':   return { label: 'Envoi…',     kind: 'scheduled' };
      case 'sent':      return { label: 'Envoyée',    kind: 'sent' };
      case 'failed':    return { label: 'Échouée',    kind: 'failed' };
      default:          return { label: 'Annulée',    kind: 'draft' };
    }
  }

  /** Taux de conversion réel : destinataires ayant utilisé le code promo. */
  conversionRate(c: Campaign): number {
    if (!c.stats?.sent_count) return 0;
    return Math.round((c.stats.conversions / c.stats.sent_count) * 1000) / 10;
  }
}
