import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, signal, computed, effect, inject, untracked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { AuthService, PlanKey, PLAN_ORDER } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';
import { IosPurchasePolicyService } from '../../services/ios-purchase-policy.service';
import {
  IosPurchaseService, IosPlanOffer, AppleVerifyData,
  IosPurchaseCancelledError, IosPurchasePendingError,
} from '../../services/ios-purchase.service';
import { environment } from '../../../environments/environment';

/** Un palier tel que le serveur le décrit (GET /api/premium/plans). */
export interface PlanOffer {
  key:            PlanKey;
  label:          string;
  price:          number;
  tagline:        string;
  /** À qui ce palier s'adresse — la première question que se pose un visiteur. */
  audience:       string;
  /** L'argument qui, à lui seul, justifie le prix. */
  highlight:      string;
  /** Registre du palier : 'tu' pour les indépendants, 'vous' pour les structures. */
  tone:           'tu' | 'vous';
  features:       string[];
  uploads_per_day: number;
  topline_cap:    number;
  contract_quota: number | null;   // null = illimité
}

/** Une cellule du tableau comparatif : coche, croix, ou valeur textuelle. */
export interface ComparisonCell {
  kind: 'yes' | 'no' | 'text';
  text?: string;
}
export interface ComparisonRow {
  label: string;
  help?: string | null;
  cells: ComparisonCell[];
}
export interface ComparisonGroup {
  title: string;
  rows: ComparisonRow[];
}
export interface ComparisonColumn {
  key: PlanKey;
  label: string;
  price: number;
  tone: 'tu' | 'vous';
}
export interface ComparisonMatrix {
  columns: ComparisonColumn[];
  groups: ComparisonGroup[];
}

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-premium',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './premium.component.html',
  styleUrl: './premium.component.scss',
})
export class PremiumComponent implements OnInit {

  private http  = inject(HttpClient);
  readonly auth = inject(AuthService);
  private toast = inject(ToastService);
  private route = inject(ActivatedRoute);
  private destroyRef  = inject(DestroyRef);
  private iosPurchase = inject(IosPurchaseService);
  readonly policy     = inject(IosPurchasePolicyService);

  /** Par quel moyen l'abonnement se paie ICI : Stripe (web, Android), achat
   *  intégré Apple (app iOS), ou pas du tout. Dans l'app iOS, aucun chemin ne
   *  doit mener à Stripe pour un abonnement (App Review 3.1.1). */
  readonly purchaseMode = this.policy.subscription;

  /** Offres App Store (prix dans la devise du compte Apple). Vide hors iOS. */
  iosOffers       = signal<IosPlanOffer[]>([]);
  iosOffersLoaded = signal(false);
  restoring       = signal(false);

  readonly user      = this.auth.currentUser;
  readonly isPremium = this.auth.isPremium;
  readonly plan      = this.auth.plan;

  /** La grille vient du SERVEUR : les prix affichés sont, par construction, ceux
   *  qui seront facturés. Une grille recopiée dans le front finirait par annoncer
   *  un montant différent de celui encaissé. */
  plans = signal<PlanOffer[]>([]);

  /** Matrice comparative — le tableau à coches, dérivé côté serveur des capacités
   *  réelles pour ne jamais afficher un droit que l'API n'accorderait pas. */
  comparison = signal<ComparisonMatrix | null>(null);

  subscribing = signal<PlanKey | null>(null);
  activating  = signal(false);
  activated   = signal(false);

  /** Paliers payants (on n'affiche pas de bouton « souscrire » au plan gratuit). */
  paidPlans = computed(() => this.plans().filter(p => p.key !== 'free'));

  /** Argument massue par palier — affiché en bandeau sous le tableau, pour que le
   *  tableau reste lisible sans perdre le discours de vente. */
  highlights = computed(() => this.plans().filter(p => p.key !== 'free'));

