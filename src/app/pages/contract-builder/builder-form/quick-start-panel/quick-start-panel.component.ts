import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Preset } from '../../contract-type-configs';

/**
 * Panneau "Démarrage rapide" — extrait de BuilderFormComponent, où il était
 * rendu deux fois (rail droit + repli mobile de l'onglet Introduction) via un
 * unique <ng-template #quickStartPanel> et *ngTemplateOutlet. Devenir un vrai
 * composant standalone permet de l'utiliser aux deux endroits sans ce détour.
 */
@Component({
  selector: 'app-quick-start-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './quick-start-panel.component.html',
  styleUrls: ['./quick-start-panel.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class QuickStartPanelComponent {
  @Input() isFinal = false;
  @Input() hasKeyInfo = false;
  @Input() autoFieldsDone = 0;
  @Input() locked = false;
  @Input() keyInfoHint = '';
  @Input() fillableCount = 0;
  @Input({ required: true }) presets!: Preset[];

  @Output() goToPremium = new EventEmitter<void>();
  @Output() applyQuickStart = new EventEmitter<void>();
  @Output() goToIntro = new EventEmitter<void>();
  @Output() fillAllExamples = new EventEmitter<void>();
  @Output() applyPreset = new EventEmitter<string>();
}
