// ─────────────────────────────────────────────────────────────────────────────
// DIRECTIVE REVEAL-ON-SCROLL
// Pose la classe .lp-reveal (état masqué) puis .is-revealed quand l'élément
// entre dans le viewport — les transitions CSS font le reste (voir styles.scss).
// Respecte prefers-reduced-motion : révélation immédiate, sans animation.
//
// Usage :  <div lpReveal [lpRevealDelay]="120" (revealed)="onVisible()">
// ─────────────────────────────────────────────────────────────────────────────

import { Directive, ElementRef, EventEmitter, Input, OnDestroy, OnInit, Output, inject } from '@angular/core';

@Directive({
  selector: '[lpReveal]',
  standalone: true,
})
export class RevealOnScrollDirective implements OnInit, OnDestroy {

  /** Délai (ms) avant la transition — pour décaler des éléments voisins. */
  @Input() lpRevealDelay = 0;

  /** Émis une seule fois, quand l'élément devient visible. */
  @Output() revealed = new EventEmitter<void>();

  private el = inject<ElementRef<HTMLElement>>(ElementRef);
  private observer?: IntersectionObserver;

  ngOnInit(): void {
    const node = this.el.nativeElement;
    node.classList.add('lp-reveal');

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reducedMotion || !('IntersectionObserver' in window)) {
      node.classList.add('is-revealed');
      this.revealed.emit();
      return;
    }

    if (this.lpRevealDelay > 0) {
      node.style.transitionDelay = `${this.lpRevealDelay}ms`;
    }

    this.observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          node.classList.add('is-revealed');
          this.revealed.emit();
          this.observer?.disconnect();
          this.observer = undefined;
        }
      },
      { threshold: 0.15 },
    );
    this.observer.observe(node);
  }

  ngOnDestroy(): void {
    this.observer?.disconnect();
  }
}
