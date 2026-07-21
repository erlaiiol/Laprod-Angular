import {
  AfterViewInit, ChangeDetectionStrategy, Component, ElementRef,
  OnDestroy, output, viewChild,
} from '@angular/core';
import { environment } from '../../../environments/environment';

// API globale injectée par le script Turnstile.
declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string;
      reset: (id: string) => void;
      remove: (id: string) => void;
    };
  }
}

const SCRIPT_SRC = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
let _scriptPromise: Promise<void> | null = null;

/**
 * Widget CAPTCHA Cloudflare Turnstile.
 *
 * À n'afficher que sur le web quand une site key est configurée
 * (`TurnstileComponent.isEnabled`). Émet le token via `(token)` — `null` quand le
 * défi expire ou échoue. Le parent conditionne son bouton d'envoi sur ce token.
 */
@Component({
  selector: 'app-turnstile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<div #host></div>`,
})
export class TurnstileComponent implements AfterViewInit, OnDestroy {

  /** CAPTCHA actif : web (non natif) + site key renseignée. */
  static readonly isEnabled = !environment.isNative && !!environment.turnstileSiteKey;

  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  readonly token = output<string | null>();

  private widgetId: string | null = null;

  async ngAfterViewInit(): Promise<void> {
    if (!TurnstileComponent.isEnabled) return;
    try {
      await this.loadScript();
      this.widgetId = window.turnstile!.render(this.host().nativeElement, {
        sitekey: environment.turnstileSiteKey,
        callback: (t: string) => this.token.emit(t),
        'expired-callback': () => this.token.emit(null),
        'error-callback': () => this.token.emit(null),
      });
    } catch {
      // Script injoignable : on n'émet aucun token (le parent restera bloqué),
      // mais on ne casse pas la page.
    }
  }

  /** Réinitialise le défi (à appeler après un échec serveur pour rejouer). */
  reset(): void {
    if (this.widgetId && window.turnstile) {
      window.turnstile.reset(this.widgetId);
      this.token.emit(null);
    }
  }

  ngOnDestroy(): void {
    if (this.widgetId && window.turnstile) {
      window.turnstile.remove(this.widgetId);
    }
  }

  private loadScript(): Promise<void> {
    if (window.turnstile) return Promise.resolve();
    if (_scriptPromise) return _scriptPromise;
    _scriptPromise = new Promise<void>((resolve, reject) => {
      const s = document.createElement('script');
      s.src = SCRIPT_SRC;
      s.async = true;
      s.defer = true;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error('Turnstile script load failed'));
      document.head.appendChild(s);
    });
    return _scriptPromise;
  }
}
