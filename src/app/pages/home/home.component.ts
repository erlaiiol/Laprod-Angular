// ─────────────────────────────────────────────────────────────────────────────
// PAGE HOME
// Rôle : orchestrer. Elle charge les tracks depuis l'API et les distribue
// vers TrackCardComponent. Elle réagit aux filtres posés par Navbar.
// Si l'utilisateur est connecté et n'a pas de filtres actifs → recommandations.
// ─────────────────────────────────────────────────────────────────────────────

import { Component, OnInit, signal, computed, effect, inject, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

import { TrackService, Track, TrackFilters } from '../../services/track.service';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { TagCategoryFilterComponent } from '../../components/tag-category-filter/tag-category-filter.component';
import { OnboardingModalComponent } from '../../components/onboarding-modal/onboarding-modal.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { FilterStateService, ActiveFilters } from '../../services/filter-state.service';
import { ToastService } from '../../services/toast.service';
import { FavoritesService } from '../../services/favorites.service';
import { AuthService } from '../../services/auth.service';
import { RevealOnScrollDirective } from '../../directives/reveal-on-scroll.directive';

const PER_PAGE = 20;

// ── Statistiques landing ──────────────────────────────────────────────────────
// Valeurs vitrines (pas branchées sur l'API) — à ajuster à mesure que la
// plateforme grandit. Animées en count-up à l'entrée dans le viewport.
interface LandingStat {
  icon: string;
  target: number;
  suffix: string;
  label: string;
}

const LANDING_STATS: LandingStat[] = [
  { icon: 'bi-music-note-beamed',       target: 150,  suffix: '+', label: 'beats en ligne' },
  { icon: 'bi-people-fill',             target: 45,   suffix: '+', label: 'créateurs inscrits' },
  { icon: 'bi-file-earmark-check-fill', target: 60,   suffix: '+', label: 'contrats générés' },
  { icon: 'bi-headphones',              target: 2400, suffix: '+', label: 'écoutes cette semaine' },
];

const STATS_COUNTUP_MS = 1600;

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule, RouterModule, TrackCardComponent, TagCategoryFilterComponent, OnboardingModalComponent, PaginationComponent, RevealOnScrollDirective],
  templateUrl: './home.component.html',
  styleUrls:   ['./home.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HomeComponent implements OnInit {

  tracks          = signal<Track[]>([]);
  loading         = signal(true);
  error           = signal<string | null>(null);

  showOnboarding  = signal(false);
  showHero        = signal(false);
  heroTab         = signal<'artiste' | 'beatmaker' | 'ingenieur' | 'producteur'>('artiste');
  displayMode     = signal<'list' | 'gallery'>(
    (localStorage.getItem('laprod_display_mode') as 'list' | 'gallery') ?? 'gallery'
  );

  // Pagination
  page       = signal(1);
  totalPages = signal(1);

  // Stats landing — count-up déclenché par lpReveal sur le bandeau
  readonly landingStats = LANDING_STATS;
  statValues = signal<number[]>(LANDING_STATS.map(() => 0));
  private statsStarted = false;

  private trackService       = inject(TrackService);
  private filterStateService = inject(FilterStateService);
  private toast              = inject(ToastService);
  private favSvc             = inject(FavoritesService);
  readonly auth              = inject(AuthService);

  constructor() {
    // Filtre ou catégorie changent → toujours revenir à la page 1
    effect(() => {
      this.filterStateService.applied();
      this.auth.preferredTagCategory();
      this.loadTracks(1);
    }, { allowSignalWrites: true });
  }

  ngOnInit(): void {
    if (!this.auth.isLoggedIn() && !localStorage.getItem('laprod_visited')) {
      this.showHero.set(true);
      localStorage.setItem('laprod_visited', '1');
    }

    const user = this.auth.currentUser();
    const hasRole = user && (user.roles.is_artist || user.roles.is_beatmaker || user.roles.is_mix_engineer);
    // Ne pas redemander si l'utilisateur a déjà une préférence (backend ou mode artistes local)
    const alreadyHasPref = !!user?.preferred_tag_category
      || localStorage.getItem('card_info_mode') === 'artists';
    if (hasRole && !alreadyHasPref && OnboardingModalComponent.shouldShow()) {
      localStorage.setItem('laprod_onboarding_done', '1');
      this.showOnboarding.set(true);
    }
  }

  dismissHero(): void {
    this.showHero.set(false);
  }

  startStatsCountUp(): void {
    if (this.statsStarted) return;
    this.statsStarted = true;

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.statValues.set(LANDING_STATS.map((s) => s.target));
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - start) / STATS_COUNTUP_MS, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      this.statValues.set(LANDING_STATS.map((s) => Math.round(s.target * eased)));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  formatStat(value: number): string {
    return value.toLocaleString('fr-FR');
  }

  setDisplayMode(mode: 'list' | 'gallery'): void {
    this.displayMode.set(mode);
    localStorage.setItem('laprod_display_mode', mode);
  }

  goToPage(p: number): void {
    this.loadTracks(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  loadTracks(page = 1): void {
    this.page.set(page);
    this.loading.set(true);
    this.error.set(null);
    this._loadRegularTracks(page);
  }

  private _loadRegularTracks(page: number): void {
    const apiFilters: TrackFilters = {
      ...this.toTrackFilters(this.filterStateService.filters()),
      page,
      per_page: PER_PAGE,
      sort: this.auth.isLoggedIn() ? 'recommended' : undefined,
    };

    this.trackService.getTracks(apiFilters).subscribe({
      next: (response) => {
        if (response.success) {
          this.totalPages.set(response.data.pagination.pages);
          if (this.auth.isLoggedIn()) {
            const ids = (response.data.tracks as Track[]).map((t: Track) => t.id);
            // Prefetch lancé avant le rendu : FavoriteButtonComponent s'y branche
            // automatiquement via favSvc.check() — pas besoin d'attendre ici.
            this.favSvc.prefetch(ids).subscribe();
          }
          this.tracks.set(response.data.tracks);
          this.loading.set(false);
        } else {
          this.error.set('Le serveur a répondu mais signale une erreur.');
          this.loading.set(false);
        }
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de contacter le serveur.' });
        }
        this.error.set('Impossible de contacter le serveur.');
        this.loading.set(false);
      }
    });
  }

  private toTrackFilters(f: ActiveFilters): TrackFilters {
    return {
      search:             f.search   || undefined,
      bpm_min:            f.bpmMin   ?? undefined,
      bpm_max:            f.bpmMax   ?? undefined,
      keys:               f.keys.length           ? f.keys.join(',')           : undefined,
      styles:             f.styles.length          ? f.styles.join(',')          : undefined,
      tags:               f.tags.length            ? f.tags.join(',')            : undefined,
      similar_artist_ids: f.similarArtists?.length ? f.similarArtists.join(',') : undefined,
      // tag_category N'EST PAS envoyé comme filtre : la catégorie préférée informe
      // uniquement l'algorithme de recommandation (persistée via AuthService),
      // elle ne doit jamais exclure des tracks de la liste visible.
    };
  }

}
