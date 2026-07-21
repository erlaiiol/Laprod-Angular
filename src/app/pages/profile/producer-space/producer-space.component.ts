import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterModule } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { DashboardService, ProducerDashboard } from '../../../services/dashboard.service';
import { PLANNING_EVENT_TYPE_ICONS, PLANNING_EVENT_TYPE_LABELS, PlanningEventType } from '../../../services/planning.service';
import { ProducerTabsComponent } from '../../producer/producer-tabs/producer-tabs.component';

// ─────────────────────────────────────────────────────────────────────────────
// PRODUCER SPACE — "Vue d'ensemble" de l'espace producteur : même gabarit que
// dashboard-beatmaker/artist/mix-engineer (dash-header, stats-grid, tabs),
// alimenté par DashboardService.getProducerDashboard(). Onglets Roster/
// Planning/Royalties = routes séparées (trop substantielles pour être
// fusionnées ici) reliées par <app-producer-tabs>.
// ─────────────────────────────────────────────────────────────────────────────

interface QuickAction {
  icon: string;
  title: string;
  desc: string;
  link: string;
  cta: string;
}

@Component({
  selector: 'app-producer-space',
  standalone: true,
  imports: [RouterModule, ProducerTabsComponent],
  templateUrl: './producer-space.component.html',
  styleUrl: './producer-space.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProducerSpaceComponent implements OnInit {

  readonly auth        = inject(AuthService);
  private dashboardSvc = inject(DashboardService);

  loading = signal(true);
  error   = signal<string | null>(null);
  data    = signal<ProducerDashboard | null>(null);

  ngOnInit(): void {
    this.dashboardSvc.getProducerDashboard().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.data.set(res.data);
        } else {
          this.error.set(res.feedback?.message ?? 'Impossible de charger ton espace producteur.');
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger ton espace producteur.');
      },
    });
  }

  readonly actions: QuickAction[] = [
    {
      icon: 'bi-pencil-square',
      title: 'Créer un contrat',
      desc: 'Cession de droits, exclusivités, part SACEM, territoire, durée — configurés clause par clause, exportables en PDF signable.',
      link: '/contract-builder',
      cta: 'Ouvrir le builder',
    },
    {
      icon: 'bi-shield-check',
      title: 'Analyser un contrat',
      desc: 'Dépose n\'importe quel contrat musical : LaProd t\'explique droits, exclusivités et durée avant signature.',
      link: '/contract-analyzer',
      cta: 'Analyser',
    },
  ];

  eventIcon(type: string): string {
    return PLANNING_EVENT_TYPE_ICONS[type as PlanningEventType] ?? 'bi-calendar3';
  }

  eventLabel(type: string): string {
    return PLANNING_EVENT_TYPE_LABELS[type as PlanningEventType] ?? type;
  }

  formatEventDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  }
}
