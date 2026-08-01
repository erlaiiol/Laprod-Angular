import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, signal, viewChild } from '@angular/core';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { GuestToplineService } from '../../../services/guest-topline.service';
import { ToastService } from '../../../services/toast.service';
import { TurnstileComponent } from '../../../components/turnstile/turnstile.component';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { environment } from '../../../../environments/environment';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-login',
  standalone : true,
  imports: [ CommonModule, RouterModule, FormsModule, TurnstileComponent ],
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

  // CAPTCHA : n'apparaît qu'après un refus CAPTCHA_REQUIRED (throttle progressif),
  // et seulement sur le web avec une site key configurée.
  readonly captchaEnabled = TurnstileComponent.isEnabled;
  private readonly turnstile = viewChild(TurnstileComponent);
  showCaptcha  = signal(false);
  captchaToken = signal<string | null>(null);

  private hasCalled = false;

  constructor(
    private authService : AuthService,
    private router      : Router,
    private route       : ActivatedRoute,
    private guestSvc    : GuestToplineService,
    private toast       : ToastService,
  ) {}

  /** Redirection post-connexion vers une destination différée : invitation à
   * signer un contrat reçue par email (localStorage — survit à l'aller-retour
   * par la vérification d'email lors d'une inscription) ou `?returnUrl=`
   * (convention déjà posée ailleurs — ex: track-contract-config, mix/order —
   * mais jamais consommée jusqu'ici). Retourne true si une redirection a eu lieu. */
  private redirectToPendingDestination(): boolean {
    const pendingInvite = localStorage.getItem('pendingContractInvite');
    if (pendingInvite) {
      localStorage.removeItem('pendingContractInvite');
      this.router.navigate(['/contracts/sign-invite'], { queryParams: { token: pendingInvite } });
      return true;
    }
    const returnUrl = this.route.snapshot.queryParamMap.get('returnUrl');
    if (returnUrl) {
      this.router.navigateByUrl(returnUrl);
      return true;
    }
    return false;
  }

  onSubmit() {
    this.loading.set(true);
    this.error.set(null);
    this.pendingEmail.set(null);
    this.resendSuccess.set(false);
    this.showPasswordSetLink.set(false);
    this.passwordEmail.set(null);

    this.authService.login(this.identifier, this.password, this.remember, this.captchaToken())
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success) {
            if (this.guestSvc.hasPendingClaim()) {
              this.guestSvc.claimAfterLogin().subscribe({
                next: (claim) => {
                  if (claim.success && (claim.data?.claimed ?? 0) > 0) {
                    this.toast.showToast({
                      level: 'success',
                      message: `${claim.data!.claimed} topline(s) récupérée(s) depuis ta session invité !`,
                    });
                  }
                  this.guestSvc.clearPendingClaim();
                },
                error: () => this.guestSvc.clearPendingClaim(),
              });
            }
            const user = this.authService.currentUser();
            if (res.code === 'SHOW_SELECT_ROLE' || (user && !user.user_type_selected)) {
              this.router.navigate(['/select-role']);
            } else if (!this.redirectToPendingDestination()) {
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
          } else if (code === 'CAPTCHA_REQUIRED') {
            // Trop d'échecs : on affiche le CAPTCHA et on demande de rejouer.
            this.showCaptcha.set(true);
            this.error.set(err?.error?.feedback?.message ?? 'Confirmez que vous n\'êtes pas un robot.');
          } else {
            this.error.set(
              err?.error?.feedback?.message ?? 'Une erreur est survenue. Réessayez.'
            );
          }
          // Un token à usage unique ne se rejoue pas : on le réinitialise.
          this.captchaToken.set(null);
          this.turnstile()?.reset();
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
