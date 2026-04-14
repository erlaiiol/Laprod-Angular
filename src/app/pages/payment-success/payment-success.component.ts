import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { PaymentService } from '../../services/payment.service';

@Component({
  selector: 'app-payment-success',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './payment-success.component.html',
  styleUrls: ['./payment-success.component.scss'],
})
export class TrackPaymentSuccessComponent implements OnInit {

  state      = signal<'verifying' | 'success' | 'error'>('verifying');
  purchaseId = signal<number | null>(null);
  message    = signal('Vérification du paiement...');

  private route      = inject(ActivatedRoute);
  private paymentSvc = inject(PaymentService);

  ngOnInit(): void {
    const sessionId = this.route.snapshot.queryParamMap.get('session_id');
    if (!sessionId) {
      this.state.set('error');
      this.message.set('Paramètre session_id manquant.');
      return;
    }

    this.paymentSvc.verifyPayment(sessionId).subscribe({
      next: (res) => {
        if (res.success) {
          this.purchaseId.set(res.data?.purchase_id ?? null);
          this.state.set('success');
          this.message.set(res.feedback?.message ?? 'Paiement confirmé !');
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