  constructor() {
    // La politique iOS arrive du serveur après le premier rendu : on attend
    // qu'elle dise 'iap' pour charger les produits App Store, une seule fois.
    effect(() => {
      if (this.purchaseMode() !== 'iap') return;
      untracked(() => this.initIosPurchases());
    });
  }

  ngOnInit(): void {
    this.http.get<any>(`${environment.apiUrl}/api/premium/plans`).subscribe({
      next: res => {
        this.plans.set(res?.data?.plans ?? []);
        this.comparison.set(res?.data?.comparison ?? null);
      },
      error: () => this.toast.showToast({
        level: 'error', message: 'Impossible de charger les abonnements.',
      }),
    });

    const sessionId = this.route.snapshot.queryParamMap.get('session_id');
    const payment   = this.route.snapshot.queryParamMap.get('payment');

    if (payment === 'success' && sessionId) {
      this.activating.set(true);
      this.http.post<any>(`${environment.apiUrl}/api/premium/activate`, { session_id: sessionId })
        .subscribe({
          next: (res) => {
            if (res.success) {
              this.activated.set(true);
              this.auth.me().subscribe();
              this.toast.showToast({ level: 'success', message: 'Abonnement activé avec succès !' });
            } else {
              this.toast.showToast({ level: 'error', message: res.feedback?.message ?? "Erreur lors de l'activation." });
            }
          },
          error: (err) => {
            this.toast.showToast({ level: 'error', message: err.error?.feedback?.message ?? "Erreur lors de l'activation." });
          },
          complete: () => this.activating.set(false),
        });
    }
  }

  /** Le palier de l'utilisateur, comparé à celui de la carte. */
  isCurrentPlan(key: PlanKey): boolean {
    return this.isPremium() && this.plan() === key;
  }

  /** Une carte en dessous du palier actuel : on ne propose pas de « descendre »
   *  par un bouton d'achat, ce serait vendre une régression. */
  isBelowCurrentPlan(key: PlanKey): boolean {
    return this.isPremium() && PLAN_ORDER.indexOf(key) < PLAN_ORDER.indexOf(this.plan());
  }

  /** Libellé du bouton, dans le registre de LA CARTE (pas celui de la page) :
   *  une carte qui vouvoie et un bouton qui tutoie donneraient l'impression de
   *  deux textes écrits par deux personnes différentes. */
  ctaLabel(p: { key: PlanKey; tone: 'tu' | 'vous' }): string {
    const vous = p.tone === 'vous';

    if (this.isCurrentPlan(p.key)) {
      return vous ? 'Votre abonnement' : 'Ton abonnement';
    }
    if (this.isBelowCurrentPlan(p.key)) {
      return vous ? 'Inclus dans votre abonnement' : 'Inclus dans ton abonnement';
    }
    if (this.isPremium()) {
      return 'Passer à ce palier';
    }
    return vous ? 'Choisir ce palier' : 'Prendre ce palier';
  }

  /** Le palier mis en avant : le Semi-Pro, pas le plus cher. */
  isRecommended(key: PlanKey): boolean {
    return key === 'semi_pro';
  }

  /** Le CTA d'une colonne est-il désactivé (palier actuel ou inférieur, ou gratuit) ? */
  isColumnLocked(key: PlanKey): boolean {
    return key === 'free' || this.isCurrentPlan(key) || this.isBelowCurrentPlan(key);
  }

  lockedLabel(key: PlanKey): string {
    if (key === 'free') return this.isPremium() ? 'Inclus' : 'Palier gratuit';
    return this.ctaLabel({ key, tone: 'tu' });
  }

  scrollToPlans(event: Event): void {
    event.preventDefault();
    document.getElementById('plans')?.scrollIntoView({ behavior: 'smooth' });
  }

  // ── Achat intégré Apple (app iOS uniquement) ───────────────────────────────

  private iosInitialized = false;

