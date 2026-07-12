import { Component, Output, EventEmitter, computed, input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-pagination',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './pagination.component.html',
  styleUrls: ['./pagination.component.scss'],
})
export class PaginationComponent {
  // Inputs signal (pas @Input() classique) : un simple @Input() ne notifie
  // le graphe de signals Angular que via la passe de CD du PARENT. Quand le
  // changement de page part d'un clic DANS ce composant lui-même (bouton →
  // pageChange → le parent écrit son signal "page"), la passe de rafraîchissement
  // locale déclenchée par cet événement ne redescend pas forcément re-vérifier
  // CE composant pour lui faire relire son propre @Input() à jour — d'où la
  // pagination visuellement bloquée sur l'ancienne page au premier clic. Un
  // input signal crée un vrai lien producteur/consommateur : peu importe quel
  // composant a déclenché l'écriture, ce composant est notifié directement.
  currentPage = input(1);
  totalPages  = input(1);
  @Output() pageChange = new EventEmitter<number>();

  // Fenêtre de pages : toujours 1-2, toujours n-1/n, et current ±1 — gaps → null
  pages = computed<(number | null)[]>(() => {
    const total   = this.totalPages();
    const current = this.currentPage();

    if (total <= 7) {
      return Array.from({ length: total }, (_, i) => i + 1);
    }

    const show = new Set<number>([1, 2, total - 1, total]);
    for (let p = current - 1; p <= current + 1; p++) {
      if (p >= 1 && p <= total) show.add(p);
    }

    const sorted = [...show].sort((a, b) => a - b);
    const result: (number | null)[] = [];
    for (let i = 0; i < sorted.length; i++) {
      result.push(sorted[i]);
      if (i < sorted.length - 1 && sorted[i + 1]! > sorted[i]! + 1) {
        result.push(null);
      }
    }
    return result;
  });

  go(page: number): void {
    if (page < 1 || page > this.totalPages() || page === this.currentPage()) return;
    this.pageChange.emit(page);
  }
}
