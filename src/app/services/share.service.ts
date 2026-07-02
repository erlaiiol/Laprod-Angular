import { Injectable, inject } from '@angular/core';
import { ToastService } from './toast.service';

@Injectable({ providedIn: 'root' })
export class ShareService {
  private toast = inject(ToastService);

  async share(url: string, title?: string): Promise<void> {
    const absoluteUrl = url.startsWith('http')
      ? url
      : `${window.location.origin}${url}`;

    if (navigator.share) {
      try {
        await navigator.share({ title, url: absoluteUrl });
      } catch (err: any) {
        if (err?.name !== 'AbortError') {
          await this.copyToClipboard(absoluteUrl);
        }
      }
    } else {
      await this.copyToClipboard(absoluteUrl);
    }
  }

  private async copyToClipboard(url: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(url);
      this.toast.showToast({ level: 'success', message: 'Lien copié dans le presse-papiers !' });
    } catch {
      this.toast.showToast({ level: 'error', message: 'Impossible de copier le lien.' });
    }
  }
}
