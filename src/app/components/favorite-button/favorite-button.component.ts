import { Component, Input, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FavoritesService } from '../../services/favorites.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-favorite-button',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './favorite-button.component.html',
  styleUrls: ['./favorite-button.component.scss'],
})
export class FavoriteButtonComponent implements OnInit {

  @Input() trackId!: number;

  isFavorite = signal(false);
  pending    = signal(false);

  private favSvc = inject(FavoritesService);
  readonly auth  = inject(AuthService);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) return;
    this.favSvc.check(this.trackId).subscribe({
      next: (res) => this.isFavorite.set(res.is_favorite),
      error: () => {},
    });
  }

  toggle(event: MouseEvent): void {
    event.stopPropagation();
    if (!this.auth.isLoggedIn() || this.pending()) return;
    this.pending.set(true);
    this.favSvc.toggle(this.trackId).subscribe({
      next: (res) => {
        if (res.success && res.data) this.isFavorite.set(res.data.is_favorite);
        this.pending.set(false);
      },
      error: () => this.pending.set(false),
    });
  }
}
