import { Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router, ActivatedRoute } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../../services/auth.service';
import { DashboardService, ArtistDashboard, ArtistMixRequest } from '../../../services/dashboard.service';
import { MixmasterService } from '../../../services/mixmaster.service';
import { PurchasesService, PurchasesData } from '../../../services/purchases.service';
import { PlayerService } from '../../../services/player.service';
import { ToastService } from '../../../services/toast.service';
import { LicenseService, LicenseItem } from '../../../services/license.service';
import { LicenseBadgeComponent } from '../../../components/license-badge/license-badge.component';
import { environment } from '../../../../environments/environment';

type Tab = 'toplines' | 'favorites' | 'history' | 'mixmaster' | 'purchases' | 'licenses';

@Component({
  selector: 'app-dashboard-artist',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule, LicenseBadgeComponent],
  templateUrl: './dashboard-artist.component.html',
  styleUrls: ['./dashboard-artist.component.scss'],
})
export class DashboardArtistComponent implements OnInit, OnDestroy {

  loading   = signal(true);
  error     = signal<string | null>(null);
  data      = signal<ArtistDashboard | null>(null);
  activeTab = signal<Tab>('toplines');

  revisionInput    = signal('');
  revisionOrderId  = signal<number | null>(null);
  rejectOrderId    = signal<number | null>(null);
  actionInProgress = signal<number | null>(null);

  purchases        = signal<PurchasesData | null>(null);
  purchasesLoading = signal(false);

  licenses        = signal<LicenseItem[] | null>(null);
  licensesLoading = signal(false);
  renewingId      = signal<number | null>(null);

  readonly auth        = inject(AuthService);
  readonly player      = inject(PlayerService);
  private dashSvc      = inject(DashboardService);
  private mixSvc       = inject(MixmasterService);
  private purchasesSvc = inject(PurchasesService);
  private licenseSvc   = inject(LicenseService);
  private router       = inject(Router);
  private toast        = inject(ToastService);
  private http         = inject(HttpClient);
  private route        = inject(ActivatedRoute);

  // Blob URLs gérés localement (libérés dans ngOnDestroy)
  private blobUrls = new Map<string, string>();

  ngOnInit(): void {
    
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }
    this.loadDashboard();

