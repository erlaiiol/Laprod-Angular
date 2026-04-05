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

  staticBase = `${environment.apiUrl.replace('/api', '')}/static/`;

  loading    = signal(false);
  users      = signal<AdminUser[]>([]);
  userType   = signal<'all' | 'beatmakers' | 'artists' | 'engineers'>('all');
  counts     = signal<Record<string, number>>({});

  // Token modal
  tokenUser   = signal<AdminUser | null>(null);
  tokenType   = signal<'track' | 'topline'>('track');
  tokenAmount = signal(1);

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

  togglePremium(user: AdminUser): void {
    this.adminSvc.togglePremium(user.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
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

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR');
  }
}
