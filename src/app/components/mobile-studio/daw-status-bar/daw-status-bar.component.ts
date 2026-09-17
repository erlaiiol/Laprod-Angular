import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Barre d'état en tête de la vue idle du mini DAW — extrait de
 * MobileStudioComponent. Pure présentation : le choix stop/preview reste
 * décidé par le parent (togglePreview), qui connaît isPlayingPreview.
 */
@Component({
  selector: 'app-daw-status-bar',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './daw-status-bar.component.html',
  styleUrls: ['./daw-status-bar.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DawStatusBarComponent {
  @Input() hasTrack = false;
  @Input() trackCount = 0;
  @Input() hasExtendedBeat = false;
  @Input() isPlayingPreview = false;

  @Output() togglePreview = new EventEmitter<void>();
}
