import { ChangeDetectionStrategy, Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { AuthService, PlanKey, PLAN_ORDER } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';
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

  subscribe(key: PlanKey): void {
    if (this.isCurrentPlan(key) || this.isBelowCurrentPlan(key)) return;

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
