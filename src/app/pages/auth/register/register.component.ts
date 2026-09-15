import { ChangeDetectionStrategy, Component, OnInit, signal, viewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../services/auth.service';
import { TurnstileComponent } from '../../../components/turnstile/turnstile.component';
import { finalize } from 'rxjs';
import { environment } from '../../../../environments/environment';
import { Capacitor } from '@capacitor/core';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, TurnstileComponent],
  templateUrl: './register.component.html',
  styleUrl: './register.component.scss',
})
export class RegisterComponent implements OnInit {

  readonly googleLoginUrl = `${environment.apiUrl}/api/auth/google/login`;
  readonly appleLoginUrl  = `${environment.apiUrl}/api/auth/apple/login`;
  readonly isIosNative    = Capacitor.getPlatform() === 'ios';
  appleLoading = signal(false);

  // CAPTCHA requis (web + site key configurée) ; toujours faux en natif.
  readonly captchaEnabled = TurnstileComponent.isEnabled;
  private readonly turnstile = viewChild(TurnstileComponent);
  captchaToken = signal<string | null>(null);

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

  constructor(private authService: AuthService, private route: ActivatedRoute) {}

  ngOnInit(): void {
    // Préremplissage depuis une invitation à signer un contrat (voir
    // ContractSignInviteComponent.goToRegister) — pur confort, le rattachement
    // réel du compte à l'invitation se fait via le localStorage 'pendingContractInvite'
    // consommé par LoginComponent une fois l'email vérifié et l'utilisateur connecté.
    const email = this.route.snapshot.queryParamMap.get('email');
    if (email) this.email = email;
  }

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
      this.captchaToken(),
    ).pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success) {
            this.confirmedEmail.set(res.data?.user?.email ?? this.email);
          } else {
            this.error.set(res.feedback?.message ?? 'Erreur lors de l\'inscription.');
            this.resetCaptcha();
          }
        },
        error: (err) => {
          const code = err?.error?.code;
          if (code === 'PENDING_EMAIL_VERIFICATION') {
            this.pendingEmail.set(err.error.data?.email ?? this.email);
          } else if (code === 'SEND_CONFIRM_EMAIL_MESSAGE') {
            // Compte créé mais email non envoyé : afficher le panel resend
            this.pendingEmail.set(err.error.data?.user?.email ?? this.email);
          } else {
            this.error.set(
              err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez.'
            );
          }
          this.resetCaptcha();
        },
      });
  }

  /** Sur Android natif : Chrome Custom Tabs plutôt que la WebView de l'app
   *  (cf. AuthService.startGoogleLogin). Sur web : ne fait rien, le <a href>
   *  navigue normalement. */
  onGoogleLogin(event: Event): void {
    this.authService.startGoogleLogin(event);
  }

  /** Android/web : voir LoginComponent.onAppleWebLogin (même mécanique). */
  onAppleWebLogin(event: Event): void {
    this.authService.startAppleWebLogin(event);
  }

  /** iOS uniquement : voir LoginComponent.onAppleNativeLogin (même flow —
   *  Sign in with Apple crée ou connecte le compte indifféremment, il n'y a
   *  pas de distinction inscription/connexion côté Apple). */
  onAppleNativeLogin(): void {
    if (this.appleLoading()) return;
    this.appleLoading.set(true);
    this.error.set(null);

    this.authService.appleNativeSignIn()
      .pipe(finalize(() => this.appleLoading.set(false)))
      .subscribe({
        next: (res) => {
          if (!res.success || !res.data) {
            this.error.set(res.feedback?.message ?? 'Échec de la connexion Apple.');
            return;
          }
          this.authService.storeOauthAuth(res.data);
          this.authService.navigateAfterOauth(res.data.next, res.data.suggested_name);
        },
        error: (err) => {
          // cf. LoginComponent.onAppleNativeLogin pour le détail du code d'annulation.
          if (err?.code === '1001' || err?.code === 'SIGN_IN_CANCELED') return;
          this.error.set(err?.error?.feedback?.message ?? 'Échec de la connexion Apple. Réessayez.');
        },
      });
  }

  private resetCaptcha(): void {
    this.captchaToken.set(null);
    this.turnstile()?.reset();
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
