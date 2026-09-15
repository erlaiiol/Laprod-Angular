import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

/**
 * Écran "Test micro" (monitoring sans enregistrement) — extrait de
 * MobileStudioComponent (état `studioState() === 'warming-up'`). Pure
 * présentation : toute la logique (session pitch monitor, lecture du beat…)
 * reste dans le parent, qui pilote ce composant via inputs/outputs.
 */
@Component({
  selector: 'app-mobile-studio-warmup',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './mobile-studio-warmup.component.html',
  styleUrls: ['../mobile-studio-shared.scss', './mobile-studio-warmup.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MobileStudioWarmupComponent {
  @Input() micGain         = 1;
  @Input() micGainDb       = '';
  @Input() levelPct        = 0;
  @Input() detectedNote: string | null = null;
  @Input() correctionCents = 0;
  @Input() monitorAutotune = false;
  /** Tonalité du beat — chaîne vide si aucune (même sémantique que `TrackDetail.key`). */
  @Input() trackKey = '';

  @Output() micGainChange = new EventEmitter<number>();
  @Output() stop          = new EventEmitter<void>();

  onMicGainInput(event: Event): void {
    this.micGainChange.emit(+(event.target as HTMLInputElement).value);
  }
}
