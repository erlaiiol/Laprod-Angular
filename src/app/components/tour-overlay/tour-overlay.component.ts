import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy, Component, HostListener, OnDestroy,
  computed, effect, inject, signal,
} from '@angular/core';
import { TourService } from '../../services/tour.service';
import { TourPlacement } from '../../tours/tour-definitions';

interface Box { top: number; left: number; width: number; height: number; }

const PADDING     = 8;    // marge du halo autour de l'élément mis en avant
const BUBBLE_W    = 320;
const BUBBLE_GAP  = 14;   // distance entre l'élément et la bulle
const VIEWPORT_M  = 12;   // marge minimale avec le bord de l'écran

@Component({
  selector: 'app-tour-overlay',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './tour-overlay.component.html',
  styleUrl: './tour-overlay.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TourOverlayComponent implements OnDestroy {

  readonly tour = inject(TourService);

  /** Position de l'élément ciblé, en coordonnées viewport. */
  readonly box = signal<Box | null>(null);

  private scrollTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      const step = this.tour.currentStep();
      if (!step) {
        this.box.set(null);
        document.body.style.overflow = '';
        return;
      }

      const el = this.tour.anchorEl(step.anchor);
      if (!el) {
        this.box.set(null);
        return;
      }

      // On amène l'élément au centre avant de mesurer : sans ça, le halo se
      // dessinerait à la position d'avant-défilement.
      el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'smooth' });

      if (this.scrollTimer) clearTimeout(this.scrollTimer);
      this.scrollTimer = setTimeout(() => this.measure(), 340);
    });
  }

  private measure(): void {
    const step = this.tour.currentStep();
    if (!step) return;
    const el = this.tour.anchorEl(step.anchor);
    if (!el) { this.box.set(null); return; }

    const r = el.getBoundingClientRect();
    this.box.set({
      top:    r.top    - PADDING,
      left:   r.left   - PADDING,
      width:  r.width  + PADDING * 2,
      height: r.height + PADDING * 2,
    });
  }

  @HostListener('window:resize')
  @HostListener('window:scroll')
  onViewportChange(): void {
    if (this.tour.isOpen()) this.measure();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.tour.isOpen()) this.tour.finish();
  }

  @HostListener('document:keydown.arrowright')
  onNext(): void {
    if (this.tour.isOpen()) this.tour.next();
  }

  @HostListener('document:keydown.arrowleft')
  onPrev(): void {
    if (this.tour.isOpen()) this.tour.prev();
  }

  /**
   * Place la bulle du côté demandé, en basculant automatiquement si la place manque.
   * Le résultat est borné au viewport : la bulle ne sort jamais de l'écran.
   */
  readonly bubbleStyle = computed<Record<string, string>>(() => {
    const b = this.box();
    const step = this.tour.currentStep();
    if (!b || !step) return { display: 'none' };

    const vw = window.innerWidth;
    const vh = window.innerHeight;

    // Sur petit écran, la bulle s'ancre en bas : pas de place pour la coller à côté.
    if (vw < 620) {
      return {
        left: `${VIEWPORT_M}px`,
        right: `${VIEWPORT_M}px`,
        bottom: `${VIEWPORT_M}px`,
        width: 'auto',
      };
    }

    const placement = this.resolvePlacement(b, step.placement ?? 'bottom', vw, vh);
    const style: Record<string, string> = { width: `${BUBBLE_W}px` };

    if (placement === 'bottom' || placement === 'top') {
      const left = this.clamp(
        b.left + b.width / 2 - BUBBLE_W / 2,
        VIEWPORT_M,
        vw - BUBBLE_W - VIEWPORT_M,
      );
      style['left'] = `${left}px`;
      if (placement === 'bottom') style['top'] = `${b.top + b.height + BUBBLE_GAP}px`;
      else                        style['bottom'] = `${vh - b.top + BUBBLE_GAP}px`;
    } else {
      const top = this.clamp(b.top, VIEWPORT_M, vh - 200 - VIEWPORT_M);
      style['top'] = `${top}px`;
      if (placement === 'right') style['left'] = `${b.left + b.width + BUBBLE_GAP}px`;
      else                       style['right'] = `${vw - b.left + BUBBLE_GAP}px`;
    }

    return style;
  });

  private resolvePlacement(b: Box, wanted: TourPlacement, vw: number, vh: number): TourPlacement {
    const space = {
      bottom: vh - (b.top + b.height),
      top:    b.top,
      right:  vw - (b.left + b.width),
      left:   b.left,
    };
    const need = { bottom: 220, top: 220, right: BUBBLE_W + BUBBLE_GAP, left: BUBBLE_W + BUBBLE_GAP };

    if (space[wanted] >= need[wanted]) return wanted;

    // Repli : on prend le premier côté qui tient, sinon le plus spacieux.
    const order: TourPlacement[] = ['bottom', 'top', 'right', 'left'];
    return order.find(p => space[p] >= need[p])
        ?? order.reduce((a, p) => (space[p] > space[a] ? p : a), 'bottom' as TourPlacement);
  }

  private clamp(v: number, min: number, max: number): number {
    return Math.max(min, Math.min(v, Math.max(min, max)));
  }

  /** Le clic sur le fond termine la visite (comportement attendu d'un coach-mark). */
  onBackdropClick(): void {
    this.tour.finish();
  }

  ngOnDestroy(): void {
    if (this.scrollTimer) clearTimeout(this.scrollTimer);
    document.body.style.overflow = '';
  }
}
