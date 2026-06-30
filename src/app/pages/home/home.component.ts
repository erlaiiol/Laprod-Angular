// ─────────────────────────────────────────────────────────────────────────────
// PAGE HOME
// Rôle : orchestrer. Elle charge les tracks depuis l'API et les distribue
// vers TrackCardComponent. Elle réagit aux filtres posés par Navbar.
// Si l'utilisateur est connecté et n'a pas de filtres actifs → recommandations.
// ─────────────────────────────────────────────────────────────────────────────

import { Component, OnInit, signal, computed, effect, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { switchMap, of } from 'rxjs';

import { TrackService, Track, TrackFilters } from '../../services/track.service';
import { RecommendationService } from '../../services/recommendation.service';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { TagCategoryFilterComponent } from '../../components/tag-category-filter/tag-category-filter.component';
import { OnboardingModalComponent } from '../../components/onboarding-modal/onboarding-modal.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { FilterStateService, ActiveFilters } from '../../services/filter-state.service';
import { ToastService } from '../../services/toast.service';
import { FavoritesService } from '../../services/favorites.service';
import { AuthService } from '../../services/auth.service';

const PER_PAGE = 20;

@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule, RouterModule, TrackCardComponent, TagCategoryFilterComponent, OnboardingModalComponent, PaginationComponent],
  templateUrl: './home.component.html',
  styleUrls:   ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  tracks          = signal<Track[]>([]);
  loading         = signal(true);
  error           = signal<string | null>(null);
  isPersonalized  = signal(false);
  showOnboarding  = signal(false);
  showHero        = signal(false);
  heroTab         = signal<'artiste' | 'beatmaker' | 'ingenieur' | 'producteur'>('artiste');
  displayMode     = signal<'list' | 'gallery'>(
    (localStorage.getItem('laprod_display_mode') as 'list' | 'gallery') ?? 'gallery'
  );

  // Pagination
  page       = signal(1);
  totalPages = signal(1);

  private trackService       = inject(TrackService);
  private recoService        = inject(RecommendationService);
  private filterStateService = inject(FilterStateService);
  private toast              = inject(ToastService);
  private favSvc             = inject(FavoritesService);
  readonly auth              = inject(AuthService);

  private hasActiveFilters = computed(() => {
    const f = this.filterStateService.filters();
    return !!(
      f.search ||
      f.bpmMin !== null ||
      f.bpmMax !== null ||
      f.keys.length > 0 ||
      f.styles.length > 0 ||
      f.tags.length > 0
    );
  });

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
    if (hasRole && OnboardingModalComponent.shouldShow()) {
      localStorage.setItem('laprod_onboarding_done', '1');
      this.showOnboarding.set(true);
    }
  }

  dismissHero(): void {
    this.showHero.set(false);
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

    // Catégorie sélectionnée → toujours paginé, jamais reco (évite les pages vides)
    const useRecommendations = this.auth.isLoggedIn()
      && !this.hasActiveFilters()
      && !this.auth.preferredTagCategory();

    if (useRecommendations) {
      // Les recommandations sont déjà un set curé — pas de pagination
      this.totalPages.set(1);
      this.recoService.getTracks(this.auth.preferredTagCategory()).pipe(
        switchMap(response => {
          if (!response.success) return of(response);
          const ids = response.data.tracks.map(t => t.id);
          return this.favSvc.prefetch(ids).pipe(switchMap(() => of(response)));
        })
      ).subscribe({
        next: (response) => {
          if (response.success) {
            // Moins d'une page complète → catalogue régulier (parité avec mode déconnecté)
            if (response.data.tracks.length < PER_PAGE) {
              this._loadRegularTracks(page);
              return;
            }
            this.tracks.set(response.data.tracks);
            this.isPersonalized.set(response.data.is_personalized);
          } else {
            this.error.set('Le serveur a répondu mais signale une erreur.');
          }
          this.loading.set(false);
        },
        error: () => this._loadRegularTracks(page),
      });
    } else {
      this.isPersonalized.set(false);
      this._loadRegularTracks(page);
    }
  }

  private _loadRegularTracks(page: number): void {
    const apiFilters: TrackFilters = {
      ...this.toTrackFilters(this.filterStateService.filters()),
      page,
      per_page: PER_PAGE,
    };

    this.trackService.getTracks(apiFilters).pipe(
      switchMap(response => {
        if (!response.success || !this.auth.isLoggedIn()) return of(response);
        const ids = (response.data.tracks as Track[]).map(t => t.id);
        return this.favSvc.prefetch(ids).pipe(switchMap(() => of(response)));
      })
    ).subscribe({
      next: (response) => {
        if (response.success) {
          this.tracks.set(response.data.tracks);
          this.totalPages.set(response.data.pagination.pages);
        } else {
          this.error.set('Le serveur a répondu mais signale une erreur.');
        }
        this.loading.set(false);
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
      search:       f.search   || undefined,
      bpm_min:      f.bpmMin   ?? undefined,
      bpm_max:      f.bpmMax   ?? undefined,
      keys:         f.keys.length   ? f.keys.join(',')   : undefined,
      styles:       f.styles.length ? f.styles.join(',') : undefined,
      tags:         f.tags.length   ? f.tags.join(',')   : undefined,
      tag_category: this.auth.preferredTagCategory() ?? undefined,
    };
  }

}
