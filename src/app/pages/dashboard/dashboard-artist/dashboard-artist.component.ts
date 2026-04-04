import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../services/auth.service';
import { DashboardService, ArtistDashboard, ArtistMixRequest } from '../../../services/dashboard.service';
import { MixmasterService } from '../../../services/mixmaster.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

type Tab = 'toplines' | 'favorites' | 'history' | 'mixmaster';

@Component({
  selector: 'app-dashboard-artist',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './dashboard-artist.component.html',
  styleUrls: ['./dashboard-artist.component.scss'],
})
export class DashboardArtistComponent implements OnInit {

  loading   = signal(true);
  error     = signal<string | null>(null);
  data      = signal<ArtistDashboard | null>(null);
  activeTab = signal<Tab>('toplines');

  revisionInput   = signal('');
  revisionOrderId = signal<number | null>(null);
  actionInProgress = signal<number | null>(null);

  readonly auth    = inject(AuthService);
  private dashSvc  = inject(DashboardService);
  private mixSvc   = inject(MixmasterService);
  private router   = inject(Router);
  private toast    = inject(ToastService);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }
    this.loadDashboard();
  }

  private loadDashboard(): void {
    this.dashSvc.getArtistDashboard().subscribe({
      next: (res) => {
        if (res.success) this.data.set(res.data!);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger l\'espace artiste.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger l\'espace artiste.');
        this.loading.set(false);
      },
    });
  }

  setTab(tab: Tab): void { this.activeTab.set(tab); }

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-track.png';
  }

  fileUrl(url: string | null): string {
    return url ? `${environment.apiUrl}${url}` : '';
  }

  formatDate(iso: string | null): string {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  statusLabel(status: string): string {
    const labels: Record<string, string> = {
      awaiting_acceptance: 'En attente',
      accepted:            'Acceptée',
      processing:          'En cours',
      delivered:           'Livrée',
      revision1:           'Révision 1',
      revision2:           'Révision 2',
      completed:           'Terminée',
      rejected:            'Refusée',
      refunded:            'Remboursée',
    };
    return labels[status] ?? status;
  }

  servicesList(order: ArtistMixRequest): string[] {
    const list: string[] = [];
    if (order.services.cleaning)  list.push('Nettoyage');
    if (order.services.effects)   list.push('Effets');
    if (order.services.artistic)  list.push('Direction artistique');
    if (order.services.mastering) list.push('Mastering');
    return list;
  }

  // ── Actions ──────────────────────────────────────────────────────────────

  cancelOrder(orderId: number): void {
    if (!confirm('Annuler cette commande ? Le paiement sera remboursé.')) return;
    if (this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.cancelOrder(orderId).subscribe({
      next: (res) => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadDashboard();
        this.actionInProgress.set(null);
      },
      error: (err) => {
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
        this.actionInProgress.set(null);
      },
    });
  }

  openRevision(orderId: number): void {
    this.revisionOrderId.set(orderId);
    this.revisionInput.set('');
  }

  submitRevision(): void {
    const orderId = this.revisionOrderId();
    const msg = this.revisionInput().trim();
    if (!orderId || !msg) return;
    if (this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.requestRevision(orderId, msg).subscribe({
      next: (res) => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) { this.revisionOrderId.set(null); this.loadDashboard(); }
        this.actionInProgress.set(null);
      },
      error: (err) => {
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
        this.actionInProgress.set(null);
      },
    });
  }

  approveOrder(orderId: number): void {
    if (!confirm('Approuver la livraison et finaliser la commande ?')) return;
    if (this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.approveOrder(orderId).subscribe({
      next: (res) => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadDashboard();
        this.actionInProgress.set(null);
      },
      error: (err) => {
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
        this.actionInProgress.set(null);
      },
    });
  }

  downloadUrl(orderId: number): string {
    return `${environment.apiUrl}/mixmaster-artist/download/${orderId}`;
  }
}
