import { ChangeDetectionStrategy, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

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
}
