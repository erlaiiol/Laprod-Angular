import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminService, AdminContract, UserSearchResult, TrackSearchResult } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';

@Component({
  selector: 'app-admin-contracts',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-contracts.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminContractsComponent implements OnInit {

  loading           = signal(false);
  contracts         = signal<AdminContract[]>([]);
  revenue           = signal(0);
  exclusiveCount    = signal(0);
  nonExclusiveCount = signal(0);

  // ── Create modal ────────────────────────────────────────────────────────────
  showModal     = signal(false);
  submitting    = signal(false);

  buyerQuery    = signal('');
  buyerResults  = signal<UserSearchResult[]>([]);
  selectedBuyer = signal<UserSearchResult | null>(null);

  trackQuery    = signal('');
  trackResults  = signal<TrackSearchResult[]>([]);
  selectedTrack = signal<TrackSearchResult | null>(null);

  formPrice       = signal(0);
  formIsExclusive = signal(false);
  formTerritory   = signal('France');
  formDuration    = signal('3 ans');

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.loadContracts(); }

  loadContracts(): void {
    this.loading.set(true);
    this.adminSvc.getContracts().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.contracts.set(res.data.contracts);
          this.revenue.set(res.data.total_revenue);
          this.exclusiveCount.set(res.data.exclusive_count);
          this.nonExclusiveCount.set(res.data.non_exclusive_count);
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement contrats.' });
      },
    });
  }

  openModal(): void {
    this.selectedBuyer.set(null);
    this.selectedTrack.set(null);
    this.buyerQuery.set('');
    this.trackQuery.set('');
    this.buyerResults.set([]);
    this.trackResults.set([]);
    this.formPrice.set(0);
    this.formIsExclusive.set(false);
    this.formTerritory.set('France');
    this.formDuration.set('3 ans');
    this.showModal.set(true);
  }

  searchBuyer(): void {
    const q = this.buyerQuery().trim();
    if (q.length < 2) { this.buyerResults.set([]); return; }
    this.adminSvc.searchUsers(q).subscribe({
      next: res => { if (res.success && res.data) this.buyerResults.set(res.data.users); },
      error: () => {},
    });
  }

  selectBuyer(u: UserSearchResult): void {
    this.selectedBuyer.set(u);
    this.buyerQuery.set(u.username);
    this.buyerResults.set([]);
  }

  searchTrack(): void {
    const q = this.trackQuery().trim();
    if (q.length < 2) { this.trackResults.set([]); return; }
    this.adminSvc.searchTracks(q).subscribe({
      next: res => { if (res.success && res.data) this.trackResults.set(res.data.tracks); },
      error: () => {},
    });
  }

  selectTrack(t: TrackSearchResult): void {
    this.selectedTrack.set(t);
    this.trackQuery.set(t.title);
    this.trackResults.set([]);
    if (!this.formPrice()) {
      this.formPrice.set(t.price_mp3 ?? 0);
    }
  }

  submitCreate(): void {
    const buyer = this.selectedBuyer();
    const track = this.selectedTrack();
    if (!buyer || !track) {
      this.toast.showToast({ level: 'error', message: 'Sélectionnez un acheteur et un track.' });
      return;
    }
    if (!this.formPrice() || this.formPrice() <= 0) {
      this.toast.showToast({ level: 'error', message: 'Prix invalide.' });
      return;
    }
    this.submitting.set(true);
    this.adminSvc.createContract({
      track_id:     track.id,
      client_id:    buyer.id,
      price:        this.formPrice(),
      is_exclusive: this.formIsExclusive(),
      territory:    this.formTerritory(),
      duration:     this.formDuration(),
    }).subscribe({
      next: res => {
        this.submitting.set(false);
        if (res.success) { this.showModal.set(false); this.loadContracts(); }
      },
      error: err => {
        this.submitting.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur création contrat.' });
      },
    });
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR');
  }
}
