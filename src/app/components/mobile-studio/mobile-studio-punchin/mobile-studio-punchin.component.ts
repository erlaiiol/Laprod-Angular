import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { VocalTrack } from '../../../services/mobile-maquette.service';
import { formatTimer } from '../../../utils/waveform.utils';

/**
 * Écran "Corriger un passage" (sélecteur de point de punch-in) — extrait de
 * MobileStudioComponent (état `studioState() === 'punch-in'`). Pure
 * présentation : la logique de punch-in (calcul du point, lecture, démarrage
 * de l'enregistrement) reste dans le parent.
 */
@Component({
  selector: 'app-mobile-studio-punchin',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './mobile-studio-punchin.component.html',
  styleUrls: ['../mobile-studio-shared.scss', './mobile-studio-punchin.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MobileStudioPunchinComponent {
  @Input() track: VocalTrack | null = null;
  @Input() sec = 0;

  @Output() secChange = new EventEmitter<number>();
  @Output() preview    = new EventEmitter<void>();
  @Output() confirm    = new EventEmitter<void>();
  @Output() cancel      = new EventEmitter<void>();

  readonly formatTimer = formatTimer;

  onSliderInput(event: Event): void {
    this.secChange.emit(+(event.target as HTMLInputElement).value);
  }
}
