import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import {
  DashboardService, MixEngineerDashboard, MixOrder,
} from '../../../services/dashboard.service';
import { environment } from '../../../../environments/environment';

type Tab = 'awaiting' | 'active' | 'revisions' | 'completed' | 'refused';

@Component({
  selector: 'app-dashboard-mix-engineer',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard-mix-engineer.component.html',
  styleUrls: ['./dashboard-mix-engineer.component.scss'],
})
export class DashboardMixEngineerComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  data      = signal<MixEngineerDashboard | null>(null);
  activeTab = signal<Tab>('awaiting');

  readonly auth        = inject(AuthService);
  private dashboardSvc = inject(DashboardService);
  private router       = inject(Router);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.dashboardSvc.getMixEngineerDashboard().subscribe({
      next: (res) => {
        if (res.success) this.data.set(res.data!);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de contacter le serveur.');
        this.loading.set(false);
      },
    });
  }

  setTab(tab: Tab): void { this.activeTab.set(tab); }

  currentOrders(): MixOrder[] {
    const d = this.data();
    if (!d) return [];
    return d.orders[this.activeTab()];
  }

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-avatar.png';
  }

  formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  statusLabel(status: string): string {
    const labels: Record<string, string> = {
      awaiting_acceptance: 'En attente',
      accepted:            'Acceptée',
      processing:          'En cours',
      delivered:           'Livrée',
      revision1:           'Révision 1',
      revision2:           'Révision 2',
      completed:           'Terminée',
      rejected:            'Refusée',
      refunded:            'Remboursée',
    };
    return labels[status] ?? status;
  }

  servicesList(order: MixOrder): string[] {
    const list: string[] = [];
    if (order.services.cleaning)  list.push('Nettoyage');
    if (order.services.effects)   list.push('Effets');
    if (order.services.artistic)  list.push('Direction artistique');
    if (order.services.mastering) list.push('Mastering');
    return list;
  }
}
