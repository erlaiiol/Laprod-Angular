import { ChangeDetectionStrategy, Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AdminService, AdminTransaction } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { FormatDatePipe } from '../../../pipes/format-date.pipe';

type TxStatus = 'all' | 'awaiting' | 'in_progress' | 'completed';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-admin-transactions',
  standalone: true,
  imports: [CommonModule, FormatDatePipe],
  templateUrl: './admin-transactions.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminTransactionsComponent implements OnInit {

  loading      = signal(false);
  transactions = signal<AdminTransaction[]>([]);
  txStatus     = signal<TxStatus>('all');
  counts       = signal<Record<string, number>>({});
  revenue      = signal(0);

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getTransactions(this.txStatus()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.transactions.set(res.data.transactions);
          this.counts.set(res.data.counts);
          this.revenue.set(res.data.total_revenue);
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement transactions.' });
      },
    });
  }

  setStatus(status: TxStatus): void {
    this.txStatus.set(status);
    this.load();
  }

}
