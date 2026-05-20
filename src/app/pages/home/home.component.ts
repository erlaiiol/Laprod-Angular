// ─────────────────────────────────────────────────────────────────────────────
// PAGE HOME
// Rôle : orchestrer. Elle charge les tracks depuis l'API et les distribue
// vers TrackCardComponent. Elle réagit aux filtres posés par Navbar.
// Si l'utilisateur est connecté et n'a pas de filtres actifs → recommandations.
// ─────────────────────────────────────────────────────────────────────────────

import { Component, OnInit, signal, computed, effect, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { switchMap, of } from 'rxjs';

import { TrackService, Track, TrackFilters } from '../../services/track.service';
import { RecommendationService } from '../../services/recommendation.service';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { TagCategoryFilterComponent } from '../../components/tag-category-filter/tag-category-filter.component';
import { FilterStateService, ActiveFilters } from '../../services/filter-state.service';
import { ToastService } from '../../services/toast.service';
import { FavoritesService } from '../../services/favorites.service';
import { AuthService } from '../../services/auth.service';


@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule, TrackCardComponent, TagCategoryFilterComponent],
  templateUrl: './home.component.html',
  styleUrls:   ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  tracks          = signal<Track[]>([]);
  loading         = signal(true);
  error           = signal<string | null>(null);
  isPersonalized  = signal(false);

  private trackService       = inject(TrackService);
  private recoService        = inject(RecommendationService);
  private filterStateService = inject(FilterStateService);
  private toast              = inject(ToastService);
  private favSvc             = inject(FavoritesService);
  private auth               = inject(AuthService);

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
    effect(() => {
      this.filterStateService.applied(); // lecture → crée la dépendance
      this.loadTracks();
    }, { allowSignalWrites: true });
  }

  ngOnInit(): void {}

  loadTracks(): void {
    this.loading.set(true);
    this.error.set(null);

    const useRecommendations = this.auth.isLoggedIn() && !this.hasActiveFilters();

    if (useRecommendations) {
      this.recoService.getTracks().pipe(
        switchMap(response => {
          if (!response.success) return of(response);
          const ids = response.data.tracks.map(t => t.id);
          return this.favSvc.prefetch(ids).pipe(
            switchMap(() => of(response)),
          );
        })
      ).subscribe({
        next: (response) => {
          if (response.success) {
            this.tracks.set(response.data.tracks);
            this.isPersonalized.set(response.data.is_personalized);
          } else {
            this.error.set('Le serveur a répondu mais signale une erreur.');
          }
          this.loading.set(false);
        },
        error: () => {
          // Fallback silencieux vers les tracks normaux en cas d'erreur reco
          this._loadRegularTracks();
        }
      });
    } else {
      this.isPersonalized.set(false);
      this._loadRegularTracks();
    }
  }

  private _loadRegularTracks(): void {
    const apiFilters = this.toTrackFilters(this.filterStateService.filters());

    this.trackService.getTracks(apiFilters).pipe(
      switchMap(response => {
        if (!response.success || !this.auth.isLoggedIn()) return of(response);
        const ids = (response.data.tracks as Track[]).map(t => t.id);
        return this.favSvc.prefetch(ids).pipe(
          switchMap(() => of(response)),
        );
      })
    ).subscribe({
      next: (response) => {
        if (response.success) {
          this.tracks.set(response.data.tracks);
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

  // ── Conversion de format ──────────────────────────────────────────────────
  private toTrackFilters(f: ActiveFilters): TrackFilters {
    return {
      search:   f.search   || undefined,
      bpm_min:  f.bpmMin   ?? undefined,
      bpm_max:  f.bpmMax   ?? undefined,
      keys:     f.keys.length   ? f.keys.join(',')   : undefined,
      styles:   f.styles.length ? f.styles.join(',') : undefined,
      tags:     f.tags.length   ? f.tags.join(',')   : undefined,
    };
  }

}
