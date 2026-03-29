import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { finalize } from 'rxjs';

@Component({
  selector: 'app-complete-profile',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './complete-profile.component.html',
  styleUrl: './complete-profile.component.scss',
})
export class CompleteProfileComponent implements OnInit {

  username    = '';
  signature   = '';
  acceptTerms = false;

  loading = signal(false);
  error   = signal<string | null>(null);

  constructor(
    private route:  ActivatedRoute,
    private router: Router,
    private auth:   AuthService,
  ) {}

  ngOnInit(): void {
    // Pré-remplir la signature avec le prénom Google si disponible
    const suggested = this.route.snapshot.queryParamMap.get('name') ?? '';
    if (suggested) this.signature = suggested;
  }

  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);

    this.auth.completeOauthProfile(this.username, this.signature, this.acceptTerms)
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: (res) => {
          if (res.success && res.data) {
            this.auth.storeOauthAuth(res.data);
            const next = res.data.next;
            this.router.navigate([next === 'select-role' ? '/select-role' : '/']);
          } else {
            this.error.set(res.feedback?.message ?? 'Erreur lors de la complétion du profil.');
          }
        },
        error: (err) => {
          this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur. Réessayez.');
        },
      });
  }
}
