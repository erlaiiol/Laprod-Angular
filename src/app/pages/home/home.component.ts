// ─────────────────────────────────────────────────────────────────────────────
// PAGE HOME
// Rôle : orchestrer. Elle charge les tracks depuis l'API et les distribue
// vers TrackCardComponent. Elle réagit aux filtres posés par Navbar.
// Si l'utilisateur est connecté et n'a pas de filtres actifs → recommandations.
// ─────────────────────────────────────────────────────────────────────────────

import { Component, OnInit, signal, computed, effect, untracked, inject, ChangeDetectionStrategy } from '@angular/core';
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
import { environment } from '../../../environments/environment';

const PER_PAGE = 20;

// ── Statistiques landing ──────────────────────────────────────────────────────
interface LandingStat {
  icon:   string;
  suffix: string;
  label:  string;
}

const LANDING_STATS: LandingStat[] = [
  { icon: 'bi-music-note-beamed',   suffix: '+', label: 'beats en ligne' },
  { icon: 'bi-people-fill',         suffix: '+', label: 'artistes inscrits' },
  { icon: 'bi-bag-check-fill',      suffix: '+', label: 'licences vendues' },
  { icon: 'bi-mic-fill',            suffix: '+', label: 'toplines publiées' },
];

const LANDING_STATS_FALLBACK = [150, 45, 60, 120];

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
  displayMode     = signal<'list' | 'gallery' | 'compact'>(
    (localStorage.getItem('laprod_display_mode') as 'list' | 'gallery' | 'compact') ?? 'gallery'
  );

  // Pagination
  page       = signal(1);
  totalPages = signal(1);

  readonly apiUrl = environment.apiUrl;

  // Stats landing — count-up déclenché par lpReveal sur le bandeau
  readonly landingStats = LANDING_STATS;
  statValues  = signal<number[]>(LANDING_STATS.map(() => 0));
  statTargets = signal<number[]>(LANDING_STATS_FALLBACK);
  private statsStarted = false;

  private trackService       = inject(TrackService);
  private filterStateService = inject(FilterStateService);
  private toast              = inject(ToastService);
  private favSvc             = inject(FavoritesService);
  readonly auth              = inject(AuthService);

  // -1 = premier rendu (retour depuis une autre page → restaurer savedPage)
  private _lastApplied = -1;

  constructor() {
    effect(() => {
      const applied = this.filterStateService.applied();
      this.auth.preferredTagCategory();

      if (this._lastApplied === -1) {
        // Premier rendu : restaurer la page mémorisée (retour depuis track-detail).
        // untracked() : lire savedPage() ici ne doit PAS l'ajouter aux dépendances
        // de cet effect — sinon le premier clic pagination (qui écrit savedPage
        // via loadTracks) re-déclenche cet effect et loadTracks(1) écrase la page
        // qu'on vient de choisir. Bug réel observé : cassé au 1er clic seulement,
        // car la branche else ci-dessous ne relit plus savedPage() ensuite.
        this._lastApplied = applied;
        this.loadTracks(untracked(() => this.filterStateService.savedPage()));
      } else {
        // Filtre ou catégorie changés → page 1
        this._lastApplied = applied;
        this.loadTracks(1);
      }
    }, { allowSignalWrites: true });
  }

  ngOnInit(): void {
    if (!this.auth.isLoggedIn() && !localStorage.getItem('laprod_visited')) {
      this.showHero.set(true);
      localStorage.setItem('laprod_visited', '1');
    }

    const user = this.auth.currentUser();
    const hasRole = user && (user.roles.is_artist || user.roles.is_beatmaker || user.roles.is_mix_engineer);
    const alreadyHasPref = !!user?.preferred_tag_category
      || localStorage.getItem('card_info_mode') === 'artists';
    if (hasRole && !alreadyHasPref && OnboardingModalComponent.shouldShow()) {
      localStorage.setItem('laprod_onboarding_done', '1');
      this.showOnboarding.set(true);
    }

    // Charger les stats réelles de la plateforme pour le bandeau landing
    this.trackService.getPlatformStats().subscribe({
      next: (res) => {
        if (res.success && res.data) {
          this.statTargets.set([
            res.data.beats_count,
            res.data.artists_count,
            res.data.licenses_sold,
            res.data.toplines_count,
          ]);
        }
      },
      error: () => { /* fallback sur LANDING_STATS_FALLBACK déjà en place */ },
    });
  }

  dismissHero(): void {
    this.showHero.set(false);
    // Wait one tick for Angular to remove the hero from the DOM before scrolling,
    // otherwise the browser tries to maintain the old scroll offset and lands at
    // the bottom of the (now shorter) page on mobile.
    setTimeout(() => window.scrollTo({ top: 0, behavior: 'instant' }), 0);
  }

  startStatsCountUp(): void {
    if (this.statsStarted) return;
    this.statsStarted = true;

    const targets = this.statTargets();

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      this.statValues.set(targets);
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min((now - start) / STATS_COUNTUP_MS, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      this.statValues.set(targets.map((t) => Math.round(t * eased)));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  formatStat(value: number): string {
    return value.toLocaleString('fr-FR');
  }

  setDisplayMode(mode: 'list' | 'gallery' | 'compact'): void {
    this.displayMode.set(mode);
    localStorage.setItem('laprod_display_mode', mode);
  }

  goToPage(p: number): void {
    this.loadTracks(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  loadTracks(page = 1): void {
    this.page.set(page);
    this.filterStateService.savedPage.set(page);
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
