import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UserService } from '../../../services/user.service';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-edit-security',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './edit-security.component.html',
  styleUrl:    './edit-security.component.scss',
})
export class EditSecurityComponent implements OnInit {

  // ── Form fields ───────────────────────────────────────────────────────────
  currentPassword     = signal('');
  newUsername         = signal('');
  newPassword         = signal('');
  newPasswordConfirm  = signal('');
  newEmail            = signal('');

  // OAuth : premier mot de passe
  setPassword        = signal('');
  setPasswordConfirm = signal('');

  // ── Context ───────────────────────────────────────────────────────────────
  isOAuth     = signal(false);
  hasPassword = signal(true);
  currentUsername = signal('');

  // ── UI ────────────────────────────────────────────────────────────────────
  loading = signal(false);
  error   = signal<string | null>(null);
  success = signal<string | null>(null);

  showCurrentPwd = signal(false);
  showNewPwd     = signal(false);

  constructor(
    private userSvc: UserService,
    readonly auth:   AuthService,
    private router:  Router,
  ) {}

  ngOnInit(): void {
    const user = this.auth.currentUser();
    if (!user) { this.router.navigate(['/login']); return; }
    this.currentUsername.set(user.username);

    this.userSvc.getProfile(user.username).subscribe(res => {
      if (res.success && res.data) {
        const u = res.data.user;
        this.isOAuth.set(!!u.oauth_provider);
        this.hasPassword.set(u.has_password ?? true);
      }
    });
  }

  // ── Définir premier mot de passe (OAuth) ──────────────────────────────────
  onSetPassword(): void {
    this.loading.set(true);
    this.error.set(null);
    this.success.set(null);

    this.userSvc.updateSecurity({
      set_password:         this.setPassword(),
      set_password_confirm: this.setPasswordConfirm(),
    }).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success) {
          this.hasPassword.set(true);
          this.success.set(res.feedback.message);
          this.setPassword.set('');
          this.setPasswordConfirm.set('');
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur.');
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur.');
      },
    });
  }

  // ── Modifier username / password / email ──────────────────────────────────
  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);
    this.success.set(null);

    const payload: any = { current_password: this.currentPassword() };
    if (this.newUsername().trim())       payload.new_username = this.newUsername().trim();
    if (this.newPassword())              payload.new_password = this.newPassword();
    if (this.newPasswordConfirm())       payload.new_password_confirm = this.newPasswordConfirm();
    if (this.newEmail().trim())          payload.new_email = this.newEmail().trim();

    this.userSvc.updateSecurity(payload).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success) {
          this.success.set(res.feedback.message);
          this.currentPassword.set('');
          this.newPassword.set('');
          this.newPasswordConfirm.set('');
          if (res.data?.username) {
            this.currentUsername.set(res.data.username);
            const stored = JSON.parse(localStorage.getItem('user') ?? '{}');
            localStorage.setItem('user', JSON.stringify({ ...stored, username: res.data.username }));
          }
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur.');
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur.');
      },
    });
  }
}
