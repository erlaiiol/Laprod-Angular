import { ChangeDetectionStrategy, Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../services/auth.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';

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
  readonly isPro     = this.auth.isPro;
  readonly isAmateur = this.auth.isAmateur;
  readonly plan      = computed(() => this.user()?.subscription_plan ?? 'free');

  subscribing  = signal<'amateur' | 'pro' | null>(null);
  activating   = signal(false);
  activated    = signal(false);

  ngOnInit(): void {
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
              this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur lors de l\'activation.' });
            }
          },
          error: (err) => {
            this.toast.showToast({ level: 'error', message: err.error?.feedback?.message ?? 'Erreur lors de l\'activation.' });
          },
          complete: () => this.activating.set(false),
        });
    }
  }

  scrollToPlans(event: Event): void {
    event.preventDefault();
    document.getElementById('plans')?.scrollIntoView({ behavior: 'smooth' });
  }

  subscribe(plan: 'amateur' | 'pro'): void {
    this.subscribing.set(plan);
    this.http.post<any>(`${environment.apiUrl}/api/premium/subscribe`, { plan })
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
          this.toast.showToast({ level: 'error', message: err.error?.feedback?.message ?? 'Erreur lors de la redirection Stripe.' });
          this.subscribing.set(null);
        },
      });
  }
}
