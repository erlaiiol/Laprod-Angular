import {
  ChangeDetectionStrategy, Component, ElementRef, EventEmitter,
  HostListener, Output, computed, effect, input, signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-style-select',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './style-select.component.html',
  styleUrls: ['./style-select.component.scss'],
})
export class StyleSelectComponent {

  value       = input('');
  options     = input<string[]>([]);
  placeholder = input('Ex: Trap, R&B, Afrobeats…');
  inputId     = input('style');
  inputName   = input('style');

  @Output() valueChange = new EventEmitter<string>();

  // Texte affiché dans l'input, distinct de `value` tant que l'utilisateur n'a
  // pas explicitement choisi une option — évite de committer du texte libre à
  // chaque frappe (l'utilisateur doit sélectionner un style existant ou
  // cliquer "ajouter" pour qu'il devienne la valeur réelle du champ).
  draft  = signal('');
  isOpen = signal(false);

  constructor(private host: ElementRef<HTMLElement>) {
    effect(() => { this.draft.set(this.value()); });
  }

  filteredOptions = computed(() => {
    const q = this.draft().trim().toLowerCase();
    if (!q) return this.options();
    return this.options().filter(o => o.toLowerCase().includes(q));
  });

  exactMatch = computed(() => {
    const q = this.draft().trim().toLowerCase();
    if (!q) return null;
    return this.options().find(o => o.toLowerCase() === q) ?? null;
  });

  showAddOption = computed(() => this.draft().trim().length > 0 && !this.exactMatch());

  @HostListener('document:click', ['$event'])
  onDocumentClick(event: MouseEvent): void {
    if (!this.isOpen()) return;
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.close();
    }
  }

  onFocus(): void {
    this.isOpen.set(true);
  }

  onInput(raw: string): void {
    this.draft.set(raw);
    this.isOpen.set(true);
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      this.close();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      const match = this.exactMatch();
      if (match)                 this.selectExisting(match);
      else if (this.showAddOption()) this.selectNew();
    }
  }

  selectExisting(option: string): void {
    this.draft.set(option);
    this.valueChange.emit(option);
    this.isOpen.set(false);
  }

  selectNew(): void {
    const v = this.draft().trim();
    if (!v) return;
    this.valueChange.emit(v);
    this.isOpen.set(false);
  }

  private close(): void {
    this.isOpen.set(false);
    // Rien n'a été sélectionné explicitement : on revient à la dernière
    // valeur validée plutôt que de laisser un texte non pris en compte affiché.
    this.draft.set(this.value());
  }
}
