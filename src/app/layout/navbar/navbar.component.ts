import { ChangeDetectionStrategy, Component, DestroyRef, HostListener, computed, effect, inject, signal, untracked } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router, RouterModule } from '@angular/router';
import { environment } from '../../../environments/environment';

import { TagsService, Tag } from '../../services/tags.service';
import { FilterStateService } from '../../services/filter-state.service';
import { AuthService } from '../../services/auth.service';
import { NotificationService } from '../../services/notification.service';
import { SimilarArtistsService, SimilarArtistScene } from '../../services/similar-artists.service';
import { ThemeService } from '../../services/theme.service';
import { ImgFallbackDirective } from '../../directives/img-fallback.directive';
import { TourAnchorDirective } from '../../directives/tour-anchor.directive';
import { BetaBadgeComponent } from '../../components/beta-badge/beta-badge.component';
import { TourService } from '../../services/tour.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-navbar',
  standalone: true,
  imports: [CommonModule, RouterModule, ImgFallbackDirective, TourAnchorDirective, BetaBadgeComponent],
  templateUrl: './navbar.component.html',
  styleUrl: './navbar.component.scss',
})
export class NavbarComponent {

  loading = signal(false);
  error   = signal<string | null>(null);

  selectedKeys           = signal<string[]>([]);
  selectedStyles         = signal<string[]>([]);
  selectedTags           = signal<string[]>([]);
  selectedSimilarArtists = signal<string[]>([]);

  search = signal('');
  bpmMin = signal('');
  bpmMax = signal('');

  filtersOpen = signal(false);

  // Menu burger + dropdowns gérés en signals : le CSS Bootstrap
  // (.collapse.show / .dropdown-menu.show) suffit, sans bootstrap.bundle.js.
  menuOpen     = signal(false);
  openDropdown = signal<'contracts' | 'user' | null>(null);

  private tourSvc = inject(TourService);

  // Le guide interactif force l'ouverture du menu mobile le temps de montrer
  // les onglets/le profil, sans toucher à l'intention réelle de l'utilisateur.
  menuVisible = computed(() => this.menuOpen() || this.tourSvc.navbarForceOpen());

  // Tags/gammes/styles/scènes ne sont chargés qu'à la première ouverture du
  // panneau de filtres : un visiteur qui ne filtre jamais ne coûte aucun appel.
  private filterDataRequested = false;

  private notifSvc          = inject(NotificationService);
  private similarArtistsSvc = inject(SimilarArtistsService);
  readonly themeSvc         = inject(ThemeService);

  // L'état vit dans SimilarArtistsService ; la navbar n'en garde pas de copie.
  readonly artistScenes = this.similarArtistsSvc.scenes;

  private router = inject(Router);

  hasActiveFilters = computed(() =>
    this.selectedKeys().length > 0 ||
    this.selectedStyles().length > 0 ||
    this.selectedTags().length > 0 ||
    this.selectedSimilarArtists().length > 0 ||
    !!this.bpmMin() || !!this.bpmMax()
  );

  private authService = inject(AuthService);
  // Presentation only: authentication and route guards update immediately.
  private displayedUser = signal(this.authService.currentUser());
  readonly authMotion = signal<'idle' | 'out' | 'in'>('idle');
  private motionTimer?: ReturnType<typeof setTimeout>;
  private readonly destroyRef = inject(DestroyRef);

  constructor(
    private tagsService:        TagsService,
    private filterStateService: FilterStateService,
  ) {
    effect(() => {
      const user = this.authService.currentUser();
      untracked(() => {
        if (user?.id === this.displayedUser()?.id && this.authMotion() === 'idle') {
          this.displayedUser.set(user);
          return;
        }
        if (this.motionTimer) clearTimeout(this.motionTimer);
        if (typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches) {
          this.displayedUser.set(user);
          this.authMotion.set('idle');
          this.openDropdown.set(null);
          return;
        }
        this.authMotion.set('out');
        this.motionTimer = setTimeout(() => {
          this.displayedUser.set(this.authService.currentUser());
          this.openDropdown.set(null);
          this.authMotion.set('in');
          this.motionTimer = setTimeout(() => this.authMotion.set('idle'), 240);
        }, 180);
      });
    });
    this.destroyRef.onDestroy(() => {
      if (this.motionTimer) clearTimeout(this.motionTimer);
    });
  }

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

