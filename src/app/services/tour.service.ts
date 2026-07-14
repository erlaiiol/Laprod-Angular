import { Injectable, computed, signal } from '@angular/core';
import { TOURS, TourDef, TourId, TourStep } from '../tours/tour-definitions';

const LS_ENABLED = 'laprod_tours_enabled';
const LS_SEEN    = 'laprod_tours_seen';

/**
 * Visites guidées contextuelles (bulles ancrées sur de vrais éléments du DOM).
 *
 * État persisté en localStorage — il est donc propre à l'appareil. C'est assumé :
 * l'interrupteur `enabled` permet de couper définitivement les bulles sur une
 * nouvelle machine sans avoir à les subir une par une.
 *
 * Les ancres sont enregistrées par la directive `lpTourAnchor`. Une étape dont
 * l'ancre est absente du DOM (élément conditionnel, rôle non activé, écran mobile…)
 * est simplement retirée du parcours : une visite ne pointe jamais dans le vide.
 */
@Injectable({ providedIn: 'root' })
export class TourService {

  private anchors = new Map<string, HTMLElement>();

  readonly enabled = signal<boolean>(this.readEnabled());
  readonly seen    = signal<Record<string, boolean>>(this.readSeen());

  readonly activeTour = signal<TourDef | null>(null);
  readonly steps      = signal<TourStep[]>([]);
  readonly index      = signal(0);

  readonly isOpen     = computed(() => this.activeTour() !== null);
  readonly currentStep = computed<TourStep | null>(() => this.steps()[this.index()] ?? null);
  readonly total       = computed(() => this.steps().length);
  readonly isLast      = computed(() => this.index() >= this.total() - 1);

  // ── Enregistrement des ancres (directive lpTourAnchor) ─────────────────────

  register(id: string, el: HTMLElement): void {
    this.anchors.set(id, el);
  }

  unregister(id: string, el: HTMLElement): void {
    // Ne retire que si l'élément est bien celui enregistré : évite qu'un composant
    // détruit après re-création d'un homonyme n'efface l'ancre du nouveau.
    if (this.anchors.get(id) === el) this.anchors.delete(id);
  }

  anchorEl(id: string): HTMLElement | null {
    return this.anchors.get(id) ?? null;
  }

  // ── Cycle de vie d'une visite ──────────────────────────────────────────────

  /** Démarre la visite si les bulles sont activées et qu'elle n'a jamais été vue. */
  maybeAutoStart(id: TourId): void {
    if (!this.enabled()) return;
    if (this.seen()[id]) return;
    this.start(id);
  }

  /** Démarre (ou redémarre) une visite, quel que soit l'état « déjà vue ». */
  start(id: TourId): void {
    const def = TOURS[id];
    if (!def) return;

    const steps = def.steps.filter(s => this.anchors.has(s.anchor));
    if (!steps.length) return;

    this.steps.set(steps);
    this.index.set(0);
    this.activeTour.set(def);
  }

  next(): void {
    if (this.isLast()) { this.finish(); return; }
    this.index.update(i => i + 1);
  }

  prev(): void {
    this.index.update(i => Math.max(0, i - 1));
  }

  /** Termine la visite et la marque comme vue (ne se relancera plus toute seule). */
  finish(): void {
    const def = this.activeTour();
    if (def) this.markSeen(def.id);
    this.close();
  }

  /** Ferme sans marquer comme vue : la visite pourra se relancer. */
  close(): void {
    this.activeTour.set(null);
    this.steps.set([]);
    this.index.set(0);
  }

  // ── Préférences ────────────────────────────────────────────────────────────

  setEnabled(on: boolean): void {
    this.enabled.set(on);
    localStorage.setItem(LS_ENABLED, on ? '1' : '0');
    if (!on) this.close();
  }

  /** « Ne plus afficher les bulles » — coupe tout et ferme la visite en cours. */
  disableForever(): void {
    this.setEnabled(false);
  }

  /** Réinitialise l'historique : toutes les visites pourront se rejouer. */
  resetSeen(): void {
    this.seen.set({});
    localStorage.removeItem(LS_SEEN);
  }

  hasSeen(id: TourId): boolean {
    return !!this.seen()[id];
  }

  private markSeen(id: TourId): void {
    const next = { ...this.seen(), [id]: true };
    this.seen.set(next);
    localStorage.setItem(LS_SEEN, JSON.stringify(next));
  }

  // ── Lecture du localStorage (tolérante aux données corrompues) ──────────────

  private readEnabled(): boolean {
    try {
      return localStorage.getItem(LS_ENABLED) !== '0';
    } catch {
      return true;
    }
  }

  private readSeen(): Record<string, boolean> {
    try {
      const raw = localStorage.getItem(LS_SEEN);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  }
}
