import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AdminService, AdminPurchaseInvoice, AdminMixmasterInvoice, AdminInvoicesData } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-admin-invoices',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './admin-invoices.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminInvoicesComponent implements OnInit {

  loading       = signal(false);
  purchases     = signal<AdminPurchaseInvoice[]>([]);
  mmRequests    = signal<AdminMixmasterInvoice[]>([]);
  totals        = signal<AdminInvoicesData['totals'] | null>(null);
  activeSection = signal<'purchases' | 'mixmaster'>('purchases');

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.loadInvoices(); }

  loadInvoices(): void {
    this.loading.set(true);
    this.adminSvc.getAdminInvoices().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.purchases.set(res.data.purchases);
          this.mmRequests.set(res.data.mm_requests);
          this.totals.set(res.data.totals);
        }
      },
      error: () => {
        this.loading.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur chargement des factures.' });
      },
    });
  }

  downloadUrl(path: string): string {
    return `${environment.apiUrl}${path}`;
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR');
  }

  fmtAmount(n: number): string {
    return n.toFixed(2) + ' €';
  }

  mmStatusLabel(status: string): string {
    const labels: Record<string, string> = {
      accepted:   'Acceptée',
      processing: 'En cours',
      delivered:  'Livrée',
      revision1:  'Révision 1',
      revision2:  'Révision 2',
      completed:  'Terminée',
    };
    return labels[status] ?? status;
  }
}
