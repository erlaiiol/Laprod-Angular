import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { DashboardService, ArtistDashboard } from '../../../services/dashboard.service';
import { environment } from '../../../../environments/environment';

type Tab = 'toplines' | 'favorites' | 'history';

@Component({
  selector: 'app-dashboard-artist',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard-artist.component.html',
  styleUrls: ['./dashboard-artist.component.scss'],
})
export class DashboardArtistComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  data      = signal<ArtistDashboard | null>(null);
  activeTab = signal<Tab>('toplines');

  readonly auth        = inject(AuthService);
  private dashboardSvc = inject(DashboardService);
  private router       = inject(Router);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.dashboardSvc.getArtistDashboard().subscribe({
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

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-track.png';
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
}
