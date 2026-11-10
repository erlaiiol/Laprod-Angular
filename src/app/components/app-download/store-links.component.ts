import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { AppDownloadService } from '../../services/app-download.service';
import { StoreIconComponent } from './store-icon.component';

@Component({
  selector: 'app-store-links',
  imports: [StoreIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!downloads.isNative) {
      <div class="store-links" [class.store-links--compact]="compact()" role="group" aria-label="Télécharger l’application LaProd">
        @for (store of (suggested() ? downloads.suggestedStores : downloads.stores); track store.platform) {
          <a class="store-link" [href]="store.url" target="_blank" rel="noopener noreferrer"
             [attr.aria-label]="'Télécharger LaProd sur ' + store.name + ' (nouvel onglet)'">
            <app-store-icon [platform]="store.platform" />
            <span class="store-link__label">
              @if (!compact()) { <span class="store-link__hint">{{ store.hint }}</span> }
              <span class="store-link__name">{{ store.name }}</span>
            </span>
            @if (compact()) { <i class="bi bi-arrow-up-right" aria-hidden="true"></i> }
          </a>
        }
      </div>
    }
  `,
  styleUrl: './store-links.component.scss',
})
export class StoreLinksComponent {
  readonly downloads = inject(AppDownloadService);
  readonly compact = input(false);
  readonly suggested = input(false);
}
