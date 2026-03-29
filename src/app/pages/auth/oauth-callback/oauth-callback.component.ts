import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../../services/auth.service';

/**
 * Page intermédiaire transparente : reçoit ?code=XXX depuis le callback Flask,
 * échange le code contre les JWT, puis navigue vers la bonne destination.
 */
@Component({
  selector: 'app-oauth-callback',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="oauth-loading">
      @if (error()) {
        <div class="oauth-error">
          <i class="bi bi-exclamation-triangle"></i>
          {{ error() }}
          <a href="/login" class="back-link">Retour à la connexion</a>
        </div>
      } @else {
        <div class="spinner-border text-primary" role="status"></div>
        <p>Connexion en cours…</p>
      }
    </div>
  `,
  styles: [`
    .oauth-loading {
      min-height: 100vh; display: flex; flex-direction: column;
      align-items: center; justify-content: center; gap: 1rem;
      background: #1a1d20; color: #adb5bd; font-size: 0.9rem;
    }
    .oauth-error {
      display: flex; flex-direction: column; align-items: center; gap: 0.75rem;
      color: #dc3545; font-size: 0.9rem;
      i { font-size: 2rem; }
    }
    .back-link { color: #0d6efd; text-decoration: none; margin-top: 0.5rem; }
  `],
})
export class OauthCallbackComponent implements OnInit {

  error = signal<string | null>(null);

  constructor(
    private route:  ActivatedRoute,
    private router: Router,
    private auth:   AuthService,
  ) {}

  ngOnInit(): void {
    // Vérifier les erreurs retournées par Flask
    const urlError = this.route.snapshot.queryParamMap.get('error');
    if (urlError) {
      const messages: Record<string, string> = {
        account_deleted: 'Ce compte a été supprimé.',
        oauth_conflict:  'Cet email est déjà lié à un autre fournisseur.',
        oauth_failed:    'Échec de la connexion Google. Réessayez.',
      };
      this.error.set(messages[urlError] ?? 'Erreur de connexion.');
      return;
    }

    const code = this.route.snapshot.queryParamMap.get('code');
    if (!code) {
      this.error.set('Code OAuth manquant.');
      return;
    }

    this.auth.tokenExchange(code).subscribe({
      next: (res) => {
        if (!res.success || !res.data) {
          this.error.set(res.feedback?.message ?? 'Code invalide ou expiré.');
          return;
        }
        this.auth.storeOauthAuth(res.data);
        this.navigate(res.data.next, res.data.suggested_name);
      },
      error: () => {
        this.error.set('Erreur serveur lors de l\'échange OAuth.');
      },
    });
  }

  private navigate(next: string, suggestedName: string): void {
    switch (next) {
      case 'complete-profile':
        this.router.navigate(['/complete-profile'], {
          queryParams: suggestedName ? { name: suggestedName } : {},
        });
        break;
      case 'select-role':
        this.router.navigate(['/select-role']);
        break;
      default:
        this.router.navigate(['/']);
    }
  }
}
