import { Directive, ElementRef, Input, OnDestroy, OnInit, inject } from '@angular/core';
import { TourService } from '../services/tour.service';

/**
 * Marque un élément comme cible possible d'une visite guidée.
 *
 *   <div lpTourAnchor="cb-progress"> … </div>
 *
 * L'identifiant doit correspondre au champ `anchor` d'une étape de tour-definitions.
 * Poser une ancre est sans effet tant qu'aucune visite ne la référence.
 */
@Directive({
  selector: '[lpTourAnchor]',
  standalone: true,
})
export class TourAnchorDirective implements OnInit, OnDestroy {
  @Input({ required: true, alias: 'lpTourAnchor' }) anchorId!: string;

  private el   = inject(ElementRef<HTMLElement>);
  private tour = inject(TourService);

  ngOnInit(): void {
    this.tour.register(this.anchorId, this.el.nativeElement);
  }

  ngOnDestroy(): void {
    this.tour.unregister(this.anchorId, this.el.nativeElement);
  }
}
