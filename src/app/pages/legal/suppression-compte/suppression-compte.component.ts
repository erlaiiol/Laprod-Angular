import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-suppression-compte',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './suppression-compte.component.html',
  styleUrl:    './suppression-compte.component.scss',
})
export class SuppressionCompteComponent {
  lastUpdated = '6 août 2026';
}
