import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { LEGAL_ENTITY } from '../../../config/legal.config';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-dmca',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './dmca.component.html',
  styleUrl:    './dmca.component.scss',
})
export class DmcaComponent {
  lastUpdated = '29 juin 2026';
  readonly legal = LEGAL_ENTITY;
}
