import { Component, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Overlay "connexion requise" affiché à un invité qui tente de publier sa
 * maquette — extrait de MobileStudioComponent. Statique, sans état propre :
 * chaque action reste décidée par le parent via les @Output.
 */
@Component({
  selector: 'app-daw-guest-gate-overlay',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './daw-guest-gate-overlay.component.html',
  styleUrls: ['../mobile-studio-shared.scss', './daw-guest-gate-overlay.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DawGuestGateOverlayComponent {
  @Output() login = new EventEmitter<void>();
  @Output() downloadLocal = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();
}
