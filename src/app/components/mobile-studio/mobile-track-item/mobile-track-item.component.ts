import {
  Component, Input, Output, EventEmitter, signal,
  ChangeDetectionStrategy, inject, ViewChild, ElementRef, AfterViewChecked,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule }  from '@angular/forms';
import { VocalTrack, MobileMaquetteService } from '../../../services/mobile-maquette.service';
import type { TrackSettings } from '../../../services/mobile-maquette.service';

/**
 * Inspecteur d'une piste vocale : affiché sous la timeline du studio quand la
 * piste est sélectionnée. Nom, actions de prise, volume et effets — tout réglage
 * s'entend immédiatement si le mix est en lecture.
 */
@Component({
  selector: 'app-mobile-track-item',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './mobile-track-item.component.html',
  styleUrls: ['./mobile-track-item.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MobileTrackItemComponent implements AfterViewChecked {

  @Input({ required: true }) track!: VocalTrack;
  @Input() trackKey    = '';
  /**
   * Invité (sans compte) : seuls le volume et les actions de prise restent
   * disponibles ; autotune, réverb, boue, présence et clarté sont verrouillés.
   */
  @Input() fxLocked = false;

  @Output() startRecord = new EventEmitter<string>();
  @Output() remove      = new EventEmitter<string>();
  @Output() punchIn     = new EventEmitter<string>();
  /** L'invité demande l'accès aux effets (le parent ouvre l'invitation à créer un compte). */
  @Output() fxUnlock    = new EventEmitter<void>();
  @Output() closed      = new EventEmitter<void>();

  @ViewChild('nameInput')  nameInputRef?: ElementRef<HTMLInputElement>;

  readonly editingName      = signal(false);
  editNameValue             = '';

  private readonly service   = inject(MobileMaquetteService);

  ngAfterViewChecked(): void {
    // Focus automatique sur l'input de renommage à l'ouverture
    if (this.editingName() && this.nameInputRef?.nativeElement) {
      this.nameInputRef.nativeElement.focus();
    }
  }

  // ── Renommage ─────────────────────────────────────────────────────────────────

  startRename(): void {
    this.editNameValue = this.track.name;
    this.editingName.set(true);
  }

  confirmRename(): void {
    const trimmed = this.editNameValue.trim();
    if (trimmed) this.service.renameTrack(this.track.id, trimmed);
    this.editingName.set(false);
  }

  cancelRename(): void {
    this.editingName.set(false);
  }

  onNameKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter')  { event.preventDefault(); this.confirmRename(); }
    if (event.key === 'Escape') { event.preventDefault(); this.cancelRename();  }
  }

  // ── Presets EQ / Réverb ───────────────────────────────────────────────────────

  readonly clarityPresets: ReadonlyArray<{ label: string; value: number }> = [
    { label: 'Sombre',      value: 0 },
    { label: 'Medium',      value: 3 },
    { label: 'Voix claire', value: 7 },
  ];

  /** Réverb appliquée au rendu final seulement (export, clip) — jamais à l'écoute ni au casque. */
  readonly reverbPresets: ReadonlyArray<{ label: string; value: number }> = [
    { label: 'Discret',  value: 0.05 },
    { label: 'Réaliste', value: 0.12 },
    { label: 'Concert',  value: 0.20 },
  ];

  /** Coupe-bas : plus il est haut, plus on retire de "boue" (grave, effet de proximité). */
  readonly lowCutPresets: ReadonlyArray<{ label: string; value: number; hint: string }> = [
    { label: '80 Hz',  value: 80,  hint: 'Garde le corps — voix graves' },
    { label: '150 Hz', value: 150, hint: 'Équilibré — la plupart des voix' },
    { label: '220 Hz', value: 220, hint: 'Nettoie fort — voix proches du micro, mix chargé' },
  ];

  readonly presencePresets: ReadonlyArray<{ label: string; value: number }> = [
    { label: 'Douce',   value: 0 },
    { label: 'Normale', value: 3.5 },
    { label: 'Devant',  value: 6 },
  ];

  // Chaque réglage touché désigne aussi cette piste comme celle entendue dans le
  // retour casque : le changement s'entend immédiatement.
  setClarity(v: number):  void { this._updateFx({ clarityDb: v }); }
  setReverb(v: number):   void { this._updateFx({ reverbWet: v }); }
  setLowCut(v: number):   void { this._updateFx({ lowCutHz: v }); }
  setPresence(v: number): void { this._updateFx({ presenceDb: v }); }

  isActiveClarity(v: number):  boolean { return Math.abs(this.track.settings.clarityDb - v) < 0.1; }
  isActiveReverb(v: number):   boolean { return Math.abs(this.track.settings.reverbWet - v) < 0.005; }
  isActiveLowCut(v: number):   boolean { return Math.abs((this.track.settings.lowCutHz ?? 150) - v) < 1; }
  isActivePresence(v: number): boolean { return Math.abs((this.track.settings.presenceDb ?? 3.5) - v) < 0.1; }

  /** Réglage d'effet : refusé à un invité (le volume passe par _update, toujours libre). */
  private _updateFx(partial: Partial<TrackSettings>): void {
    if (this.fxLocked) { this.fxUnlock.emit(); return; }
    this._update(partial);
  }

  private _update(partial: Partial<TrackSettings>): void {
    this.service.updateSettings(this.track.id, partial);
    this.service.focusTrack(this.track.id);
  }

  // ── Labels lisibles ──────────────────────────────────────────────────────────

  volumeLabel(v: number): string {
    const db = Math.round(20 * Math.log10(v) * 10) / 10;
    if (!isFinite(db)) return '-∞ dB';
    return db >= 0 ? `+${db} dB` : `${db} dB`;
  }

  // ── Autotune toggle ──────────────────────────────────────────────────────────

  async toggleAutotune(): Promise<void> {
    if (this.fxLocked) { this.fxUnlock.emit(); return; }
    const newVal = !this.track.settings.useAutotune;
    this.service.updateSettings(this.track.id, { useAutotune: newVal });
    if (newVal && !this.track.processedBlob) {
      await this.service.ensureAutotune(this.track.id, this.trackKey);
    }
  }

  // ── Slider helpers ───────────────────────────────────────────────────────────

  onVolume(event: Event): void {
    this._update({ volume: +(event.target as HTMLInputElement).value });
  }
}
