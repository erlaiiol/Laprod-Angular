import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { CommonModule } from '@angular/common';

import { TagsService } from '../../services/tags.service';
import { AuthService } from '../../services/auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-tag-category-filter',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './tag-category-filter.component.html',
  styleUrls: ['./tag-category-filter.component.scss'],
})
export class TagCategoryFilterComponent {
  private tagsService = inject(TagsService);
  private authService = inject(AuthService);

  // La vue compacte masque tags et artistes similaires sur les track-cards
  // (track-card.component.scss : .track-card--compact .track-info { display: none })
  // → ce filtre n'a alors plus aucun effet visible, on l'indique au lieu de
  // laisser des boutons cliquables qui ne font rien.
  compact = input(false);

  constructor() {
    // Le composant est responsable de ses données : requête partagée/cachée,
    // gratuite si un autre consommateur a déjà chargé les tags.
    this.tagsService.ensureLoaded().subscribe({ error: () => {} });
  }

  categories = computed(() => {
    const seen = new Set<string>();
    const result: { name: string; color: string }[] = [];
    for (const tag of this.tagsService.tags()) {
      if (!seen.has(tag.category.name)) {
        seen.add(tag.category.name);
        result.push({ name: tag.category.name, color: tag.category.color });
      }
    }
    return result;
  });

  activeCategory  = computed(() => this.authService.preferredTagCategory());
  artistsModeOn   = computed(() => this.authService.preferredCardInfoMode() === 'artists');

  selectCategory(name: string | null): void {
    // Reclic sur la même catégorie → désactive
    const newValue = this.activeCategory() === name ? null : name;
    this.authService.setCardInfoMode('tags');
    this.authService.updateTagCategoryPreference(newValue);
  }

  toggleArtistsMode(): void {
    if (this.artistsModeOn()) {
      // Reclic → retour aux tags
      this.authService.setCardInfoMode('tags');
    } else {
      this.authService.setCardInfoMode('artists');
      this.authService.updateTagCategoryPreference(null);
    }
  }
}
