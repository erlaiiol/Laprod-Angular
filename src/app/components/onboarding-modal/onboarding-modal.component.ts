import { Component, output, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { TagsService } from '../../services/tags.service';
import { AuthService } from '../../services/auth.service';

const STORAGE_KEY = 'laprod_onboarding_done';

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

  categories  = this.tagsService.categories;
  selected    = signal<string | null>(null);

  select(name: string): void {
    this.selected.set(this.selected() === name ? null : name);
  }

  confirm(): void {
    if (this.selected()) {
      this.authService.updateTagCategoryPreference(this.selected());
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
