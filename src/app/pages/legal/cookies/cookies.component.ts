import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-cookies',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './cookies.component.html',
  styleUrl:    './cookies.component.scss',
})
export class CookiesComponent {
  lastUpdated = '29 juin 2026';
}
