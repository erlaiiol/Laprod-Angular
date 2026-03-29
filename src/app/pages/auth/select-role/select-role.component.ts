import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-select-role',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './select-role.component.html',
  styleUrl: './select-role.component.scss',
})
export class SelectRoleComponent {

  isArtist      = signal(false);
  isBeatmaker   = signal(false);
  isMixEngineer = signal(false);

  loading = signal(false);
  error   = signal<string | null>(null);

  hasSelection = () => this.isArtist() || this.isBeatmaker() || this.isMixEngineer();

  constructor(private auth: AuthService, private router: Router) {}

  toggle(role: 'artist' | 'beatmaker' | 'mix'): void {
    if (role === 'artist')    this.isArtist.update(v => !v);
    if (role === 'beatmaker') this.isBeatmaker.update(v => !v);
    if (role === 'mix')       this.isMixEngineer.update(v => !v);
  }

  onSubmit(): void {
    if (!this.hasSelection()) {
      this.error.set('Vous devez sélectionner au moins un rôle.');
      return;
    }
    this.loading.set(true);
    this.error.set(null);

    this.auth.selectRole({
      is_artist:       this.isArtist(),
      is_beatmaker:    this.isBeatmaker(),
      is_mix_engineer: this.isMixEngineer(),
    }).pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success && res.data) {
            // Mise à jour du user en mémoire
            const stored = JSON.parse(localStorage.getItem('user') ?? '{}');
            const updated = { ...stored, ...res.data.user };
            localStorage.setItem('user', JSON.stringify(updated));

            const next = res.data.next;
            this.router.navigate([next === 'submit-sample' ? '/submit-sample' : '/']);
          } else {
            this.error.set(res.feedback?.message ?? 'Erreur lors de la mise à jour.');
          }
        },
        error: (err) => {
          this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur. Réessayez.');
        },
      });
  }
}
