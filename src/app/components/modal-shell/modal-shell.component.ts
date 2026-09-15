import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Coquille de modale générique : backdrop plein écran (flou + dim + centrage)
 * + clic-en-dehors-pour-fermer. Le CONTENU (carte, header, footer…) reste
 * entièrement à la charge de l'appelant via `<ng-content>` — cette coquille
 * ne standardise QUE ce qui était strictement dupliqué à l'identique entre
 * les modales admin (contract-builder, contracts, tracks, users) et celle du
 * contract-builder (`.bf-preview-*`). Volontairement PAS utilisée pour les
 * confirmations plein-écran de mobile-studio (`.ms-confirm-overlay`,
 * `.daw-guest-gate`) : positionnement (absolute dans son propre conteneur,
 * pas fixed) et échelle de z-index différentes — les forcer dans la même
 * coquille aurait été le genre de cas particulier sur infrastructure
 * partagée qu'on veut éviter, pas une vraie unification.
 */
@Component({
  selector: 'app-modal-shell',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './modal-shell.component.html',
  styleUrls: ['./modal-shell.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModalShellComponent {
  /** Marge autour de la carte sur grand écran (ex. builder-form : "2.5rem 1.5rem"). */
  @Input() padding = '0';
  /** Repasse `padding` à 0 sous 700px — pour une carte qui devient plein écran
   *  en mobile (ex. builder-form : sa propre règle @media met déjà max-width:none
   *  + height:100% sur la carte, une marge de backdrop la contredirait). */
  @Input() mobileFlush = false;
  /** Fondu d'entrée du backdrop — off par défaut (comportement historique des modales admin). */
  @Input() fadeIn = false;

  @Output() backdropClick = new EventEmitter<void>();
}
