import { ChangeDetectionStrategy, Component } from '@angular/core';

// ─────────────────────────────────────────────────────────────────────────────
// BETA BADGE — pastille "Bêta" réutilisable, posée à côté des libellés des
// modules encore en rodage (espace producteur, contrats, rétroplanning).
// Composant plutôt que classe SCSS dupliquée : le style est identique partout,
// un seul endroit à faire évoluer si le libellé/l'apparence changent.
// ─────────────────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-beta-badge',
  standalone: true,
  template: `<span class="beta-badge">Bêta</span>`,
  styleUrl: './beta-badge.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BetaBadgeComponent {}
