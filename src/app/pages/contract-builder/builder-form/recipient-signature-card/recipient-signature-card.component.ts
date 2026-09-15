import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ContractParty } from '../../../../services/contract-builder.service';

/**
 * Bloc affiché à une partie invitée à signer ("bf-signature-card") — extrait
 * de BuilderFormComponent. Ne vit que pour isRecipient() ; toute action
 * (signer/décliner) reste gérée par le parent via les @Output.
 */
@Component({
  selector: 'app-recipient-signature-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './recipient-signature-card.component.html',
  styleUrls: ['../builder-form-shared.scss', './recipient-signature-card.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RecipientSignatureCardComponent {
  @Input() myInviteStatus: string = 'none';
  @Input() myParty: ContractParty | null = null;
  @Input() signatureName = '';
  @Input() signatureConsent = false;
  @Input() signing = false;
  @Input() declining = false;

  @Output() signatureNameChange = new EventEmitter<string>();
  @Output() signatureConsentChange = new EventEmitter<boolean>();
  @Output() submitSignature = new EventEmitter<void>();
  @Output() declineSignature = new EventEmitter<void>();
}
