import { Component, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';

import { TagsService } from '../../services/tags.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-tag-category-filter',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './tag-category-filter.component.html',
  styleUrls: ['./tag-category-filter.component.scss'],
})
export class TagCategoryFilterComponent {
  private tagsService = inject(TagsService);
  private authService = inject(AuthService);

  // Catégories uniques extraites de la liste globale des tags
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

  active = computed(() => this.authService.preferredTagCategory());

  select(name: string | null): void {
    const newValue = this.active() === name ? null : name;  // reclic = désactive
    this.authService.updateTagCategoryPreference(newValue);
  }
}
