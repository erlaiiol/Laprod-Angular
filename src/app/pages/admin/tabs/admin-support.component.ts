import { Component, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { debounceTime, distinctUntilChanged, Subject, switchMap, of } from 'rxjs';
import { AdminService, UserSearchResult } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';

interface SupportTemplate {
  id:      string;
  label:   string;
  subject: string;
  body:    string;
}

const TEMPLATES: SupportTemplate[] = [
  {
    id:      'tokens',
    label:   'Tokens ajoutés',
    subject: 'Des tokens ont été ajoutés à votre compte !',
    body:
`Bonjour {username},

Nous avons le plaisir de vous informer que des tokens ont été ajoutés à votre compte LaProd.

Vous pouvez dès maintenant les utiliser pour uploader vos prochains projets.

Bonne création !

L'équipe LaProd
https://laprod.net`,
  },
  {
    id:      'bug-fixed',
    label:   'Bug corrigé',
    subject: 'Votre signalement a été traité – merci !',
    body:
`Bonjour {username},

Merci de nous avoir signalé ce bug. Nous l'avons identifié et corrigé, votre expérience sur LaProd devrait désormais être améliorée.

Votre aide nous est précieuse pour faire évoluer la plateforme.

Cordialement,
L'équipe LaProd
https://laprod.net`,
  },
  {
    id:      'welcome',
    label:   'Bienvenue',
    subject: 'Bienvenue sur LaProd !',
    body:
`Bonjour {username},

Bienvenue sur LaProd ! Nous sommes ravis de vous compter parmi notre communauté de créatifs.

N'hésitez pas à explorer la plateforme et à nous contacter si vous avez des questions.

Bonne aventure musicale !

L'équipe LaProd
https://laprod.net`,
  },
  {
    id:      'verification',
    label:   'Vérification email',
    subject: 'Action requise : vérifiez votre adresse email',
    body:
`Bonjour {username},

Nous avons remarqué que votre adresse email n'a pas encore été vérifiée sur LaProd.

Veuillez vous rendre sur votre boîte mail et cliquer sur le lien de vérification que nous vous avons envoyé. Si vous ne le trouvez pas, n'hésitez pas à contacter notre support.

Cordialement,
L'équipe LaProd
https://laprod.net`,
  },
  {
    id:      'custom',
    label:   'Message libre',
    subject: '',
    body:    '',
  },
];

@Component({
  selector: 'app-admin-support',
  standalone: true,
  imports: [CommonModule, FormsModule],
  styleUrl: '../admin.component.scss',
  template: `
<div class="support-wrap">

  <div class="support-form">

    <!-- Destinataire -->
    <section class="support-section">
      <h3 class="support-section-title"><i class="bi bi-person-lines-fill"></i> Destinataire</h3>

      <div class="recipient-search-wrap">
        <input
          class="support-input"
          type="text"
          placeholder="Rechercher un utilisateur (username)…"
          [(ngModel)]="searchQuery"
          (ngModelChange)="onSearch($event)"
          [disabled]="!!recipient()" />

        @if (recipient()) {
          <div class="recipient-pill">
            <i class="bi bi-person-circle"></i>
            <span><strong>{{ recipient()!.username }}</strong> &lt;{{ recipient()!.email }}&gt;</span>
            <button class="recipient-clear" (click)="clearRecipient()" title="Changer de destinataire">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        }

        @if (!recipient() && searchResults().length > 0) {
          <div class="search-dropdown">
            @for (u of searchResults(); track u.id) {
              <button class="search-result-item" (click)="selectUser(u)">
                <i class="bi bi-person"></i>
                <span class="search-username">{{ u.username }}</span>
                <span class="search-email">{{ u.email }}</span>
              </button>
            }
          </div>
        }

        @if (!recipient()) {
          <div class="manual-email-row">
            <span class="or-divider">ou email manuel</span>
            <input
              class="support-input support-input--inline"
              type="email"
              placeholder="exemple@email.com"
              [(ngModel)]="manualEmail" />
          </div>
        }
      </div>
    </section>

    <!-- Sélection template -->
    <section class="support-section">
      <h3 class="support-section-title"><i class="bi bi-layout-text-sidebar-reverse"></i> Template</h3>
      <div class="template-pills">
        @for (t of templates; track t.id) {
          <button
            class="template-pill"
            [class.active]="selectedTemplateId() === t.id"
            (click)="selectTemplate(t)">
            {{ t.label }}
          </button>
        }
      </div>
    </section>

    <!-- Sujet -->
    <section class="support-section">
      <h3 class="support-section-title"><i class="bi bi-pencil-square"></i> Sujet</h3>
      <input
        class="support-input"
        type="text"
        placeholder="Sujet de l'email…"
        [(ngModel)]="subject" />
    </section>

    <!-- Corps -->
    <section class="support-section">
      <h3 class="support-section-title"><i class="bi bi-card-text"></i> Corps</h3>
      <textarea
        class="support-textarea"
        rows="12"
        placeholder="Corps de l'email…"
        [(ngModel)]="body">
      </textarea>
      <p class="support-hint">
        <i class="bi bi-info-circle"></i>
        Utilisez <code>{username}</code> pour insérer le nom d'utilisateur du destinataire.
      </p>
    </section>

    <!-- Actions -->
    <div class="support-actions">
      <button
        class="btn-primary"
        [disabled]="sending() || !canSend()"
        (click)="send()">
        @if (sending()) {
          <span class="btn-spinner"></span> Envoi…
        } @else {
          <i class="bi bi-send-fill"></i> Envoyer
        }
      </button>
    </div>

  </div>

  <!-- Prévisualisation -->
  <div class="support-preview">
    <div class="preview-header">
      <i class="bi bi-eye"></i> Prévisualisation
    </div>
    <div class="preview-meta">
      <span class="preview-label">De :</span>
      <span class="preview-value">support&#64;laprod.net</span>
    </div>
    <div class="preview-meta">
      <span class="preview-label">À :</span>
      <span class="preview-value">{{ previewTo() }}</span>
    </div>
    <div class="preview-meta">
      <span class="preview-label">Sujet :</span>
      <span class="preview-value">{{ subject || '—' }}</span>
    </div>
    <div class="preview-body">{{ previewBody() }}</div>
  </div>

</div>
  `,
})
export class AdminSupportComponent {

  private adminSvc = inject(AdminService);
  private toast    = inject(ToastService);

  readonly templates = TEMPLATES;

  // Recherche utilisateur
  searchQuery   = '';
  searchResults = signal<UserSearchResult[]>([]);
  recipient     = signal<UserSearchResult | null>(null);
  manualEmail   = '';

  // Composition
  selectedTemplateId = signal<string>('tokens');
  subject            = TEMPLATES[0].subject;
  body               = TEMPLATES[0].body;

  // État
  sending = signal(false);

  private search$ = new Subject<string>();

  constructor() {
    this.search$.pipe(
      debounceTime(250),
      distinctUntilChanged(),
      switchMap(q => q.length >= 2 ? this.adminSvc.searchUsers(q) : of({ success: true, data: { users: [] } })),
    ).subscribe(res => {
      if (res.success && res.data) this.searchResults.set(res.data.users);
    });
  }

  onSearch(q: string): void {
    this.search$.next(q.trim());
  }

  selectUser(u: UserSearchResult): void {
    this.recipient.set(u);
    this.searchQuery = '';
    this.searchResults.set([]);
    this.applyUsernameToBody(u.username);
  }

  clearRecipient(): void {
    this.recipient.set(null);
    this.manualEmail = '';
    this.searchQuery = '';
  }

  selectTemplate(t: SupportTemplate): void {
    this.selectedTemplateId.set(t.id);
    this.subject = t.subject;
    const name = this.recipient()?.username ?? 'utilisateur';
    this.body = t.body.replace(/\{username\}/g, name);
  }

  private applyUsernameToBody(name: string): void {
    this.body = this.body.replace(/\{username\}/g, name);
  }

  canSend = computed(() => {
    const hasRecipient = !!this.recipient() || (this.manualEmail.trim().includes('@'));
    return hasRecipient && !!this.subject.trim() && !!this.body.trim() && !this.sending();
  });

  previewTo = computed(() => {
    const r = this.recipient();
    if (r) return `${r.username} <${r.email}>`;
    return this.manualEmail.trim() || '—';
  });

  previewBody = computed(() => {
    const name = this.recipient()?.username ?? 'utilisateur';
    return this.body.replace(/\{username\}/g, name);
  });

  send(): void {
    const r = this.recipient();
    const email = r?.email ?? this.manualEmail.trim();
    const name  = r?.username ?? email;
    if (!email || !this.subject.trim() || !this.body.trim()) return;

    this.sending.set(true);
    this.adminSvc.sendSupportEmail({
      email,
      name,
      subject: this.subject,
      body:    this.previewBody(),
    }).subscribe({
      next: res => {
        this.sending.set(false);
        if (res.success) {
          this.toast.showToast({ level: 'success', message: res.feedback?.message ?? `Email envoyé à ${email}.` });
          this.clearRecipient();
          this.subject = '';
          this.body    = '';
          this.selectedTemplateId.set('custom');
        }
      },
      error: err => {
        this.sending.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur lors de l\'envoi.' });
      },
    });
  }
}
