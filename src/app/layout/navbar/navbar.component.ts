import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { environment } from '../../../environments/environment';

import { TagsService, Tag } from '../../services/tags.service';
import { FilterStateService } from '../../services/filter-state.service';
import { AuthService } from '../../services/auth.service';
import { NotificationService } from '../../services/notification.service';
import { SimilarArtistsService, SimilarArtistScene } from '../../services/similar-artists.service';
import { ThemeService } from '../../services/theme.service';

@Component({
  selector: 'app-navbar',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './navbar.component.html',
  styleUrl: './navbar.component.scss',
})
export class NavbarComponent implements OnInit {

  loading = signal(true);
  error   = signal<string | null>(null);

  selectedKeys           = signal<string[]>([]);
  selectedStyles         = signal<string[]>([]);
  selectedTags           = signal<string[]>([]);
  selectedSimilarArtists = signal<string[]>([]);

  search = signal('');
  bpmMin = signal('');
  bpmMax = signal('');

  filtersOpen = signal(false);

  artistScenes = signal<SimilarArtistScene[]>([]);

  private notifSvc          = inject(NotificationService);
  private similarArtistsSvc = inject(SimilarArtistsService);
  readonly themeSvc         = inject(ThemeService);

  private router = inject(Router);

  hasActiveFilters = computed(() =>
    this.selectedKeys().length > 0 ||
    this.selectedStyles().length > 0 ||
    this.selectedTags().length > 0 ||
    this.selectedSimilarArtists().length > 0 ||
    !!this.bpmMin() || !!this.bpmMax()
  );

  constructor(
    private tagsService:        TagsService,
    private filterStateService: FilterStateService,
    private authService:        AuthService,
  ) {}

  keys   = computed(() => this.tagsService.keys())
  styles = computed(() => this.tagsService.styles())

  tagGroups = computed<{ name: string; color: string; tags: Tag[] }[]>(() => {
    const map    = new Map<string, { name: string; color: string; tags: Tag[] }>();
    const groups: { name: string; color: string; tags: Tag[] }[] = [];
    for (const tag of this.tagsService.tags()) {
      const key = tag.category.name;
      if (!map.has(key)) {
        const g = { name: key, color: tag.category.color, tags: [] as Tag[] };
        map.set(key, g);
        groups.push(g);
      }
      map.get(key)!.tags.push(tag);
    }
    return groups;
  });

  readonly testimonialsEnabled = environment.testimonialsEnabled;

  isBeatmaker   = computed(() => this.authService.isBeatmaker());
  isArtist      = computed(() => this.authService.isArtist());
  isMixEngineer = computed(() => this.authService.isMixEngineer());
  isAdmin       = computed(() => this.authService.isAdmin());
  isPremium     = computed(() => this.authService.isPremium());
  username      = computed(() => this.authService.currentUser()?.username || '');
  userInitial   = computed(() => (this.authService.currentUser()?.username || '?').charAt(0).toUpperCase());
  notifCount    = computed(() => this.notifSvc.unreadCount());
  isLoggedIn    = computed(() => this.authService.isLoggedIn());

  logout() {
    this.authService.logout().subscribe({
      next:  () => {},
      error: () => {},
    });
  }

  clearLocalStorage() {
    localStorage.clear();
  }

  ngOnInit(): void {
    this.tagsService.loadTags().subscribe({
      next:     () => this.loading.set(false),
      error:    () => this.loading.set(false),
      complete: () => this.loading.set(false),
    });

    this.similarArtistsSvc.getSimilarArtists().subscribe({
      next: (res) => {
        if (res.success) this.artistScenes.set(res.data.scenes);
      },
      error: () => {},
    });
  }

  toggleKey(key: string): void {
    this.selectedKeys.update(arr =>
      arr.includes(key) ? arr.filter(v => v !== key) : [...arr, key]
    );
  }

  toggleStyle(style: string): void {
    this.selectedStyles.update(arr =>
      arr.includes(style) ? arr.filter(v => v !== style) : [...arr, style]
    );
  }

  toggleTag(tag: string): void {
    this.selectedTags.update(arr =>
      arr.includes(tag) ? arr.filter(v => v !== tag) : [...arr, tag]
    );
  }

  toggleArtistFilter(name: string): void {
    this.selectedSimilarArtists.update(arr =>
      arr.includes(name) ? arr.filter(v => v !== name) : [...arr, name]
    );
  }

  isArtistFilterActive(name: string): boolean {
    return this.selectedSimilarArtists().includes(name);
  }

  artistCountInScene(scene: SimilarArtistScene): number {
    return scene.artists.filter(a => this.selectedSimilarArtists().includes(a.name)).length;
  }

  tagCountInGroup(group: { name: string; color: string; tags: Tag[] }): number {
    return group.tags.filter(t => this.selectedTags().includes(t.name)).length;
  }

  applyFilters(): void {
    this.filterStateService.apply({
      search:         this.search(),
      bpmMin:         this.bpmMin()  ? parseInt(this.bpmMin(),  10) : null,
      bpmMax:         this.bpmMax()  ? parseInt(this.bpmMax(),  10) : null,
      keys:           this.selectedKeys(),
      styles:         this.selectedStyles(),
      tags:           this.selectedTags(),
      similarArtists: this.selectedSimilarArtists(),
    });
    this.closeFilters();
    if (this.router.url.split('?')[0] !== '/') {
      this.router.navigate(['/']);
    }
  }

  resetFilters(): void {
    this.search.set('');
    this.bpmMin.set('');
    this.bpmMax.set('');
    this.selectedKeys.set([]);
    this.selectedStyles.set([]);
    this.selectedTags.set([]);
    this.selectedSimilarArtists.set([]);
    this.filterStateService.reset();
    this.closeFilters();
  }

  onSearchEnter(): void {
    this.filterStateService.apply({
      search:         this.search(),
      bpmMin:         this.bpmMin() ? parseInt(this.bpmMin(), 10) : null,
      bpmMax:         this.bpmMax() ? parseInt(this.bpmMax(), 10) : null,
      keys:           this.selectedKeys(),
      styles:         this.selectedStyles(),
      tags:           this.selectedTags(),
      similarArtists: this.selectedSimilarArtists(),
    });
    if (this.router.url.split('?')[0] !== '/') {
      this.router.navigate(['/']);
    }
    this._closeNavbarCollapse();
  }

  private _closeNavbarCollapse(): void {
    const el = document.getElementById('navbarNav');
    if (!el) return;
    const bsCollapse = (window as any).bootstrap?.Collapse?.getInstance(el);
    bsCollapse?.hide();
  }

  // Délégation d'événement sur le menu mobile : Bootstrap ne referme le
  // collapse qu'au clic sur le toggler, pas sur les liens à l'intérieur.
  // On ferme au clic sur tout lien qui navigue réellement (nav-link,
  // dropdown-item) — pas sur les toggles de sous-menu (Contrats, avatar),
  // qui ne font qu'ouvrir un dropdown sans changer de page.
  onNavLinkClick(event: MouseEvent): void {
    const link = (event.target as HTMLElement).closest('a');
    if (link && !link.classList.contains('dropdown-toggle')) {
      this._closeNavbarCollapse();
    }
  }

  toggleFilters(): void { this.filtersOpen.set(!this.filtersOpen()); }
  closeFilters():  void { this.filtersOpen.set(false); }
}
