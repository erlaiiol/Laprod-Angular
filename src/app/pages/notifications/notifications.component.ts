import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { NotificationService, AppNotification } from '../../services/notification.service';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-notifications',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './notifications.component.html',
  styleUrl:    './notifications.component.scss',
})
export class NotificationsComponent implements OnInit {

  loading     = signal(true);
  error       = signal<string | null>(null);
  markingAll  = signal(false);

  constructor(
    readonly notifSvc: NotificationService,
    private auth:      AuthService,
    private router:    Router,
  ) {}

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }
    this.notifSvc.load().subscribe({
      next:  () => this.loading.set(false),
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur de chargement.');
      },
    });
  }

  markAsRead(notif: AppNotification): void {
    if (notif.is_read) {
      if (notif.link) this.router.navigateByUrl(notif.link);
      return;
    }
    this.notifSvc.markAsRead(notif.id).subscribe({
      next: res => {
        if (res.success && res.data?.link) this.router.navigateByUrl(res.data.link);
      },
      error: () => {},
    });
  }

  markAllAsRead(): void {
    this.markingAll.set(true);
    this.notifSvc.markAllAsRead().subscribe({
      next:  () => this.markingAll.set(false),
      error: () => this.markingAll.set(false),
    });
  }

  typeIcon(type: string): string {
    const icons: Record<string, string> = {
      purchase:          'bi-bag-check-fill',
      sale:              'bi-cash-coin',
      track_approved:    'bi-check-circle-fill',
      track_rejected:    'bi-x-circle-fill',
      mixmaster_request: 'bi-sliders',
      mixmaster_status:  'bi-sliders',
      tokens_recharged:  'bi-lightning-charge-fill',
      topline_submitted: 'bi-mic-fill',
      system:            'bi-info-circle-fill',
    };
    return icons[type] ?? 'bi-bell-fill';
  }

  typeColor(type: string): string {
    const colors: Record<string, string> = {
      purchase:          'blue',
      sale:              'green',
      track_approved:    'green',
      track_rejected:    'red',
      mixmaster_request: 'yellow',
      mixmaster_status:  'yellow',
      tokens_recharged:  'blue',
      topline_submitted: 'cyan',
      system:            'grey',
    };
    return colors[type] ?? 'grey';
  }

  formatDate(iso: string): string {
    const d = new Date(iso);
    const now = new Date();
    const diff = now.getTime() - d.getTime();
    const mins  = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days  = Math.floor(diff / 86400000);
    if (mins < 1)   return 'À l\'instant';
    if (mins < 60)  return `Il y a ${mins} min`;
    if (hours < 24) return `Il y a ${hours}h`;
    if (days < 7)   return `Il y a ${days}j`;
    return d.toLocaleDateString('fr-FR');
  }
}
