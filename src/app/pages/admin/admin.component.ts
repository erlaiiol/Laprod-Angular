import { ChangeDetectionStrategy, Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { AdminStats } from '../../services/admin.service';
import { ErrorService } from '../../services/error.service';

import { AdminDashboardComponent }    from './tabs/admin-dashboard.component';
import { AdminTracksComponent }       from './tabs/admin-tracks.component';
import { AdminUsersComponent }        from './tabs/admin-users.component';
import { AdminEngineersComponent }    from './tabs/admin-engineers.component';
import { AdminCategoriesComponent }   from './tabs/admin-categories.component';
import { AdminContractsComponent }    from './tabs/admin-contracts.component';
import { AdminTransactionsComponent }      from './tabs/admin-transactions.component';
import { AdminContractBuilderComponent }    from './tabs/admin-contract-builder.component';
import { AdminRecommendationsComponent }   from './tabs/admin-recommendations.component';
import { AdminSupportComponent }           from './tabs/admin-support.component';
import { AdminToplineComponent }           from './tabs/admin-toplines.component';
import { AdminInvoicesComponent }          from './tabs/admin-invoices.component';

export type AdminTab = 'dashboard' | 'tracks' | 'users' | 'engineers' | 'categories' | 'contracts' | 'transactions' | 'contract-builder' | 'recommendations' | 'support' | 'toplines' | 'invoices';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-admin',
  standalone: true,
  imports: [
    CommonModule,
    AdminDashboardComponent,
    AdminTracksComponent,
    AdminUsersComponent,
    AdminEngineersComponent,
    AdminCategoriesComponent,
    AdminContractsComponent,
    AdminTransactionsComponent,
    AdminContractBuilderComponent,
    AdminRecommendationsComponent,
    AdminSupportComponent,
    AdminToplineComponent,
    AdminInvoicesComponent,
  ],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
})
export class AdminComponent implements OnInit {

  activeTab = signal<AdminTab>('dashboard');

  // Badge counters (updated by child components via output events)
  pendingTracks    = signal(0);
  pendingEngineers = signal(0);

  constructor(
    private auth:     AuthService,
    private router:   Router,
    private errorSvc: ErrorService,
  ) {}

  ngOnInit(): void {
    if (!this.auth.isAdmin()) {
      this.errorSvc.set({ code: 403, context: 'admin' });
      this.router.navigate(['/erreur']);
    }
  }

  setTab(tab: AdminTab): void {
    this.activeTab.set(tab);
  }

  onStatsLoaded(stats: AdminStats): void {
    this.pendingTracks.set(stats.tracks.pending);
  }
}
