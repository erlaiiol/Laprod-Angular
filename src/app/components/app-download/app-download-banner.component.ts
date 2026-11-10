import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AppDownloadService } from '../../services/app-download.service';
import { StoreLinksComponent } from './store-links.component';

@Component({
  selector: 'app-download-banner',
  imports: [StoreLinksComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!downloads.isNative && !downloads.dismissed()) {
      <aside class="download-banner" aria-label="LaProd sur mobile">
        <div class="download-banner__content">
          <img src="assets/icons/icon-96.webp" width="42" height="42" alt="" class="download-banner__icon">
          <div class="download-banner__copy">
            <strong>Ton prochain morceau commence ici.</strong>
            <span>Emporte LaProd partout. L’app est disponible sur {{ downloads.platform === 'ios' ? 'iPhone et iPad' : downloads.platform === 'android' ? 'Android' : 'iOS et Android' }}.</span>
          </div>
          <app-store-links [compact]="true" [suggested]="true" />
          <button type="button" class="download-banner__close" (click)="downloads.dismiss()" aria-label="Fermer le bandeau de téléchargement">
            <i class="bi bi-x-lg" aria-hidden="true"></i>
          </button>
        </div>
      </aside>
    }
  `,
  styleUrl: './app-download-banner.component.scss',
})
export class AppDownloadBannerComponent {
  readonly downloads = inject(AppDownloadService);
}
