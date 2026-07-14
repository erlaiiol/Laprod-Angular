import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { LEGAL_ENTITY } from '../../../config/legal.config';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-mentions-legales',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './mentions-legales.component.html',
  styleUrl:    './mentions-legales.component.scss',
})
export class MentionsLegalesComponent {
  lastUpdated = '21 mai 2026';
  readonly legal = LEGAL_ENTITY;
}
