import { ChangeDetectionStrategy, Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute, Router } from '@angular/router';
import { ContractBuilderService } from '../../services/contract-builder.service';
import { AuthService } from '../../services/auth.service';

export const PENDING_CONTRACT_INVITE_KEY = 'pendingContractInvite';

// ─────────────────────────────────────────────────────────────────────────────
// Atterrissage du lien envoyé par email à quelqu'un qui n'avait pas encore de
// compte LaProd au moment de l'invitation à signer un contrat (voir
// send_contract_invite_email côté backend). Route publique : on affiche un
// aperçu (titre du contrat + invitant) puis on guide vers connexion/inscription
// si besoin, avant de rattacher le compte à l'invitation et de rediriger vers
// le contrat. Si déjà connecté, tout se fait en un seul appel.
// ─────────────────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-contract-sign-invite',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './contract-sign-invite.component.html',
  styleUrl: './contract-sign-invite.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ContractSignInviteComponent implements OnInit {

  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private svc = inject(ContractBuilderService);
  readonly auth = inject(AuthService);

  loading = signal(true);
  error   = signal<string | null>(null);
  preview = signal<{ title: string; inviter_username: string; email: string } | null>(null);
  resolving = signal(false);

  private token = '';

  ngOnInit(): void {
    this.token = this.route.snapshot.queryParamMap.get('token') ?? '';
    if (!this.token) {
      this.loading.set(false);
      this.error.set('Lien invalide : aucun jeton trouvé.');
      return;
    }

    this.svc.getInvitePreview(this.token).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.preview.set(res.data);
          if (this.auth.isLoggedIn()) this.resolve();
        } else {
          this.error.set(res.feedback?.message ?? "Ce lien d'invitation est invalide ou a expiré.");
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? "Ce lien d'invitation est invalide ou a expiré.");
      },
    });
  }

  private resolve(): void {
    this.resolving.set(true);
    this.svc.resolveInvite(this.token).subscribe({
      next: res => {
        this.resolving.set(false);
        if (res.success && res.data) {
          localStorage.removeItem(PENDING_CONTRACT_INVITE_KEY);
          this.router.navigate(['/contract-builder', res.data.contract_id]);
        } else {
          this.error.set(res.feedback?.message ?? 'Impossible de rattacher ce contrat à votre compte.');
        }
      },
      error: err => {
        this.resolving.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de rattacher ce contrat à votre compte.');
      },
    });
  }

  /** Mémorise l'invitation avant de partir vers login/register — LoginComponent
   * la consomme après connexion (y compris après un aller-retour par la
   * vérification d'email pour une inscription). */
  private storePending(): void {
    localStorage.setItem(PENDING_CONTRACT_INVITE_KEY, this.token);
  }

  goToLogin(): void {
    this.storePending();
    this.router.navigate(['/login'], {
      queryParams: { returnUrl: `/contracts/sign-invite?token=${this.token}` },
    });
  }

  goToRegister(): void {
    this.storePending();
    this.router.navigate(['/register'], {
      queryParams: { email: this.preview()?.email ?? '' },
    });
  }
}
