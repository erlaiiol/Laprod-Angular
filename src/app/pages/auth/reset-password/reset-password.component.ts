import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../../services/auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-reset-password',
  standalone: true,
  imports: [FormsModule, RouterModule],
  templateUrl: './reset-password.component.html',
  styleUrl: '../login/login.component.scss',
})
export class ResetPasswordComponent {
  private authSvc = inject(AuthService);

  readonly token = inject(ActivatedRoute).snapshot.queryParamMap.get('token');

  password        = '';
  passwordConfirm = '';
  loading = signal(false);
  done    = signal(false);
  error   = signal<string | null>(this.token ? null : 'Lien invalide.');
  /** Lien expiré / déjà utilisé : le formulaire n'a plus de sens, on propose d'en redemander un. */
  expired = signal(!this.token);

  onSubmit(): void {
    if (!this.token || this.loading()) return;
    if (this.password !== this.passwordConfirm) {
      this.error.set('Les mots de passe ne correspondent pas.');
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.authSvc.resetPassword(this.token, this.password, this.passwordConfirm).pipe(
      finalize(() => this.loading.set(false)),
    ).subscribe({
      next: () => this.done.set(true),
      error: (err: any) => {
        if (err?.error?.code === 'TOKEN_EXPIRED') this.expired.set(true);
        this.error.set(err?.error?.feedback?.message ?? 'Une erreur est survenue.');
      },
    });
  }
}
