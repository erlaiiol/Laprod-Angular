// ─────────────────────────────────────────────────────────────────────────────
// COMPOSANT DE LAYOUT : Navbar
// Rôle : barre de navigation globale, toujours présente (app.html).
// Charge les tags/keys/styles via TagsService.
// Écrit les filtres sélectionnés dans FilterStateService → Home recharge.
// ─────────────────────────────────────────────────────────────────────────────

import { Component, computed, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

import { TagsService, Tag } from '../../services/tags.service';
import { FilterStateService } from '../../services/filter-state.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-navbar',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './navbar.component.html',
  styleUrl: './navbar.component.scss',
})
export class NavbarComponent implements OnInit {

  // ── Données de filtres (chargées depuis /filters/tags/all) ───────────────

  tags    = signal<Tag[]>([]);
  keys    = signal<string[]>([]);
  styles  = signal<string[]>([]);
  loading = signal(true);
  error   = signal<string | null>(null);

  // ── Sélections "en cours" dans le popover ─────────────────────────────────
  // Ces signaux sont LOCAUX à la navbar — ils ne sont poussés vers
  // FilterStateService qu'au clic sur "Appliquer".
  // (Même comportement que filters.js : sélection ≠ application)

  selectedKeys   = signal<string[]>([]);
  selectedStyles = signal<string[]>([]);
  selectedTags   = signal<string[]>([]);

  // ── Champs texte du popover / barre de recherche ──────────────────────────

  search = signal('');
  bpmMin = signal('');
  bpmMax = signal('');

  // ── Auth (placeholder — à connecter avec un AuthService) ─────────────────



  // ── État du popover ───────────────────────────────────────────────────────

  filtersOpen = signal(false);

  constructor(
    private tagsService:      TagsService,
    private filterStateService: FilterStateService,
    private authService: AuthService,
    // FilterStateService est injecté ici pour écrire les filtres appliqués.
    // Home l'injecte lui aussi pour les lire — c'est le canal de communication.
  ) {}

  isBeatmaker   = computed(() => this.authService.isBeatmaker());
  isArtist      = computed(() => this.authService.isArtist());
  isMixEngineer = computed(() => this.authService.isMixEngineer());
  isAdmin       = computed(() => this.authService.isAdmin());
  username      = computed(() => this.authService.currentUser()?.username || '');
  notifCount    = computed(() => this.authService.currentUser()?.notif_count || 0);



  // Encapsuler le login pour le redistribuer dans le HTML malgré authService private
  isLoggedIn = computed(() => this.authService.isLoggedIn())

  logout() {
    this.authService.logout().subscribe({
      next: () => {
        console.log('déconnexion réussie')
      },
      error: (err) =>{
        console.error('erreur logout', err)
      }
    });
  }

  // =====================================
  // DEBUG ONY
  // =====================================
  clearLocalStorage(){
    console.log(localStorage)
    localStorage.clear()
  }
  // =====================================



  ngOnInit(): void {
    this.loadTags();
    console.log(this.isLoggedIn())
  }

  loadTags(): void {
    this.loading.set(true);
    this.error.set(null);

    this.tagsService.getTags().subscribe({
      next: (response) => {
        if (response.success) {
          this.tags.set(response.data.tags);
          this.keys.set(response.data.keys);
          this.styles.set(response.data.styles);
        } else {
          this.error.set('Erreur chargement des filtres');
        }
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de charger les filtres');
        this.loading.set(false);
      }
    });
  }

  // ── Toggle d'une valeur dans un tableau de sélection ─────────────────────
  // signal.update(fn) : lit la valeur actuelle, applique fn, écrit le résultat.
  // [...arr, val] : nouvel tableau (immuable) — Angular détecte le changement.
  // arr.filter(v => v !== val) : retire la valeur sans muter le tableau.

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

  // ── Application des filtres ───────────────────────────────────────────────
  // Pousse l'état local vers FilterStateService → Home le reçoit via effect().
  // Même logique que applyFiltersAndReload() de filters.js — mais sans
  // rechargement de page (SPA).

  applyFilters(): void {
    this.filterStateService.apply({
      search:  this.search(),
      bpmMin:  this.bpmMin()  ? parseInt(this.bpmMin(),  10) : null,
      bpmMax:  this.bpmMax()  ? parseInt(this.bpmMax(),  10) : null,
      keys:    this.selectedKeys(),
      styles:  this.selectedStyles(),
      tags:    this.selectedTags(),
    });
    this.closeFilters();
  }

  // Même logique que resetFilters() de filters.js.
  resetFilters(): void {
    this.search.set('');
    this.bpmMin.set('');
    this.bpmMax.set('');
    this.selectedKeys.set([]);
    this.selectedStyles.set([]);
    this.selectedTags.set([]);
    this.filterStateService.reset();
    this.closeFilters();
  }

  // Recherche via la barre (Entrée) — applique immédiatement sans ouvrir le popover.
  onSearchEnter(): void {
    this.filterStateService.apply({
      search:  this.search(),
      bpmMin:  this.bpmMin() ? parseInt(this.bpmMin(), 10) : null,
      bpmMax:  this.bpmMax() ? parseInt(this.bpmMax(), 10) : null,
      keys:    this.selectedKeys(),
      styles:  this.selectedStyles(),
      tags:    this.selectedTags(),
    });
  }

  // ── Contrôle du popover ───────────────────────────────────────────────────

  toggleFilters(): void { this.filtersOpen.set(!this.filtersOpen()); }
  closeFilters():  void { this.filtersOpen.set(false); }

}
