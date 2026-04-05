import { Component, OnInit, signal, Input } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AdminService, AdminStats } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (loading()) {
      <div class="loading-row"><span>Chargement…</span></div>
    }
    @if (stats(); as s) {
      <div class="stats-grid">
        <div class="stat-card"><div class="stat-value text-orange">{{ s.tracks.pending }}</div><div class="stat-label">Tracks en attente</div></div>
        <div class="stat-card"><div class="stat-value text-green">{{ s.tracks.approved }}</div><div class="stat-label">Tracks approuvés</div></div>
        <div class="stat-card"><div class="stat-value text-blue">{{ s.users.total }}</div><div class="stat-label">Utilisateurs actifs</div></div>
        <div class="stat-card"><div class="stat-value text-violet">{{ s.users.premium }}</div><div class="stat-label">Premium</div></div>
        <div class="stat-card"><div class="stat-value">{{ s.users.beatmakers }}</div><div class="stat-label">Beatmakers</div></div>
        <div class="stat-card"><div class="stat-value">{{ s.users.artists }}</div><div class="stat-label">Artistes</div></div>
        <div class="stat-card"><div class="stat-value">{{ s.users.engineers }}</div><div class="stat-label">Engineers</div></div>
        <div class="stat-card"><div class="stat-value text-green">{{ s.contracts.revenue | number:'1.0-0' }}€</div><div class="stat-label">Revenus contrats</div></div>
        <div class="stat-card"><div class="stat-value text-blue">{{ s.mixmaster.in_progress }}</div><div class="stat-label">Mix/Master en cours</div></div>
        <div class="stat-card"><div class="stat-value text-green">{{ s.mixmaster.revenue | number:'1.0-0' }}€</div><div class="stat-label">Revenus Mix/Master</div></div>
      </div>
      <div class="two-col">
        <div class="panel">
          <h3>Derniers tracks approuvés</h3>
          <div class="recent-list">
            @for (t of s.recent_tracks; track t.id) {
              <div class="recent-item">
                <img [src]="imgUrl(t.image_file)" class="thumb" alt="">
                <div><div class="item-title">{{ t.title }}</div><div class="item-sub">{{ t.composer?.username }} · {{ fmtDate(t.approved_at) }}</div></div>
              </div>
            }
          </div>
        </div>
        <div class="panel">
          <h3>Derniers inscrits</h3>
          <div class="recent-list">
            @for (u of s.recent_users; track u.id) {
              <div class="recent-item">
                <img [src]="imgUrl(u.profile_image)" class="thumb round" alt="">
                <div><div class="item-title">{{ u.username }}</div><div class="item-sub">{{ fmtDate(u.created_at) }}</div></div>
              </div>
            }
          </div>
        </div>
      </div>
    }
  `,
  styleUrl: '../admin.component.scss',
})
export class AdminDashboardComponent implements OnInit {
  @Input() onStatsLoaded?: (stats: AdminStats) => void;

  staticBase = `${environment.apiUrl.replace('/api', '')}/static/`;
  loading    = signal(false);
  stats      = signal<AdminStats | null>(null);

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getStats().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.stats.set(res.data);
          this.onStatsLoaded?.(res.data);
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement stats.' });
      },
    });
  }

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR');
  }
}
