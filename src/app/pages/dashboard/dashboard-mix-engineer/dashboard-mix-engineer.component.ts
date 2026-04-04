import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { AuthService } from '../../../services/auth.service';
import {
  DashboardService, MixEngineerDashboard, MixOrder,
} from '../../../services/dashboard.service';
import { MixmasterService } from '../../../services/mixmaster.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

type Tab = 'awaiting' | 'active' | 'revisions' | 'completed' | 'refused';

@Component({
  selector: 'app-dashboard-mix-engineer',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './dashboard-mix-engineer.component.html',
  styleUrls: ['./dashboard-mix-engineer.component.scss'],
})
export class DashboardMixEngineerComponent implements OnInit {

  loading      = signal(true);
  error        = signal<string | null>(null);
  data         = signal<MixEngineerDashboard | null>(null);
  activeTab    = signal<Tab>('awaiting');
  actionInProgress = signal<number | null>(null);

  // Upload state
  uploadOrderId  = signal<number | null>(null);
  uploadFile     = signal<File | null>(null);
  uploading      = signal(false);

  // Briefing panel
  expandedOrderId = signal<number | null>(null);

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
    this.dashSvc.getMixEngineerDashboard().subscribe({
      next: (res) => {
        if (res.success) this.data.set(res.data!);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger l\'espace mix engineer.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger l\'espace mix engineer.');
        this.loading.set(false);
      },
    });
  }

  setTab(tab: Tab): void { this.activeTab.set(tab); }

  currentOrders(): MixOrder[] {
    const d = this.data();
    if (!d) return [];
    return d.orders[this.activeTab()];
  }

  toggleBriefing(orderId: number): void {
    this.expandedOrderId.set(this.expandedOrderId() === orderId ? null : orderId);
  }

  // ── Actions ──────────────────────────────────────────────────────────────

  accept(orderId: number): void {
    if (this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.acceptOrder(orderId).subscribe({
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

  reject(orderId: number): void {
    if (!confirm('Refuser cette commande ? Le paiement sera annulé.')) return;
    if (this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.rejectOrder(orderId).subscribe({
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

  openUpload(orderId: number): void {
    this.uploadOrderId.set(orderId);
    this.uploadFile.set(null);
  }

  onUploadFileChange(ev: Event): void {
    const f = (ev.target as HTMLInputElement).files?.[0] ?? null;
    this.uploadFile.set(f);
  }

  submitUpload(isRevision = false): void {
    const orderId = this.uploadOrderId();
    const file    = this.uploadFile();
    if (!orderId || !file) return;
    const fd = new FormData();
    fd.append('processed_file', file);
    this.uploading.set(true);
    const obs = isRevision
      ? this.mixSvc.deliverRevision(orderId, fd)
      : this.mixSvc.uploadProcessed(orderId, fd);
    obs.subscribe({
      next: (res) => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) { this.uploadOrderId.set(null); this.loadDashboard(); }
        this.uploading.set(false);
      },
      error: (err) => {
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur upload.' });
        this.uploading.set(false);
      },
    });
  }

  cancelUpload(): void { this.uploadOrderId.set(null); this.uploadFile.set(null); }

  // ── Helpers ───────────────────────────────────────────────────────────────

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-avatar.png';
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

  servicesList(order: MixOrder): string[] {
    const list: string[] = [];
    if (order.services.cleaning)  list.push('Nettoyage');
    if (order.services.effects)   list.push('Effets');
    if (order.services.artistic)  list.push('Direction artistique');
    if (order.services.mastering) list.push('Mastering');
    return list;
  }

  isRevisionTab(): boolean {
    return this.activeTab() === 'revisions';
  }
}
