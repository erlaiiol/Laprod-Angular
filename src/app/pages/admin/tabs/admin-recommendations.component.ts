import { ChangeDetectionStrategy, Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { BaseChartDirective } from 'ng2-charts';
import {
  Chart, DoughnutController, ArcElement, BarController, BarElement,
  LineController, LineElement, PointElement, Filler,
  PolarAreaController, RadarController, RadialLinearScale,
  CategoryScale, LinearScale, Legend, Tooltip,
} from 'chart.js';
import type { ChartConfiguration } from 'chart.js';
import { AdminService, RecommendationStats, MusicStats, BehaviorStats } from '../../../services/admin.service';

// Enregistrement sélectif des types réellement utilisés dans cet onglet :
// anneau/jauge, barres, aire (line+fill), polaire, radar. On choisit le graphe
// selon la FORME de la donnée, pas pour la variété.
Chart.register(
  DoughnutController, ArcElement, BarController, BarElement,
  LineController, LineElement, PointElement, Filler,
  PolarAreaController, RadarController, RadialLinearScale,
  CategoryScale, LinearScale, Legend, Tooltip,
);

// Palette cohérente avec le reste de l'admin (fond sombre).
const PALETTE = ['#4a9eff', '#4caf50', '#a78bfa', '#ff9800', '#f06292',
                 '#26c6da', '#ffca28', '#8d6e63', '#66bb6a', '#ec407a'];

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-admin-recommendations',
  standalone: true,
  imports: [CommonModule, BaseChartDirective],
  templateUrl: './admin-recommendations.component.html',
  styleUrls: ['./admin-recommendations.component.scss'],
})
export class AdminRecommendationsComponent implements OnInit {

  loading = signal(true);
  stats   = signal<RecommendationStats | null>(null);
  error   = signal<string | null>(null);

  readonly music    = computed<MusicStats | null>(() => this.stats()?.music_stats ?? null);
  readonly behavior = computed<BehaviorStats | null>(() => this.stats()?.behavior_stats ?? null);

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

  // ── Graphiques « Portrait musical » ──────────────────────────────────────
  // Le TYPE de graphe suit la nature de la donnée :
  //   part d'un tout       → camembert (mode majeur/mineur, styles)
  //   distribution ordonnée → barres    (tonalités, familles de tempo)
  //   corrélation croisée  → barres     (mode par style empilé, tempo moyen)

