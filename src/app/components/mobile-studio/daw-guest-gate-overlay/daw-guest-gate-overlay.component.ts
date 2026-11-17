import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Overlay "connexion requise" affiché à un invité — par défaut pour la
 * publication d'une maquette, réutilisé (textes en @Input) pour le réglage des
 * effets. Sans état propre : chaque action reste décidée par le parent.
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
  @Input() title = 'Connexion requise';
  @Input() body  = 'Créez un compte gratuit pour publier votre maquette et la partager avec des beatmakers.';
  @Input() showDownload  = true;
  @Input() downloadLabel = 'Télécharger sans compte';

  @Output() login = new EventEmitter<void>();
  @Output() downloadLocal = new EventEmitter<void>();
  @Output() cancel = new EventEmitter<void>();
}
