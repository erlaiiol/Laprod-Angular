import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute, Router } from '@angular/router';
import { MixmasterService } from '../../../services/mixmaster.service';
import { ToastService } from '../../../services/toast.service';

@Component({
  selector: 'app-mix-payment-success',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './payment-success.component.html',
  styleUrls: ['./payment-success.component.scss'],
})
export class MixPaymentSuccessComponent implements OnInit {

  state   = signal<'verifying' | 'success' | 'error'>('verifying');
  orderId = signal<number | null>(null);
  message = signal('Vérification du paiement...');

  private route  = inject(ActivatedRoute);
  private router = inject(Router);
  private mixSvc = inject(MixmasterService);
  private toast  = inject(ToastService);

  ngOnInit(): void {
    const sessionId = this.route.snapshot.queryParamMap.get('session_id');
    if (!sessionId) {
      this.state.set('error');
      this.message.set('Paramètre session_id manquant.');
      return;
    }

    this.mixSvc.verifyPayment(sessionId).subscribe({
      next: (res) => {
        if (res.success) {
          this.orderId.set(res.data?.order_id ?? null);
          this.state.set('success');
          this.message.set(res.feedback?.message ?? 'Paiement confirmé !');
          if (res.feedback) this.toast.showToast(res.feedback);
        } else {
          this.state.set('error');
          this.message.set(res.feedback?.message ?? 'Erreur lors de la vérification.');
        }
      },
      error: (err) => {
        this.state.set('error');
        this.message.set(err?.error?.feedback?.message ?? 'Erreur serveur lors de la vérification.');
      },
    });
  }
}
