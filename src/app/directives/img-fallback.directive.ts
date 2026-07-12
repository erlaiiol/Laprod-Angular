// ─────────────────────────────────────────────────────────────────────────────
// DIRECTIVE IMG-FALLBACK
// Remplace le pattern onerror="this.src='...'" — un attribut d'event handler
// inline, silencieusement bloqué par la CSP prod (script-src sans
// 'unsafe-inline', voir nginx/nginx.conf). (error) est un binding Angular
// standard (addEventListener), donc compatible CSP.
//
// Usage : <img [src]="track.image_file" [appImgFallback]="'assets/placeholders/placeholder-track.png'">
// Sans valeur (ou chaîne vide) : masque l'image au lieu de la remplacer
// (ex : logo dans la navbar, pas de variante de repli).
// ─────────────────────────────────────────────────────────────────────────────

import { Directive, HostListener, Input } from '@angular/core';

@Directive({
  selector: 'img[appImgFallback]',
  standalone: true,
})
export class ImgFallbackDirective {

  @Input('appImgFallback') fallbackSrc = '';

  @HostListener('error', ['$event'])
  onError(event: Event): void {
    const img = event.target as HTMLImageElement;
    img.onerror = null;
    if (this.fallbackSrc) {
      img.src = this.fallbackSrc;
    } else {
      img.style.display = 'none';
    }
  }
}
