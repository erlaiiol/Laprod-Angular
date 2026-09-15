import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ContractParty } from '../../../../services/contract-builder.service';
import { PreviewGroup } from '../builder-form.component';

/**
 * Corps de la modale de prévisualisation plein écran — extrait de
 * BuilderFormComponent. Pure présentation : `groups` est déjà entièrement
 * calculé par le parent (valeurs formatées, numérotation) — voir
 * `BuilderFormComponent.previewGroups`.
 */
@Component({
  selector: 'app-contract-preview',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './contract-preview.component.html',
  styleUrls: ['./contract-preview.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ContractPreviewComponent {
  @Input() title = '';
  @Input() parties: ContractParty[] = [];
  @Input() groups: PreviewGroup[] = [];

  @Output() close = new EventEmitter<void>();
}
