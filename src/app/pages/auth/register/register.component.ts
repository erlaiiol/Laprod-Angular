import { Component, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../services/auth.service';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './register.component.html',
  styleUrl: './register.component.scss',
})
export class RegisterComponent {

  username        = '';
  email           = '';
  password        = '';
  passwordConfirm = '';
  signature       = '';
  acceptTerms     = false;

  loading          = signal(false);
  resendLoading    = signal(false);
  error            = signal<string | null>(null);
  confirmedEmail   = signal<string | null>(null);
  // Email en attente de vérification (compte déjà créé, mail non vérifié)
  pendingEmail     = signal<string | null>(null);
  resendSuccess    = signal(false);

  constructor(private authService: AuthService) {}

  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);
    this.pendingEmail.set(null);

    this.authService.register(
      this.username,
      this.password,
      this.passwordConfirm,
      this.email,
      this.signature,
      this.acceptTerms,
    ).pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success) {
            this.confirmedEmail.set(res.data?.user?.email ?? this.email);
          } else {
            this.error.set(res.feedback?.message ?? 'Erreur lors de l\'inscription.');
          }
        },
        error: (err) => {
          if (err?.error?.code === 'PENDING_EMAIL_VERIFICATION') {
            this.pendingEmail.set(err.error.data?.email ?? this.email);
          } else {
            this.error.set(
              err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez.'
            );
          }
        },
      });
  }

  resendVerification(): void {
    const email = this.pendingEmail();
    if (!email || this.resendLoading()) return;
    this.resendLoading.set(true);
    this.resendSuccess.set(false);
    this.authService.resendVerification(email)
      .pipe(finalize(() => this.resendLoading.set(false)))
      .subscribe({
        next: () => this.resendSuccess.set(true),
        error: () => this.error.set('Erreur lors du renvoi. Réessayez.'),
      });
  }
}
