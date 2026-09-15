import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ClauseDTO } from '../../../../services/contract-builder.service';
import { LocalValue } from '../builder-form.component';

/**
 * Une clause du contrat — extrait de BuilderFormComponent (bloc répété dans
 * @for (clause of activeGroupData()!.clauses; ...)). Pure présentation :
 * toute mutation (patch, résolution de variable, activation...) est déléguée
 * au parent via les @Output ci-dessous, qui appelle exactement les mêmes
 * méthodes qu'avant (patchField, resolveOneBracket, useExample...) — rien de
 * cette logique n'a bougé ni été dupliqué.
 *
 * Deux petits calculs SONT dupliqués ici volontairement, parce qu'ils sont
 * triviaux et purs, dérivables uniquement des @Input déjà reçus (`lv`,
 * `introVarMap`) — les reproduire évite un aller-retour de callback pour un
 * simple lookup/includes :
 *   - isSelected(opt)     ≡ BuilderFormComponent.isMultiSelected()
 *   - resolveVariable(br) ≡ BuilderFormComponent.resolveVariable()
 * Tout le reste (isFilled, clauseNum, brackets détectés...) est calculé UNE
 * FOIS par le parent et transmis en @Input — zéro logique dupliquée.
 */
@Component({
  selector: 'app-contract-clause',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './contract-clause.component.html',
  styleUrls: ['../builder-form-shared.scss', './contract-clause.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ContractClauseComponent {
  @Input({ required: true }) clause!: ClauseDTO;
  @Input({ required: true }) lv!: LocalValue;
  @Input() isFilled = false;
  @Input() clauseNum: string | undefined = undefined;
  @Input() readOnly = false;
  @Input() isFinal = false;
  @Input() tooltipExpanded = false;
  @Input() exampleExpanded = false;
  /** Brackets [xxx] détectés dans le texte de CETTE clause (déjà calculé par le parent). */
  @Input() brackets: string[] = [];
  @Input() introVarMap: Record<string, string> = {};
  @Input() hasAnyIntroVar = false;
  @Input() definedIntroVars: { key: string; value: string }[] = [];

  @Output() enabledChange      = new EventEmitter<boolean>();
  @Output() toggleTooltip      = new EventEmitter<void>();
  @Output() toggleExample      = new EventEmitter<void>();
  @Output() useExample         = new EventEmitter<void>();
  @Output() patch              = new EventEmitter<{ field: string; value: any }>();
  @Output() resolveOneBracket  = new EventEmitter<string>();
  @Output() resolveAllBrackets = new EventEmitter<void>();
  @Output() insertValue        = new EventEmitter<string>();
  @Output() toggleMulti        = new EventEmitter<string>();

  onEnabledChange(event: Event): void {
    this.enabledChange.emit((event.target as HTMLInputElement).checked);
  }

  onPatch(field: string, value: any): void {
    this.patch.emit({ field, value });
  }

  /** ≡ BuilderFormComponent.isMultiSelected() — dérivable de `lv` seul, voir le commentaire de tête. */
  isSelected(opt: string): boolean {
    return (this.lv.value?.selected ?? []).includes(opt);
  }

  /** ≡ BuilderFormComponent.resolveVariable() — dérivable de `introVarMap` seul. */
  resolveVariable(bracket: string): string {
    return this.introVarMap[bracket] ?? '';
  }
}
