import { Component, computed, output, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TagsService } from '../../services/tags.service';
import { AuthService } from '../../services/auth.service';

const STORAGE_KEY      = 'laprod_onboarding_done';
const ARTISTS_SENTINEL = '__artists__';

@Component({
  selector: 'app-onboarding-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './onboarding-modal.component.html',
  styleUrl: './onboarding-modal.component.scss',
})
export class OnboardingModalComponent {
  closed = output<void>();

  private tagsService = inject(TagsService);
  private authService = inject(AuthService);

  private readonly artistsEntry = {
    name: ARTISTS_SENTINEL,
    label: 'Artistes similaires',
    color: '#6c757d',
    description: '"type" beat, comme youtube',
  };

  options = computed(() => [
    ...this.tagsService.categories().map(c => ({ ...c, label: c.name })),
    this.artistsEntry,
  ]);

  selected = signal<string | null>(null);

  select(name: string): void {
    this.selected.set(this.selected() === name ? null : name);
  }

  confirm(): void {
    const sel = this.selected();
    if (sel === ARTISTS_SENTINEL) {
      this.authService.setCardInfoMode('artists');
      this.authService.updateTagCategoryPreference(null);
    } else if (sel) {
      this.authService.setCardInfoMode('tags');
      this.authService.updateTagCategoryPreference(sel);
    }
    localStorage.setItem(STORAGE_KEY, '1');
    this.closed.emit();
  }

  skip(): void {
    localStorage.setItem(STORAGE_KEY, '1');
    this.closed.emit();
  }

  static shouldShow(): boolean {
    return !localStorage.getItem(STORAGE_KEY);
  }
}
