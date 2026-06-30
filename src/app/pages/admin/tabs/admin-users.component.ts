import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Observable } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { AdminService, AdminUser } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-admin-users',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-users.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminUsersComponent implements OnInit {

  staticBase = `/db_assets/`;

  loading    = signal(false);
  users      = signal<AdminUser[]>([]);
  userType   = signal<'all' | 'beatmakers' | 'artists' | 'engineers'>('all');
  counts     = signal<Record<string, number>>({});

  // Token modal
  tokenUser   = signal<AdminUser | null>(null);
  tokenType   = signal<'track' | 'topline'>('track');
  tokenAmount = signal(1);

  // Delete modal
  deleteTarget    = signal<AdminUser | null>(null);
  deleteSubmitting = signal(false);

  // Resend email
  resendingId    = signal<number | null>(null);
  forcingVerifId = signal<number | null>(null);

  // Plan modal
  planUser       = signal<AdminUser | null>(null);
  planTarget     = signal<'free' | 'amateur' | 'pro'>('amateur');
  planSubmitting = signal(false);
  readonly planOptions: ('free' | 'amateur' | 'pro')[] = ['free', 'amateur', 'pro'];

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getUsers(this.userType()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.users.set(res.data.users);
          this.counts.set(res.data.counts);
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement utilisateurs.' });
      },
    });
  }

  setType(type: 'all' | 'beatmakers' | 'artists' | 'engineers'): void {
    this.userType.set(type);
    this.load();
  }

  toggleStatus(user: AdminUser): void {
    this.adminSvc.toggleUserStatus(user.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  toggleRole(user: AdminUser, role: string): void {
    this.adminSvc.toggleUserRole(user.id, role).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  openPlanModal(user: AdminUser): void {
    this.planUser.set(user);
    const current = user.subscription_plan ?? 'free';
    // Proposer le plan suivant par défaut (logique ascendante)
    if (current === 'free')         this.planTarget.set('amateur');
    else if (current === 'amateur') this.planTarget.set('pro');
    else                            this.planTarget.set('free');
  }

  closePlanModal(): void {
    this.planUser.set(null);
    this.planSubmitting.set(false);
  }

  confirmSetPlan(): void {
    const user = this.planUser();
    if (!user) return;
    this.planSubmitting.set(true);
    this.adminSvc.setPlan(user.id, this.planTarget()).subscribe({
      next: res => {
        this.planSubmitting.set(false);
        if (res.success) { this.closePlanModal(); this.load(); }
      },
      error: err => {
        this.planSubmitting.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur changement de plan.' });
      },
    });
  }

  openTokenModal(user: AdminUser, type: 'track' | 'topline'): void {
    this.tokenUser.set(user);
    this.tokenType.set(type);
    this.tokenAmount.set(1);
  }

  submitTokens(): void {
    const user = this.tokenUser();
    if (!user) return;
    const obs: Observable<any> = this.tokenType() === 'track'
      ? this.adminSvc.addTrackTokens(user.id, this.tokenAmount())
      : this.adminSvc.addToplineTokens(user.id, this.tokenAmount());
    obs.subscribe({
      next: (res: any) => {
        if (res.success) { this.tokenUser.set(null); this.load(); }
      },
      error: (err: any) => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  resendVerification(user: AdminUser): void {
    this.resendingId.set(user.id);
    this.adminSvc.resendVerificationEmail(user.id).subscribe({
      next: res => {
        this.resendingId.set(null);
        if (res.success) this.toast.showToast({ level: 'success', message: `Email de vérification renvoyé à ${user.email}.` });
      },
      error: err => {
        this.resendingId.set(null);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur lors du renvoi.' });
      },
    });
  }

  forceVerifyEmail(user: AdminUser): void {
    this.forcingVerifId.set(user.id);
    this.adminSvc.forceVerifyEmail(user.id).subscribe({
      next: res => {
        this.forcingVerifId.set(null);
        if (res.success) {
          this.toast.showToast({ level: 'success', message: `Email de ${user.username} marqué comme vérifié.` });
          this.load();
        }
      },
      error: err => {
        this.forcingVerifId.set(null);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur lors de la vérification forcée.' });
      },
    });
  }

  openDeleteModal(user: AdminUser): void {
    this.deleteTarget.set(user);
  }

  confirmDelete(): void {
    const user = this.deleteTarget();
    if (!user) return;
    this.deleteSubmitting.set(true);
    this.adminSvc.deleteUser(user.id).subscribe({
      next: res => {
        this.deleteSubmitting.set(false);
        if (res.success) {
          this.deleteTarget.set(null);
          this.toast.showToast({ level: 'success', message: `Compte de ${user.username} supprimé.` });
          this.load();
        }
      },
      error: err => {
        this.deleteSubmitting.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur lors de la suppression.' });
      },
    });
  }

  daysRemaining(expiresAt: string | null): number | null {
    if (!expiresAt) return null;
    const diff = new Date(expiresAt).getTime() - Date.now();
    return Math.max(0, Math.ceil(diff / 86_400_000));
  }

  planLabel(plan: 'free' | 'amateur' | 'pro' | null): string {
    if (plan === 'amateur') return 'Amateur';
    if (plan === 'pro')     return 'Pro';
    return 'Free';
  }

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR');
  }
}
