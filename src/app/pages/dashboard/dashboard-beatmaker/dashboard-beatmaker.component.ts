import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { Router } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import {
  DashboardService, BeatmakerDashboard, BeatmakerTrack, SaleRecord,
} from '../../../services/dashboard.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

type Tab = 'tracks' | 'sales';

@Component({
  selector: 'app-dashboard-beatmaker',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dashboard-beatmaker.component.html',
  styleUrls: ['./dashboard-beatmaker.component.scss'],
})
export class DashboardBeatmakerComponent implements OnInit {

  loading  = signal(true);
  error    = signal<string | null>(null);
  data     = signal<BeatmakerDashboard | null>(null);
  activeTab = signal<Tab>('tracks');

  readonly auth         = inject(AuthService);
  private dashboardSvc  = inject(DashboardService);
  private router        = inject(Router);
  private toast         = inject(ToastService);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.dashboardSvc.getBeatmakerDashboard().subscribe({
      next: (res) => {
        if (res.success) this.data.set(res.data!);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger l\'espace beatmaker.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger l\'espace beatmaker.');
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

  formatLabel(format: string): string {
    const labels: Record<string, string> = { mp3: 'MP3', wav: 'WAV', stems: 'STEMS' };
    return labels[format] ?? format.toUpperCase();
  }
}