  isBeatmaker   = computed(() => !!this.displayedUser()?.roles?.is_beatmaker);
  isArtist      = computed(() => !!this.displayedUser()?.roles?.is_artist);
  isMixEngineer = computed(() => !!this.displayedUser()?.roles?.is_mix_engineer);
  isCertifiedMixEngineer = computed(() => !!this.displayedUser()?.roles?.is_mixmaster_engineer);
  isProducer    = computed(() => !!this.displayedUser()?.roles?.is_producer);
  mixSamplePending = computed(() => this.displayedUser()?.roles?.is_mix_engineer === true && this.displayedUser()?.roles?.mixmaster_sample_submitted === false);
  isAdmin       = computed(() => !!this.displayedUser()?.roles?.is_admin);
  isPremium     = computed(() => !!this.displayedUser()?.is_premium && this.displayedUser()?.subscription_plan !== 'free');
  username      = computed(() => this.displayedUser()?.username || '');
  userInitial   = computed(() => (this.displayedUser()?.username || '?').charAt(0).toUpperCase());

  private readonly staticBase = `${environment.apiUrl}/db_assets/`;

  // null tant que l'utilisateur n'a pas mis de photo perso — le chip d'initiale
  // (nav-avatar) sert alors de fallback, comme sur le reste du site.
  avatarUrl = computed(() => {
    const path = this.displayedUser()?.profile_image;
    if (!path || path === 'images/default_profile.png') return null;
    return path.startsWith('http') ? path : this.staticBase + path;
  });
  notifCount    = computed(() => this.notifSvc.unreadCount());
  isLoggedIn    = computed(() => this.displayedUser() !== null);

  logout(event: Event) {
    event.stopPropagation();
    this.authService.logout().subscribe({
      next:  () => {},
      error: () => {},
    });
  }

  clearLocalStorage() {
    localStorage.clear();
  }

  private ensureFilterData(): void {
    if (this.filterDataRequested) return;
    this.filterDataRequested = true;
    this.loading.set(true);
    this.tagsService.ensureLoaded().subscribe({
      next:  () => this.loading.set(false),
      error: () => {
        this.loading.set(false);
        // Autoriser un retry à la prochaine ouverture du panneau.
        this.filterDataRequested = false;
      },
    });
    this.similarArtistsSvc.ensureLoaded().subscribe({ error: () => {} });
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
    this.menuOpen.set(false);
  }

  toggleMenu(): void {
    const opening = !this.menuOpen();
    this.menuOpen.set(opening);
    // Repartir sur l'onglet "Navigation" à chaque réouverture, plutôt que de
    // rester coincé sur "Mon profil" si c'est là qu'on avait fermé le menu.
    if (!opening) this.openDropdown.set(null);
  }

  toggleDropdown(name: 'contracts' | 'user', event: Event): void {
    event.preventDefault();
    // Sans stopPropagation, le listener document:click refermerait
    // immédiatement le dropdown qu'on vient d'ouvrir.
    event.stopPropagation();
    this.openDropdown.update(current => (current === name ? null : name));
  }

  // Switch mobile "Navigation" / "Mon profil" — contrairement à
  // toggleDropdown (bascule), ici chaque bouton force son propre panneau :
  // un onglet déjà actif ne doit pas se refermer sur un second clic.
  selectMobilePane(pane: 'nav' | 'profile', event: Event): void {
    event.preventDefault();
    event.stopPropagation();
    this.openDropdown.set(pane === 'profile' ? 'user' : null);
  }

  // Clic n'importe où hors du toggle (y compris sur un item du menu) :
  // fermeture, même comportement que l'auto-close Bootstrap.
  @HostListener('document:click')
  onDocumentClick(): void {
    this.openDropdown.set(null);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.openDropdown.set(null);
    this.menuOpen.set(false);
    this.closeFilters();
  }

  // Délégation d'événement sur le menu mobile : on ferme au clic sur tout
  // lien qui navigue réellement (nav-link, dropdown-item) — pas sur les
  // toggles de sous-menu (Contrats, avatar), qui ne font qu'ouvrir un
  // dropdown sans changer de page.
  onNavLinkClick(event: MouseEvent): void {
    const link = (event.target as HTMLElement).closest('a');
    if (link && !link.classList.contains('dropdown-toggle')) {
      this.menuOpen.set(false);
    }
  }

  toggleFilters(): void {
    const opening = !this.filtersOpen();
    if (opening) this.ensureFilterData();
    this.filtersOpen.set(opening);
  }
  closeFilters():  void { this.filtersOpen.set(false); }
}
