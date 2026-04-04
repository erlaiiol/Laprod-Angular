import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import {
  WalletService, WalletInfo, WalletTransaction,
} from '../../services/wallet.service';
import { ToastService } from '../../services/toast.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-wallet',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './wallet.component.html',
  styleUrls: ['./wallet.component.scss'],
})
export class WalletComponent implements OnInit {

  // ── State ────────────────────────────────────────────────────────────────────

  loading          = signal(true);
  error            = signal<string | null>(null);
  wallet           = signal<WalletInfo | null>(null);
  transactions     = signal<WalletTransaction[]>([]);
  showConnectAlert = signal(false);

  // Withdraw modal
  showWithdrawModal = signal(false);
  withdrawAmount    = signal(0);
  withdrawing       = signal(false);
  withdrawError     = signal<string | null>(null);
  withdrawSuccess   = signal<string | null>(null);

  // Stripe setup
  settingUpStripe = signal(false);
  stripeError     = signal<string | null>(null);

  // ── Computed ─────────────────────────────────────────────────────────────────

  canWithdraw    = computed(() => (this.wallet()?.balance_available ?? 0) >= 10);
  stripeComplete = computed(() => this.wallet()?.stripe_onboarding_complete ?? false);

  // ── DI ───────────────────────────────────────────────────────────────────────

  private walletSvc = inject(WalletService);
  readonly auth     = inject(AuthService);
  private router    = inject(Router);
  private toast     = inject(ToastService);

  // ── Lifecycle ────────────────────────────────────────────────────────────────

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.walletSvc.getWallet().subscribe({
      next: (res) => {
        if (res.success) {
          this.wallet.set(res.data!.wallet);
          this.transactions.set(res.data!.transactions);
          this.showConnectAlert.set(res.data!.show_connect_alert);
          this.withdrawAmount.set(res.data!.wallet.balance_available);
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        }
        this.loading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger le portefeuille.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger le portefeuille.');
        this.loading.set(false);
      },
    });
  }

  // ── Stripe Connect ────────────────────────────────────────────────────────────

  setupStripe(): void {
    if (this.settingUpStripe()) return;
    this.settingUpStripe.set(true);
    this.stripeError.set(null);

    const returnUrl = window.location.href;
    this.walletSvc.getSetupUrl(returnUrl).subscribe({
      next: (res) => {
        if (res.success && res.data?.url) {
          window.location.href = res.data.url;
        } else {
          const msg = res.feedback?.message ?? 'Erreur Stripe Connect.';
          this.stripeError.set(msg);
          this.toast.showToast({ level: 'error', message: msg });
          this.settingUpStripe.set(false);
        }
      },
      error: (err) => {
        const msg = err?.error?.feedback?.message ?? 'Erreur Stripe Connect.';
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: msg });
        this.stripeError.set(msg);
        this.settingUpStripe.set(false);
      },
    });
  }

  openDashboard(): void {
    this.walletSvc.getDashboardUrl().subscribe({
      next: (res) => {
        if (res.success && res.data?.url) window.open(res.data.url, '_blank');
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible d\'ouvrir le dashboard Stripe.' });
        }
      },
    });
  }

  // ── Withdrawal ────────────────────────────────────────────────────────────────

  openWithdrawModal(): void {
    this.withdrawAmount.set(this.wallet()?.balance_available ?? 0);
    this.withdrawError.set(null);
    this.withdrawSuccess.set(null);
    this.showWithdrawModal.set(true);
  }

  closeWithdrawModal(): void {
    this.showWithdrawModal.set(false);
  }

  confirmWithdraw(): void {
    if (this.withdrawing()) return;
    const amount = this.withdrawAmount();
    if (amount < 10) {
      this.withdrawError.set('Montant minimum : 10€.');
      return;
    }

    this.withdrawing.set(true);
    this.withdrawError.set(null);

    this.walletSvc.withdraw(amount).subscribe({
      next: (res) => {
        if (res.success) {
          this.withdrawSuccess.set(`Retrait de ${res.data!.amount.toFixed(2)}€ initié avec succès.`);
          this.walletSvc.getWallet().subscribe({
            next: (r) => {
              if (r.success) {
                this.wallet.set(r.data!.wallet);
                this.transactions.set(r.data!.transactions);
              }
              this.withdrawing.set(false);
            },
            error: () => { this.withdrawing.set(false); },
          });
        } else {
          this.withdrawError.set(res.feedback?.message ?? 'Erreur de retrait.');
          this.withdrawing.set(false);
        }
      },
      error: (err) => {
        this.withdrawError.set(err?.error?.feedback?.message ?? 'Erreur serveur.');
        this.withdrawing.set(false);
      },
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────────

  isDebit(txn: WalletTransaction): boolean {
    return txn.type === 'withdrawal' || txn.type === 'expiration';
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  formatTime(iso: string): string {
    return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }
}
