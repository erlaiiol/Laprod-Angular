import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterModule } from '@angular/router';

// ─────────────────────────────────────────────────────────────────────────────
// PRODUCER TABS — barre d'onglets partagée par les 4 pages producteur (Vue
// d'ensemble, Roster, Planning, Royalties). Chaque page reste une route à part
// entière (elles sont trop substantielles pour être fusionnées en un seul
// composant à bascule locale, contrairement aux tabs des autres dashboards) ;
// ce composant ne fait que donner la sensation d'onglets persistants en
// stylant des routerLink avec le même .tab-btn que dashboard-beatmaker/etc.
// ─────────────────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-producer-tabs',
  standalone: true,
  imports: [RouterModule],
  templateUrl: './producer-tabs.component.html',
  styleUrl: './producer-tabs.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProducerTabsComponent {}
