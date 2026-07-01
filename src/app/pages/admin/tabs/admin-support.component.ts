import { Component, signal, computed, inject, OnInit } from '@angular/core';
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
    id:      'update',
    label:   'Mise à jour',
    subject: '🎉 Nouveautés sur LaProd !',
    body:
`Bonjour {username},

Nous avons le plaisir de vous annoncer une nouvelle mise à jour de LaProd !

[Décrivez ici les nouvelles fonctionnalités ou améliorations.]

Merci de faire partie de la communauté LaProd.

L'équipe LaProd
https://laprod.net`,
  },
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

    <!-- Toggle mode : individuel / broadcast -->
    <section class="support-section">
      <div class="mode-toggle-wrap">
        <button class="mode-toggle-btn" [class.active]="mode() === 'individual'"
                (click)="setMode('individual')">
          <i class="bi bi-person-fill"></i> Individuel
        </button>
        <button class="mode-toggle-btn" [class.active]="mode() === 'broadcast'"
                (click)="setMode('broadcast')">
          <i class="bi bi-megaphone-fill"></i> Tous les utilisateurs actifs
        </button>
      </div>
    </section>

    <!-- Destinataire (mode individuel) -->
    @if (mode() === 'individual') {
      <section class="support-section">
        <h3 class="support-section-title"><i class="bi bi-person-lines-fill"></i> Destinataire</h3>

        <div class="recipient-search-wrap">
          @if (recipient()) {
            <div class="recipient-pill">
              <i class="bi bi-person-circle"></i>
              <span><strong>{{ recipient()!.username }}</strong> &lt;{{ recipient()!.email }}&gt;</span>
              <button class="recipient-clear" (click)="clearRecipient()" title="Changer de destinataire">
                <i class="bi bi-x-lg"></i>
              </button>
            </div>
          } @else {
            <input
              class="support-input"
              type="text"
              placeholder="Rechercher un utilisateur ou saisir un email directement…"
              [(ngModel)]="searchQuery"
              (ngModelChange)="onSearch($event)" />

            @if (searchResults().length > 0) {
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

            <p class="support-hint" style="margin-top:0.35rem">
              <i class="bi bi-info-circle"></i>
              Sélectionnez un utilisateur dans la liste, ou saisissez directement une adresse email et cliquez sur Envoyer.
            </p>
          }
        </div>
      </section>
    }

    <!-- Info broadcast -->
    @if (mode() === 'broadcast') {
      <section class="support-section">
        <h3 class="support-section-title"><i class="bi bi-people-fill"></i> Destinataires</h3>
        <div class="broadcast-info">
          <i class="bi bi-megaphone-fill"></i>
          @if (broadcastCount() !== null) {
            <span>
              Cet email sera envoyé à
              <strong>{{ broadcastCount() }} utilisateur{{ broadcastCount()! > 1 ? 's' : '' }}</strong>
              actifs avec email vérifié.
            </span>
          } @else {
            <span class="text-muted">Chargement du nombre de destinataires…</span>
          }
        </div>
        <p class="support-hint">
          <i class="bi bi-info-circle"></i>
          <code>&#123;username&#125;</code> sera remplacé par le vrai nom de chaque destinataire côté serveur.
        </p>
      </section>
    }

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
        Utilisez <code>&#123;username&#125;</code> pour insérer le nom d'utilisateur du destinataire.
      </p>
    </section>

    <!-- Confirmation broadcast -->
    @if (mode() === 'broadcast' && confirmStep()) {
      <div class="broadcast-confirm">
        <i class="bi bi-exclamation-triangle-fill"></i>
        <span>
          Vous êtes sur le point d'envoyer cet email à
          <strong>{{ broadcastCount() }} utilisateur(s)</strong>.
          Cette action est irréversible.
        </span>
        <div class="broadcast-confirm-actions">
          <button class="btn-confirm-cancel" (click)="confirmStep.set(false)">Annuler</button>
          <button class="btn-confirm-send" [disabled]="sending()" (click)="executeBroadcast()">
            @if (sending()) {
              <span class="btn-spinner"></span> Envoi en cours…
            } @else {
              <i class="bi bi-send-fill"></i> Confirmer l'envoi
            }
          </button>
        </div>
      </div>
    }

    <!-- Actions -->
    @if (!confirmStep()) {
      <div class="support-actions">
        <button
          class="btn-primary"
          [disabled]="sending() || !canSend()"
          (click)="onSendClick()">
          @if (sending()) {
            <span class="btn-spinner"></span> Envoi…
          } @else if (mode() === 'broadcast') {
            <i class="bi bi-megaphone-fill"></i> Préparer l'envoi groupé
          } @else {
            <i class="bi bi-send-fill"></i> Envoyer
          }
        </button>
      </div>
    }

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
export class AdminSupportComponent implements OnInit {

  private adminSvc = inject(AdminService);
  private toast    = inject(ToastService);

  readonly templates = TEMPLATES;

  // Mode : individuel ou broadcast
  mode = signal<'individual' | 'broadcast'>('individual');

  // Broadcast
  broadcastCount = signal<number | null>(null);
  confirmStep    = signal(false);

  // Recherche utilisateur / email direct
  searchQuery   = '';
  searchResults = signal<UserSearchResult[]>([]);
  recipient     = signal<UserSearchResult | null>(null);

  // Composition
  selectedTemplateId = signal<string>('tokens');
  subject            = TEMPLATES[0].subject;
  body               = TEMPLATES[0].body;

  // État
  sending = signal(false);

  private search$ = new Subject<string>();

  ngOnInit(): void {
    this.loadBroadcastCount();
  }

  constructor() {
    this.search$.pipe(
      debounceTime(250),
      distinctUntilChanged(),
      switchMap(q => q.length >= 2 ? this.adminSvc.searchUsers(q) : of({ success: true, data: { users: [] } })),
    ).subscribe(res => {
      if (res.success && res.data) this.searchResults.set(res.data.users);
    });
  }

  private loadBroadcastCount(): void {
    this.adminSvc.getBroadcastPreview().subscribe({
      next: res => { if (res.success && res.data) this.broadcastCount.set(res.data.count); },
    });
  }

  setMode(m: 'individual' | 'broadcast'): void {
    this.mode.set(m);
    this.confirmStep.set(false);
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
    this.searchQuery = '';
    this.searchResults.set([]);
  }

  selectTemplate(t: SupportTemplate): void {
    this.selectedTemplateId.set(t.id);
    this.subject = t.subject;
    const name = this.mode() === 'broadcast'
      ? '{username}'
      : (this.recipient()?.username ?? 'utilisateur');
    this.body = t.body.replace(/\{username\}/g, name);
  }

  private applyUsernameToBody(name: string): void {
    this.body = this.body.replace(/\{username\}/g, name);
  }

  canSend = computed(() => {
    if (this.sending()) return false;
    if (!this.subject.trim() || !this.body.trim()) return false;
    if (this.mode() === 'broadcast') return (this.broadcastCount() ?? 0) > 0;
    const hasRecipient = !!this.recipient() || this.searchQuery.trim().includes('@');
    return hasRecipient;
  });

  previewTo = computed(() => {
    if (this.mode() === 'broadcast') {
      const n = this.broadcastCount();
      return n !== null ? `${n} utilisateurs actifs` : 'Tous les utilisateurs actifs';
    }
    const r = this.recipient();
    if (r) return `${r.username} <${r.email}>`;
    return this.searchQuery.trim() || '—';
  });

  previewBody = computed(() => {
    if (this.mode() === 'broadcast') return this.body;
    const name = this.recipient()?.username ?? 'utilisateur';
    return this.body.replace(/\{username\}/g, name);
  });

  onSendClick(): void {
    if (this.mode() === 'broadcast') {
      this.confirmStep.set(true);
    } else {
      this.sendIndividual();
    }
  }

  private sendIndividual(): void {
    const r     = this.recipient();
    const email = r?.email ?? this.searchQuery.trim();
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
      error: () => {
        this.sending.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors de l\'envoi.' });
      },
    });
  }

  executeBroadcast(): void {
    if (!this.subject.trim() || !this.body.trim()) return;
    this.sending.set(true);
    this.adminSvc.broadcastEmail({ subject: this.subject, body: this.body }).subscribe({
      next: res => {
        this.sending.set(false);
        this.confirmStep.set(false);
        if (res.success) {
          this.toast.showToast({ level: 'success', message: res.feedback?.message ?? 'Emails envoyés.' });
          this.subject = '';
          this.body    = '';
          this.selectedTemplateId.set('custom');
          this.loadBroadcastCount();
        }
      },
      error: () => {
        this.sending.set(false);
        this.confirmStep.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors de l\'envoi groupé.' });
      },
    });
  }
}
