import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { finalize } from 'rxjs';
import { AuthService } from '../../../services/auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-forgot-password',
  standalone: true,
  imports: [FormsModule, RouterModule],
  templateUrl: './forgot-password.component.html',
  styleUrl: '../login/login.component.scss',
})
export class ForgotPasswordComponent {
  private authSvc = inject(AuthService);

  email   = inject(ActivatedRoute).snapshot.queryParamMap.get('email') ?? '';
  loading = signal(false);
  sent    = signal(false);
  error   = signal<string | null>(null);

  onSubmit(): void {
    if (!this.email.trim() || this.loading()) return;
    this.loading.set(true);
    this.error.set(null);
    this.authSvc.forgotPassword(this.email.trim()).pipe(
      finalize(() => this.loading.set(false)),
    ).subscribe({
      next: () => this.sent.set(true),
      error: (err: any) => this.error.set(
        err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez plus tard.'),
    });
  }
}
