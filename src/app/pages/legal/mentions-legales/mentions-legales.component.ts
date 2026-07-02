import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-mentions-legales',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './mentions-legales.component.html',
  styleUrl:    './mentions-legales.component.scss',
})
export class MentionsLegalesComponent {
  lastUpdated = '21 mai 2026';
}