  private readonly doughnutOpts: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'bottom', labels: { color: '#bbb', boxWidth: 12 } } },
  };

  private readonly barOpts: ChartConfiguration<'bar'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#999' }, grid: { display: false } },
      y: { ticks: { color: '#999' }, grid: { color: 'rgba(255,255,255,.06)' }, beginAtZero: true },
    },
  };

  private readonly stackedOpts: ChartConfiguration<'bar'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'bottom', labels: { color: '#bbb', boxWidth: 12 } } },
    scales: {
      x: { stacked: true, ticks: { color: '#999' }, grid: { display: false } },
      y: { stacked: true, ticks: { color: '#999' }, grid: { color: 'rgba(255,255,255,.06)' }, beginAtZero: true },
    },
  };

  get doughnutOptions() { return this.doughnutOpts; }
  get barOptions()      { return this.barOpts; }
  get stackedOptions()  { return this.stackedOpts; }

  modesData = computed<ChartConfiguration<'doughnut'>['data']>(() => {
    const m = this.music()?.modes ?? [];
    return {
      labels: m.map(x => x.label),
      // Mineur en bleu (dominant en rap/trap), majeur en ambre : deux teintes lisibles.
      datasets: [{ data: m.map(x => x.value), backgroundColor: ['#4a9eff', '#ffca28'], borderWidth: 0 }],
    };
  });

  stylesData = computed<ChartConfiguration<'doughnut'>['data']>(() => {
    const s = this.music()?.styles ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{ data: s.map(x => x.value),
                   backgroundColor: s.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0 }],
    };
  });

  keysData = computed<ChartConfiguration<'bar'>['data']>(() => {
    const k = this.music()?.keys ?? [];
    return {
      labels: k.map(x => x.label),
      datasets: [{ data: k.map(x => x.value), backgroundColor: '#4a9eff', borderRadius: 3 }],
    };
  });

  tempoData = computed<ChartConfiguration<'bar'>['data']>(() => {
    const t = this.music()?.tempo_families ?? [];
    return {
      labels: t.map(x => `${x.label} (${x.range})`),
      datasets: [{ data: t.map(x => x.value), backgroundColor: '#a78bfa', borderRadius: 3 }],
    };
  });

  modeByStyleData = computed<ChartConfiguration<'bar'>['data']>(() => {
    const rows = this.music()?.mode_by_style ?? [];
    return {
      labels: rows.map(r => r.style),
      datasets: [
        { label: 'Mineur', data: rows.map(r => r.minor), backgroundColor: '#4a9eff' },
        { label: 'Majeur', data: rows.map(r => r.major), backgroundColor: '#ffca28' },
      ],
    };
  });

  avgTempoData = computed<ChartConfiguration<'bar'>['data']>(() => {
    const rows = this.music()?.avg_tempo_by_style ?? [];
    return {
      labels: rows.map(r => r.style),
      datasets: [{ data: rows.map(r => r.avg_bpm), backgroundColor: '#4caf50', borderRadius: 3 }],
    };
  });

  hasMusic = computed(() => (this.music()?.total_tracks ?? 0) > 0);

  // ── Graphiques « Comportement » ──────────────────────────────────────────
  // Chaque type suit la forme de la donnée :
  //   série temporelle → aire | cyclique → polaire | distribution → barres
  //   part d'un tout → anneau | profil multi-axes → radar | proportion → jauge

  private readonly polarOpts: ChartConfiguration<'polarArea'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { position: 'bottom', labels: { color: '#bbb', boxWidth: 12 } } },
    scales: { r: { ticks: { display: false }, grid: { color: 'rgba(255,255,255,.08)' } } },
  };

  private readonly radarOpts: ChartConfiguration<'radar'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      r: {
        beginAtZero: true,
        angleLines: { color: 'rgba(255,255,255,.08)' },
        grid: { color: 'rgba(255,255,255,.08)' },
        pointLabels: { color: '#bbb', font: { size: 10 } },
        ticks: { display: false },
      },
    },
  };

  private readonly areaOpts: ChartConfiguration<'line'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { ticks: { color: '#999', maxRotation: 0 }, grid: { display: false } },
      y: { ticks: { color: '#999', precision: 0 }, grid: { color: 'rgba(255,255,255,.06)' }, beginAtZero: true },
    },
  };

  // Jauge = demi-anneau (circumference 180°, départ à gauche).
  private readonly gaugeOpts: ChartConfiguration<'doughnut'>['options'] = {
    responsive: true, maintainAspectRatio: false,
    circumference: 180, rotation: -90, cutout: '72%',
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
  };

  get polarOptions() { return this.polarOpts; }
  get radarOptions() { return this.radarOpts; }
  get areaOptions()  { return this.areaOpts; }
  get gaugeOptions() { return this.gaugeOpts; }

  uploadRegularityData = computed<ChartConfiguration<'line'>['data']>(() => {
    const s = this.behavior()?.upload_regularity ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{
        data: s.map(x => x.value),
        borderColor: '#4a9eff',
        backgroundColor: 'rgba(74,158,255,.18)',
        fill: true, tension: 0.35, pointRadius: 2, borderWidth: 2,
      }],
    };
  });

  weekdayData = computed<ChartConfiguration<'polarArea'>['data']>(() => {
    const s = this.behavior()?.uploads_by_weekday ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{
        data: s.map(x => x.value),
        backgroundColor: s.map((_, i) => PALETTE[i % PALETTE.length] + 'cc'),
        borderWidth: 0,
      }],
    };
  });

  listenSourcesData = computed<ChartConfiguration<'doughnut'>['data']>(() => {
    const s = this.behavior()?.listen_sources ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{ data: s.map(x => x.value),
                   backgroundColor: s.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0 }],
    };
  });

  browseHistogramData = computed<ChartConfiguration<'bar'>['data']>(() => {
    const s = this.behavior()?.beats_before_topline?.histogram ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{ data: s.map(x => x.value), backgroundColor: '#26c6da', borderRadius: 3 }],
    };
  });

  toplineTempoData = computed<ChartConfiguration<'radar'>['data']>(() => {
    const s = this.music()?.topline_by_tempo ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{
        data: s.map(x => x.value),
        borderColor: '#f06292',
        backgroundColor: 'rgba(240,98,146,.2)',
        pointBackgroundColor: '#f06292', borderWidth: 2,
      }],
    };
  });

  minorGaugeData = computed<ChartConfiguration<'doughnut'>['data']>(() => {
    const pct = this.music()?.minor_ratio?.pct_minor ?? 0;
    return {
      labels: ['Mineur', 'Majeur'],
      datasets: [{ data: [pct, 100 - pct], backgroundColor: ['#4a9eff', 'rgba(255,255,255,.08)'],
                   borderWidth: 0 }],
    };
  });

  // Régularité des connexions — même paire de graphes que la régularité d'upload
  // (aire pour la tendance, polaire pour le cycle hebdomadaire), sur une couleur
  // distincte pour ne pas confondre les deux séries au premier coup d'œil.
  loginRegularityData = computed<ChartConfiguration<'line'>['data']>(() => {
    const s = this.behavior()?.login_regularity ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{
        data: s.map(x => x.value),
        borderColor: '#4caf50',
        backgroundColor: 'rgba(76,175,80,.18)',
        fill: true, tension: 0.35, pointRadius: 2, borderWidth: 2,
      }],
    };
  });

  loginsByWeekdayData = computed<ChartConfiguration<'polarArea'>['data']>(() => {
    const s = this.behavior()?.logins_by_weekday ?? [];
    return {
      labels: s.map(x => x.label),
      datasets: [{
        data: s.map(x => x.value),
        backgroundColor: s.map((_, i) => PALETTE[(i + 3) % PALETTE.length] + 'cc'),
        borderWidth: 0,
      }],
    };
  });

  hasBehavior = computed(() => {
    const b = this.behavior();
    if (!b) return false;
    return b.upload_regularity.some(x => x.value > 0)
        || b.listen_sources.length > 0
        || b.beats_before_topline.sample > 0
        || b.login_regularity.some(x => x.value > 0);
  });

  hasLogins = computed(() => (this.behavior()?.login_regularity ?? []).some(x => x.value > 0));
}
