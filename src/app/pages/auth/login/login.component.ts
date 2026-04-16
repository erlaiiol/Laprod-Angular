import { CommonModule } from '@angular/common';
import { Component, signal } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-login',
  standalone : true,
  imports: [ CommonModule, RouterModule, FormsModule ],
  templateUrl: './login.component.html',
  styleUrl: './login.component.scss',
})
export class LoginComponent {

  readonly googleLoginUrl = `${environment.apiUrl}/api/auth/google/login`;

  identifier : string = '';
  password : string = '';
  remember : boolean = false;

  loading              = signal(false);
  resendLoading        = signal(false);
  error                = signal<string | null>(null);
  pendingEmail         = signal<string | null>(null);  // email non vérifié → renvoi lien
  resendSuccess        = signal(false);
  showPasswordSetLink  = signal(false);                // compte OAuth sans mot de passe
  passwordEmail        = signal<string | null>(null);

  constructor(private authService : AuthService, private router : Router ) {}

  onSubmit() {
    this.loading.set(true);
    this.error.set(null);
    this.pendingEmail.set(null);
    this.resendSuccess.set(false);
    this.showPasswordSetLink.set(false);
    this.passwordEmail.set(null);

    this.authService.login(this.identifier, this.password, this.remember)
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success) {
            // La navigation est déjà gérée par AuthService.login() via tap()
            // (→ /select-role si SHOW_SELECT_ROLE, sinon on navigue vers /)
            if (res.code !== 'SHOW_SELECT_ROLE') {
              this.router.navigate(['/']);
            }
          } else {
            this.error.set(res.feedback?.message ?? 'Identifiants incorrects.');
          }
        },
        error: (err) => {
          const code = err?.error?.code;
          if (code === 'SHOW_EMAIL_CONFIRMATION_LINK') {
            this.pendingEmail.set(err.error.data?.confirmation_email ?? null);
          } else if (code === 'SHOW_PASSWORD_SET_LINK') {
            this.showPasswordSetLink.set(true);
            this.passwordEmail.set(err.error.data?.password_email ?? null);
          } else {
            this.error.set(
              err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez.'
            );
          }
        },
      });
  }

  resendVerification(): void {
    // Priorité à l'email renvoyé par le backend ; fallback sur l'identifiant saisi
    // (peut être un username ou un email — le backend résout les deux)
    const identifier = this.pendingEmail() || this.identifier;
    if (!identifier || this.resendLoading()) return;
    this.resendLoading.set(true);
    this.resendSuccess.set(false);
    this.authService.resendVerification(identifier)
      .pipe(finalize(() => this.resendLoading.set(false)))
      .subscribe({
        next: () => this.resendSuccess.set(true),
        error: () => this.error.set('Erreur lors du renvoi. Réessayez.'),
      });
  }

}
