import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Boîte de confirmation plein écran (dans `.ms-sheet`) — extrait de
 * MobileStudioComponent, où le même bloc icône + titre + corps + 2 boutons
 * était répété 3× à l'identique (ré-enregistrement, fermeture, upgrade Pro).
 * Pure présentation, aucun état ni décision métier ici.
 */
@Component({
  selector: 'app-mobile-studio-confirm-dialog',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './mobile-studio-confirm-dialog.component.html',
  styleUrls: ['./mobile-studio-confirm-dialog.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MobileStudioConfirmDialogComponent {
  /** Classe glyph Bootstrap Icons SANS le préfixe "bi", ex. "bi-exclamation-triangle". */
  @Input() icon = '';
  @Input() iconGold = false;
  @Input() title = '';
  @Input() body = '';
  @Input() cancelLabel = 'Annuler';
  @Input() okLabel = '';
  /** Classe glyph Bootstrap Icons du bouton OK, ex. "bi-record-circle". */
  @Input() okIcon = '';

  @Output() cancel = new EventEmitter<void>();
  @Output() ok     = new EventEmitter<void>();
}