  private initIosPurchases(): void {
    if (this.iosInitialized) return;
    this.iosInitialized = true;

    this.iosPurchase.loadOffers()
      .then(offers => this.iosOffers.set(offers))
      .catch(() => this.iosOffers.set([]))
      .finally(() => this.iosOffersLoaded.set(true));

    // Rattrapage silencieux d'un achat payé mais jamais crédité (réseau coupé
    // juste après le paiement) : sans effet si tout est déjà à jour.
    this.iosPurchase.reconcile()
      .then(data => this.onIosVerified(data))
      .catch(() => { /* le bouton « Restaurer mes achats » reste disponible */ });

    this.iosPurchase.onTransactionUpdated(data => this.onIosVerified(data))
      .then(handle => this.destroyRef.onDestroy(() => handle.remove()))
      .catch(() => { /* plugin absent : aucun achat possible, rien à écouter */ });
  }

  iosOffer(key: PlanKey): IosPlanOffer | undefined {
    return this.iosOffers().find(o => o.plan === key);
  }

  private onIosVerified(data: AppleVerifyData | null): void {
    if (!data?.credited) return;
    this.activated.set(true);
    this.auth.me().subscribe();
    this.toast.showToast({ level: 'success', message: 'Abonnement activé avec succès !' });
  }

  /** Point d'entrée unique des boutons de palier : choisit le moyen de paiement. */
  buy(key: PlanKey): void {
    if (this.purchaseMode() === 'iap') this.purchaseNative(key);
    else this.subscribe(key);
  }

  private purchaseNative(key: PlanKey): void {
    if (this.isCurrentPlan(key) || this.isBelowCurrentPlan(key)) return;
    const offer = this.iosOffer(key);
    if (!offer || this.subscribing() !== null) return;

    this.subscribing.set(key);
    this.iosPurchase.purchase(offer.productId)
      .then(data => this.onIosVerified(data))
      .catch(err => {
        if (err instanceof IosPurchaseCancelledError) return;
        if (err instanceof IosPurchasePendingError) {
          this.toast.showToast({
            level: 'info',
            message: "Achat en attente de validation. Ton abonnement s'activera dès qu'il sera approuvé.",
          });
          return;
        }
        this.toast.showToast({
          level: 'error',
          message: err?.error?.feedback?.message ?? err?.feedback?.message
            ?? "L'achat n'a pas abouti. Si tu as été débité, utilise « Restaurer mes achats ».",
        });
      })
      .finally(() => this.subscribing.set(null));
  }

  restorePurchases(): void {
    if (this.restoring()) return;
    this.restoring.set(true);
    this.iosPurchase.restore()
      .then(data => {
        if (data?.credited) this.onIosVerified(data);
        else this.toast.showToast({ level: 'info', message: 'Aucun achat à restaurer.' });
      })
      .catch(err => this.toast.showToast({
        level: 'error',
        message: err?.error?.feedback?.message ?? 'La restauration a échoué. Réessaie dans un instant.',
      }))
      .finally(() => this.restoring.set(false));
  }

  // ── Stripe (web, Android) ──────────────────────────────────────────────────

  subscribe(key: PlanKey): void {
    if (this.isCurrentPlan(key) || this.isBelowCurrentPlan(key)) return;
    // Jamais de checkout Stripe pour un abonnement dans l'app iOS.
    if (!this.policy.guard('subscription')) return;

    this.subscribing.set(key);
    this.http.post<any>(`${environment.apiUrl}/api/premium/subscribe`, { plan: key })
      .subscribe({
        next: (res) => {
          if (res.success && res.data?.checkout_url) {
            window.location.href = res.data.checkout_url;
          } else {
            this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
            this.subscribing.set(null);
          }
        },
        error: (err) => {
          this.toast.showToast({
            level: 'error',
            message: err.error?.feedback?.message ?? 'Erreur lors de la redirection Stripe.',
          });
          this.subscribing.set(null);
        },
      });
  }
}
