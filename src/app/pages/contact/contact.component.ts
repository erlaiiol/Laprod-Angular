import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { UserService } from '../../services/user.service';
import { AuthService } from '../../services/auth.service';

const CONTACT_REASONS: Record<string, string> = {
  contract_error:     'Erreur dans la création du contrat',
  download_error:     'Impossible de télécharger le fichier audio',
  mixmaster_download: 'Problème lors du téléchargement de mon mix/master',
};

@Component({
  selector: 'app-contact',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './contact.component.html',
  styleUrl:    './contact.component.scss',
})
export class ContactComponent implements OnInit {

  subject = signal('');
  message = signal('');
  ref     = signal('');

  loading = signal(false);
  error   = signal<string | null>(null);
  success = signal(false);

  canSubmit = computed(() =>
    !!this.subject().trim() && !!this.message().trim() && !this.loading(),
  );

  constructor(
    private route:   ActivatedRoute,
    private router:  Router,
    private userSvc: UserService,
    readonly auth:   AuthService,
  ) {}

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.route.queryParamMap.subscribe(params => {
      const reason = params.get('reason') ?? '';
      const ref    = params.get('ref')    ?? '';
      this.subject.set(CONTACT_REASONS[reason] ?? '');
      this.ref.set(ref);
    });
  }

  onSubmit(): void {
    if (!this.canSubmit()) return;
    this.loading.set(true);
    this.error.set(null);

    this.userSvc.sendContact(this.subject(), this.message(), this.ref()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success) {
          this.success.set(true);
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur lors de l\'envoi.');
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur. Réessayez ou écrivez à contact@laprod.net.');
      },
    });
  }

  reset(): void {
    this.subject.set('');
    this.message.set('');
    this.ref.set('');
    this.success.set(false);
  }
}
