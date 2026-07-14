import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { LEGAL_ENTITY } from '../../../config/legal.config';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-cgu',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './cgu.component.html',
  styleUrl:    './cgu.component.scss',
})
export class CguComponent {
  lastUpdated = '21 mai 2026';
  readonly legal = LEGAL_ENTITY;
}
