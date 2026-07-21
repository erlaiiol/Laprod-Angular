import { ChangeDetectionStrategy, Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../../services/auth.service';
import {
  DashboardService, MixEngineerDashboard, MixOrder,
} from '../../../services/dashboard.service';
import { MixmasterService } from '../../../services/mixmaster.service';
import { PlayerService } from '../../../services/player.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';
import { FormatDatePipe } from '../../../pipes/format-date.pipe';
import { MarketingPanelComponent } from '../../../components/marketing-panel/marketing-panel.component';

type Tab = 'awaiting' | 'active' | 'revisions' | 'completed' | 'refused' | 'marketing';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-dashboard-mix-engineer',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, FormatDatePipe, MarketingPanelComponent],
  templateUrl: './dashboard-mix-engineer.component.html',
  styleUrls: ['./dashboard-mix-engineer.component.scss'],
})
export class DashboardMixEngineerComponent implements OnInit, OnDestroy {

  loading      = signal(true);
  error        = signal<string | null>(null);
  data         = signal<MixEngineerDashboard | null>(null);
  activeTab    = signal<Tab>('awaiting');
  actionInProgress = signal<number | null>(null);

  // Upload state (mix orders)
  uploadOrderId  = signal<number | null>(null);
  uploadFile     = signal<File | null>(null);
  uploading      = signal(false);

  // Pro preview update
  uploadPreviewRaw  = signal<File | null>(null);
  uploadPreviewProc = signal<File | null>(null);
  uploadingPreview = signal(false);

  // Briefing panel
  expandedOrderId = signal<number | null>(null);

  // Vues de la page d'ingénieur : total (gratuit) + uniques (Premium).
  viewStats = signal<{ total_views: number; unique_views: number | null; unique_locked: boolean } | null>(null);

  // Blob URLs gérés localement (libérés dans ngOnDestroy)
  private blobUrls = new Map<string, string>();

  readonly auth    = inject(AuthService);
  readonly player  = inject(PlayerService);
  private dashSvc  = inject(DashboardService);
  private mixSvc   = inject(MixmasterService);
  private router   = inject(Router);
  private toast    = inject(ToastService);
  private http     = inject(HttpClient);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }
    this.loadDashboard();
    this.mixSvc.getMyEngineerViewStats().subscribe({
      next: res => this.viewStats.set(res.data ?? null),
      error: () => {},
    });
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
    const tab = this.activeTab();
    // « marketing » n'est pas un panier de commandes : c'est un onglet à part
    // entière. On le sort explicitement plutôt que d'indexer d.orders à l'aveugle.
    return tab === 'marketing' ? [] : d.orders[tab];
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
        if (res.success) this.loadDashboard();
        this.actionInProgress.set(null);
      },
      error: (err) => {
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' });
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
        if (res.success) this.loadDashboard();
        this.actionInProgress.set(null);
      },
      error: (err) => {
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' });
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
        if (res.success) { this.uploadOrderId.set(null); this.loadDashboard(); }
        this.uploading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur upload.' });
        this.uploading.set(false);
      },
    });
  }

  cancelUpload(): void { this.uploadOrderId.set(null); this.uploadFile.set(null); }

  // ── Pro preview update ────────────────────────────────────────────────────

  onPreviewFileChange(field: 'raw' | 'proc', event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (field === 'raw') this.uploadPreviewRaw.set(file);
    else                 this.uploadPreviewProc.set(file);
  }

  submitPreviewUpdate(): void {
    if (!this.uploadPreviewRaw() && !this.uploadPreviewProc()) return;
    this.uploadingPreview.set(true);
    const fd = new FormData();
    const previewRaw = this.uploadPreviewRaw();
    if (previewRaw)  fd.append('sample_raw', previewRaw);
    const previewProc = this.uploadPreviewProc();
    if (previewProc) fd.append('sample_processed', previewProc);
    this.http.post<any>(
      `${environment.apiUrl}/api/premium/update-mix-previews`, fd,
      { headers: { Authorization: `Bearer ${this.auth.getToken()}` } },
    ).subscribe({
      next: (res) => {
        this.uploadingPreview.set(false);
        if (res.success) {
          this.uploadPreviewRaw.set(null);
          this.uploadPreviewProc.set(null);
          this.toast.showToast({ level: 'success', message: 'Previews mis à jour.' });
        }
      },
      error: (err) => {
        this.uploadingPreview.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur lors de la mise à jour.' });
      },
    });
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/db_assets/${path}` : '/assets/placeholders/default_profile.png';
  }

  fileUrl(url: string | null): string {
    return url ? `${environment.apiUrl}${url}` : '';
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

  // ── Fichiers protégés ─────────────────────────────────────────────────────

  /** Ouvre la référence audio dans le player global (JWT → Blob URL → PlayerService). */
  playReference(order: MixOrder): void {
    // Si déjà en train de jouer cette référence → toggle play/pause
    const existingUrl = this.blobUrls.get(`${order.id}_reference`);
    if (existingUrl && this.player.currentTrack()?.stream_url === existingUrl) {
      this.player.togglePlay();
      return;
    }

    const url = `${environment.apiUrl}/api/mixmaster-media/${order.id}/reference`;
    this.http.get(url, {
      headers: { Authorization: `Bearer ${this.auth.getToken()}` },
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        const blobUrl = URL.createObjectURL(blob);
        this.blobUrls.set(`${order.id}_reference`, blobUrl);
        this.player.playMixAudio(blobUrl, {
          orderId:    order.id,
          orderTitle: order.title,
          status:     order.status,
          personName: order.artist_username,
        });
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de charger la référence.' }),
    });
  }

  isPlayingReference(order: MixOrder): boolean {
    const url = this.blobUrls.get(`${order.id}_reference`);
    return !!url && this.player.currentTrack()?.stream_url === url && this.player.isPlaying();
  }

  /** Télécharge les stems via JWT. */
  downloadMedia(order: MixOrder): void {
    const key = `${order.id}_original`;
    const existing = this.blobUrls.get(key);

    const triggerDownload = (blobUrl: string) => {
      const a = document.createElement('a');
      a.href = blobUrl;
      a.download = `stems_${order.title}_${order.id}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    };

    if (existing) { triggerDownload(existing); return; }

    const url = `${environment.apiUrl}/api/mixmaster-media/${order.id}/original`;
    this.http.get(url, {
      headers: { Authorization: `Bearer ${this.auth.getToken()}` },
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        const blobUrl = URL.createObjectURL(blob);
        this.blobUrls.set(key, blobUrl);
        triggerDownload(blobUrl);
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de télécharger les stems.' }),
    });
  }

  ngOnDestroy(): void {
    this.blobUrls.forEach(url => URL.revokeObjectURL(url));
    this.blobUrls.clear();
  }
}
