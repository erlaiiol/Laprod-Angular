import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';

/**
 * Barre d'outils du studio, commune au studio web (modale topline-recorder) et
 * au studio de l'app (mobile-studio) : mêmes boutons, mêmes libellés, même
 * ordre. Le parent ne fournit que les états ; aucune logique ici.
 */
@Component({
  selector: 'app-studio-toolbar',
  standalone: true,
  templateUrl: './studio-toolbar.component.html',
  styleUrls: ['./studio-toolbar.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StudioToolbarComponent {
  /** Libellé du bouton d'enregistrement (« Enregistrer », « Nouvelle voix », « Terminer »…). */
  @Input() recordLabel = 'Enregistrer';
  /** Enregistrement en cours : le bouton devient « arrêter » (carré). */
  @Input() recording = false;
  @Input() recordDisabled = false;
  /** Préparation (micro, chargement du beat) : spinner dans le bouton. */
  @Input() recordBusy = false;

  /** Panneau « Micro & monito » ouvert. */
  @Input() settingsActive = false;
  @Input() settingsDisabled = false;

  @Input() publishLabel = 'Publier';
  @Input() publishIcon = 'bi-cloud-arrow-up-fill';
  @Input() publishDisabled = true;

  @Input() downloadDisabled = true;
  @Input() downloadBusy = false;

  @Output() record = new EventEmitter<void>();
  @Output() settings = new EventEmitter<void>();
  @Output() publish = new EventEmitter<void>();
  @Output() download = new EventEmitter<void>();
}
