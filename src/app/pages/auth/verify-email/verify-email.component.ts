import { ChangeDetectionStrategy, Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, ActivatedRoute } from '@angular/router';
import { AuthService } from '../../../services/auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-verify-email',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './verify-email.component.html',
  styleUrl: './verify-email.component.scss',
})
export class VerifyEmailComponent implements OnInit {

  state = signal<'loading' | 'success' | 'expired' | 'error'>('loading');
  message = signal<string>('');

  private route    = inject(ActivatedRoute);
  private authSvc  = inject(AuthService);

  ngOnInit(): void {
    const token = this.route.snapshot.queryParamMap.get('token');
    if (!token) {
      this.state.set('error');
      this.message.set('Lien invalide.');
      return;
    }

    this.authSvc.verifyEmail(token).subscribe({
      next: (res: any) => {
        this.state.set('success');
        this.message.set(res?.feedback?.message ?? 'Email vérifié avec succès.');
      },
      error: (err: any) => {
        if (err?.error?.code === 'TOKEN_EXPIRED') {
          this.state.set('expired');
          this.message.set('Lien expiré. Demandez un nouveau lien depuis la page d\'inscription.');
        } else {
          this.state.set('error');
          this.message.set(err?.error?.feedback?.message ?? 'Une erreur est survenue.');
        }
      },
    });
  }
}