    // Synchronisation tab <-> query param
    this.route.queryParamMap.subscribe(params => {
      const tab = params.get('tab') as Tab | null;
      if (tab) {
        this.setTab(tab as any);
      }
    })
  }

  ngOnDestroy(): void {
    this.blobUrls.forEach(url => URL.revokeObjectURL(url));
    this.blobUrls.clear();
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

  setTab(tab: Tab): void {
    this.activeTab.set(tab);
    this.router.navigate([], { queryParams: { tab }, queryParamsHandling: 'merge' });
    if (tab === 'purchases' && !this.purchases()) {
      this.loadPurchases();
    }
    if (tab === 'licenses' && !this.licenses()) {
      this.loadLicenses();
    }
  }

  private loadPurchases(): void {
    this.purchasesLoading.set(true);
    this.purchasesSvc.getMyPurchases().subscribe({
      next: (res) => {
        if (res.success) this.purchases.set(res.data!);
        this.purchasesLoading.set(false);
      },
      error: () => {
        this.toast.showToast({ level: 'error', message: 'Impossible de charger vos achats.' });
        this.purchasesLoading.set(false);
      },
    });
  }

  private loadLicenses(): void {
    this.licensesLoading.set(true);
    this.licenseSvc.getLicenses().subscribe({
      next: (res) => {
        if (res.success) this.licenses.set(res.data?.licenses ?? []);
        this.licensesLoading.set(false);
      },
      error: () => {
        this.toast.showToast({ level: 'error', message: 'Impossible de charger vos licences.' });
        this.licensesLoading.set(false);
      },
    });
  }

  activeLicenses(): LicenseItem[] {
    return (this.licenses() ?? []).filter(l => l.license_status === 'active');
  }

  expiredLicenses(): LicenseItem[] {
    return (this.licenses() ?? []).filter(l => l.license_status === 'expired');
  }

  licenseUrgency(l: LicenseItem): 'lifetime' | 'ok' | 'soon' | 'urgent' | 'expired' {
    if (l.is_lifetime || !l.expires_at) return 'lifetime';
    const days = this.licenseSvc.daysRemaining(l.expires_at);
    return this.licenseSvc.urgency(days) as any;
  }

  renewLicense(l: LicenseItem): void {
    if (!l.track?.id) return;
    if (this.renewingId() !== null) return;
    this.renewingId.set(l.id);
    this.licenseSvc.initiateRenewal(l.track.id, l.id, {
      duration_years: l.duration_years ?? undefined,
      is_lifetime:    l.is_lifetime,
      territory:      l.territory ?? undefined,
    }).subscribe({
      next: (res) => {
        this.renewingId.set(null);
        if (res.success && res.data?.checkout_url) {
          window.location.href = res.data.checkout_url;
        }
      },
      error: (err) => {
        this.renewingId.set(null);
        const msg = err?.error?.feedback?.message ?? 'Erreur lors du renouvellement.';
        this.toast.showToast({ level: 'error', message: msg });
      },
    });
  }

  downloadLicenseContract(purchaseId: number, trackTitle: string): void {
    const url = this.licenseSvc.downloadContract(purchaseId);
    this._jwtDownload(url.replace(environment.apiUrl, ''), `contrat_${trackTitle}.pdf`, 'application/pdf');
  }

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/db_assets/${path}` : '/assets/placeholders/placeholder-track.png';
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
        if (res.success) this.loadDashboard();
        this.actionInProgress.set(null);
      },
      error: (err) => {
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' });
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
        if (res.success) { this.revisionOrderId.set(null); this.loadDashboard(); }
        this.actionInProgress.set(null);
      },
      error: (err) => {
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' });
        this.actionInProgress.set(null);
      },
    });
  }

  approveOrder(orderId: number): void {
    if (!confirm('Confirmer la validation ? Le solde restant sera versé à l\'ingénieur et vous pourrez télécharger le fichier final. Cette action est irréversible.')) return;
    if (this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.approveOrder(orderId).subscribe({
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

  openRejectDelivery(orderId: number): void {
    this.rejectOrderId.set(orderId);
  }

  confirmRejectDelivery(): void {
    const orderId = this.rejectOrderId();
    if (!orderId || this.actionInProgress() !== null) return;
    this.actionInProgress.set(orderId);
    this.mixSvc.rejectDelivery(orderId).subscribe({
      next: (res) => {
        if (res.success) {
          this.rejectOrderId.set(null);
          this.loadDashboard();
        }
        this.actionInProgress.set(null);
      },
      error: (err) => {
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur lors du refus.' });
        this.actionInProgress.set(null);
      },
    });
  }

  rejectRefundAmount(): number {
    const id = this.rejectOrderId();
    if (!id) return 0;
    return this.data()?.mm_requests.find(r => r.id === id)?.refund_amount ?? 0;
  }

  // ── Audio (JWT blob → player global) ─────────────────────────────────────

  /**
   * Charge un fichier audio via l'endpoint protégé JWT → Blob URL → player global.
   * Si le même blob est déjà dans le player, bascule play/pause.
   * mediaType : 'preview' | 'preview_full' | 'reference'
   */
  private fetchAndPlayMix(
    cacheKey:  string,
    orderId:   number,
    mediaType: string,
    order:     ArtistMixRequest,
  ): void {
    const existing = this.blobUrls.get(cacheKey);
    if (existing && this.player.currentTrack()?.stream_url === existing) {
      this.player.togglePlay();
      return;
    }
    const url = `${environment.apiUrl}/api/mixmaster-media/${orderId}/${mediaType}`;
    this.http.get(url, {
      headers:      { Authorization: `Bearer ${this.auth.getToken()}` },
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        const blobUrl = URL.createObjectURL(blob);
        this.blobUrls.set(cacheKey, blobUrl);
        this.player.playMixAudio(blobUrl, {
          orderId:    order.id,
          orderTitle: order.title,
          status:     order.status,
          personName: order.engineer_username,
        });
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Impossible de charger l\'audio.' }),
    });
  }

  playPreview(mediaType: 'preview' | 'preview_full', order: ArtistMixRequest): void {
    this.fetchAndPlayMix(`${order.id}_${mediaType}`, order.id, mediaType, order);
  }

  isPlayingPreview(orderId: number, mediaType: string): boolean {
    const url = this.blobUrls.get(`${orderId}_${mediaType}`);
    return !!url && this.player.currentTrack()?.stream_url === url && this.player.isPlaying();
  }

  playReference(order: ArtistMixRequest): void {
    this.fetchAndPlayMix(`${order.id}_reference`, order.id, 'reference', order);
  }

  isPlayingReference(order: ArtistMixRequest): boolean {
    const url = this.blobUrls.get(`${order.id}_reference`);
    return !!url && this.player.currentTrack()?.stream_url === url && this.player.isPlaying();
  }

  // ── Téléchargement final (JWT blob, anti-rip) ─────────────────────────────

  downloadFinal(orderId: number): void {
    const url = `${environment.apiUrl}/api/mixmaster-artist/download/${orderId}`;
    this.http.get(url, {
      headers:      { Authorization: `Bearer ${this.auth.getToken()}` },
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href     = blobUrl;
        a.download = `mixmaster_${orderId}.wav`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Téléchargement impossible.' }),
    });
  }

  // ── Helpers achats ────────────────────────────────────────────────────────

  formatLabel(format: string): string {
    const labels: Record<string, string> = { mp3: 'MP3', wav: 'WAV', stems: 'STEMS' };
    return labels[format] ?? format.toUpperCase();
  }

  private _jwtDownload(relativeUrl: string, filename: string, mime: string): void {
    const url = `${environment.apiUrl}${relativeUrl}`;
    this.http.get(url, {
      headers:      { Authorization: `Bearer ${this.auth.getToken()}` },
      responseType: 'blob',
    }).subscribe({
      next: (blob) => {
        const blobUrl = URL.createObjectURL(new Blob([blob], { type: mime }));
        const a = document.createElement('a');
        a.href = blobUrl; a.download = filename;
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(blobUrl), 5000);
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Téléchargement impossible.' }),
    });
  }

  downloadPurchase(p: { stream_url: string; format: string; track: { title: string } | null }): void {
    const ext  = p.format === 'stems' ? 'zip' : p.format;
    const mime = p.format === 'stems' ? 'application/zip'
               : p.format === 'wav'   ? 'audio/wav' : 'audio/mpeg';
    this._jwtDownload(p.stream_url, `${p.track?.title ?? 'beat'}.${ext}`, mime);
  }

  downloadContract(p: { contract_url: string | null; track: { title: string } | null; format: string }): void {
    if (!p.contract_url) return;
    this._jwtDownload(p.contract_url, `contrat_${p.track?.title ?? 'beat'}_${p.format}.pdf`, 'application/pdf');
  }

  downloadInvoice(p: { invoice_url: string; track: { title: string } | null }): void {
    this._jwtDownload(p.invoice_url, `facture_laprod_${p.track?.title ?? 'beat'}.pdf`, 'application/pdf');
  }
}
