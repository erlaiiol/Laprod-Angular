import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

import { TagsService, Tag } from '../../services/tags.service';
import { FilterStateService } from '../../services/filter-state.service';
import { AuthService } from '../../services/auth.service';
import { NotificationService } from '../../services/notification.service';
import { SimilarArtistsService, SimilarArtistScene } from '../../services/similar-artists.service';

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

  isBeatmaker   = computed(() => this.authService.isBeatmaker());
  isArtist      = computed(() => this.authService.isArtist());
  isMixEngineer = computed(() => this.authService.isMixEngineer());
  isAdmin       = computed(() => this.authService.isAdmin());
  isPremium     = computed(() => this.authService.isPremium());
  username      = computed(() => this.authService.currentUser()?.username || '');
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
  }

  toggleFilters(): void { this.filtersOpen.set(!this.filtersOpen()); }
  closeFilters():  void { this.filtersOpen.set(false); }
}
