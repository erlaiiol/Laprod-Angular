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

  loading        = signal(false);
  error          = signal<string | null>(null);
  confirmedEmail = signal<string | null>(null); // success state

  constructor(private authService: AuthService) {}

  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);

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
          this.error.set(
            err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez.'
          );
        },
      });
  }
}
