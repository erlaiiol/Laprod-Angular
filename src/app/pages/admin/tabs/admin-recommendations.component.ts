import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { AdminService, RecommendationStats } from '../../../services/admin.service';

@Component({
  selector: 'app-admin-recommendations',
  standalone: true,
  imports: [CommonModule],
  template: `
    @if (loading()) {
      <div class="loading-row"><span>Chargement…</span></div>
    }
    @if (stats(); as s) {
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-value text-blue">{{ s.total_listen_events }}</div>
          <div class="stat-label">Événements d'écoute</div>
        </div>
        <div class="stat-card">
          <div class="stat-value text-green">{{ s.active_users_last_7d }}</div>
          <div class="stat-label">Utilisateurs actifs (7j)</div>
        </div>
      </div>

      <div class="two-col">
        <div class="panel">
          <h3>Top gammes écoutées</h3>
          @for (item of s.top_keys; track item[0]) {
            <div class="bar-row">
              <span class="bar-label">{{ item[0] }}</span>
              <div class="bar-track">
                <div class="bar-fill" [style.width.%]="barPct(item[1], s.top_keys)"></div>
              </div>
              <span class="bar-count">{{ item[1] }}</span>
            </div>
          }
          @if (s.top_keys.length === 0) {
            <p class="empty-note">Aucune donnée.</p>
          }
        </div>

        <div class="panel">
          <h3>Top tags écoutés</h3>
          @for (item of s.top_tags; track item[0]) {
            <div class="bar-row">
              <span class="bar-label">{{ item[0] }}</span>
              <div class="bar-track">
                <div class="bar-fill" [style.width.%]="barPct(item[1], s.top_tags)"></div>
              </div>
              <span class="bar-count">{{ item[1] }}</span>
            </div>
          }
          @if (s.top_tags.length === 0) {
            <p class="empty-note">Aucune donnée.</p>
          }
        </div>
      </div>

      <div class="panel">
        <h3>Corrélations de gammes (top 20)</h3>
        @if (s.top_correlations.length > 0) {
          <table class="corr-table">
            <thead>
              <tr><th>Si l'utilisateur écoute</th><th>Il écoutera aussi</th><th>Probabilité</th></tr>
            </thead>
            <tbody>
              @for (c of s.top_correlations; track c.from + c.to) {
                <tr>
                  <td>{{ c.from }}</td>
                  <td>{{ c.to }}</td>
                  <td>{{ (c.probability * 100) | number:'1.0-0' }}%</td>
                </tr>
              }
            </tbody>
          </table>
        } @else {
          <p class="empty-note">Aucune corrélation calculée. Le job nightly n'a pas encore tourné.</p>
        }
      </div>

      @if (s.top_artists && s.top_artists.length > 0) {
        <div class="panel">
          <h3>Top artistes similaires écoutés</h3>
          @for (item of s.top_artists; track item[0]) {
            <div class="bar-row">
              <span class="bar-label" style="width:140px; font-style:italic;">{{ item[0] }}</span>
              <div class="bar-track">
                <div class="bar-fill" style="background:#a78bfa"
                     [style.width.%]="barPct(item[1], s.top_artists!)"></div>
              </div>
              <span class="bar-count">{{ item[1] }}</span>
            </div>
          }
        </div>
      }

      @if (s.artist_correlations && s.artist_correlations.length > 0) {
        <div class="panel">
          <h3>Corrélations artistes similaires (top 20)</h3>
          <table class="corr-table">
            <thead>
              <tr><th>Si écoute référencé par</th><th>Écoute aussi référencé par</th><th>Probabilité</th></tr>
            </thead>
            <tbody>
              @for (c of s.artist_correlations; track c.from + c.to) {
                <tr>
                  <td style="font-style:italic;">{{ c.from }}</td>
                  <td style="font-style:italic;">{{ c.to }}</td>
                  <td>{{ (c.probability * 100) | number:'1.0-0' }}%</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    }
    @if (error()) {
      <div class="state-error">{{ error() }}</div>
    }
  `,
  styles: [`
    .stats-grid { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
    .stat-card  { background: var(--surface, #1e1e1e); border-radius: 8px; padding: 1rem 1.5rem; min-width: 150px; }
    .stat-value { font-size: 2rem; font-weight: 700; }
    .stat-label { font-size: .75rem; color: #888; margin-top: .25rem; }
    .text-blue  { color: #4a9eff; }
    .text-green { color: #4caf50; }
    .two-col    { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
    .panel      { background: var(--surface, #1e1e1e); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
    .panel h3   { font-size: .9rem; color: #aaa; margin-bottom: .75rem; text-transform: uppercase; letter-spacing: .05em; }
    .bar-row    { display: flex; align-items: center; gap: .5rem; margin-bottom: .4rem; font-size: .85rem; }
    .bar-label  { width: 110px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .bar-track  { flex: 1; background: #333; border-radius: 3px; height: 8px; overflow: hidden; }
    .bar-fill   { height: 100%; background: #4a9eff; border-radius: 3px; transition: width .3s; }
    .bar-count  { width: 36px; text-align: right; color: #888; }
    .corr-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    .corr-table th, .corr-table td { padding: .4rem .75rem; border-bottom: 1px solid #333; text-align: left; }
    .corr-table th { color: #888; font-weight: 600; }
    .empty-note { color: #666; font-style: italic; font-size: .85rem; }
    .loading-row { padding: 2rem; text-align: center; color: #888; }
    .state-error { color: #f44336; padding: 1rem; }
    @media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
  `],
})
export class AdminRecommendationsComponent implements OnInit {

  loading = signal(true);
  stats   = signal<RecommendationStats | null>(null);
  error   = signal<string | null>(null);

  constructor(private adminSvc: AdminService) {}

  ngOnInit(): void {
    this.adminSvc.getRecommendationStats().subscribe({
      next: (res) => {
        if (res.success && res.data) {
          this.stats.set(res.data);
        } else {
          this.error.set('Erreur lors du chargement des statistiques.');
        }
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de contacter le serveur.');
        this.loading.set(false);
      },
    });
  }

  barPct(value: number, list: [string, number][]): number {
    const max = list[0]?.[1] ?? 1;
    return max > 0 ? Math.round((value / max) * 100) : 0;
  }
}
