import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { AdminService, AdminStats, AdminTrack, AdminUser, AdminEngineer, PriceRequest, AdminContract, AdminTransaction, AdminCategory } from '../../services/admin.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';

type Tab = 'dashboard' | 'tracks' | 'users' | 'engineers' | 'categories' | 'contracts' | 'transactions';

@Component({
  selector: 'app-admin',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin.component.html',
  styleUrl: './admin.component.scss',
})
export class AdminComponent implements OnInit {

  staticBase = `${environment.apiUrl.replace('/api', '')}/static/`;

  activeTab = signal<Tab>('dashboard');

  // ── Loading ───────────────────────────────────────────────────────────────
  loading = signal(false);

  // ── Dashboard ─────────────────────────────────────────────────────────────
  stats = signal<AdminStats | null>(null);

  // ── Tracks ────────────────────────────────────────────────────────────────
  tracks          = signal<AdminTrack[]>([]);
  trackStatus     = signal<'pending' | 'approved' | 'all'>('pending');
  pendingCount    = signal(0);
  approvedCount   = signal(0);
  editingTrack    = signal<AdminTrack | null>(null);

  // ── Users ─────────────────────────────────────────────────────────────────
  users         = signal<AdminUser[]>([]);
  userType      = signal<'all' | 'beatmakers' | 'artists' | 'engineers'>('all');
  userCounts    = signal<Record<string, number>>({});
  tokenUser     = signal<AdminUser | null>(null);
  tokenType     = signal<'track' | 'topline'>('track');
  tokenAmount   = signal(1);

  // ── Engineers ─────────────────────────────────────────────────────────────
  certifiedEngineers = signal<AdminEngineer[]>([]);
  pendingEngineers   = signal<AdminEngineer[]>([]);
  paRequests         = signal<AdminEngineer[]>([]);
  priceRequests      = signal<PriceRequest[]>([]);
  engineerTab        = signal<'pending' | 'certified' | 'price' | 'pa'>('pending');
  priceEditId        = signal<number | null>(null);
  priceEditMin       = signal<number>(0);
  priceEditRef       = signal<number>(0);

  // ── Categories ────────────────────────────────────────────────────────────
  categories      = signal<AdminCategory[]>([]);
  newCatName      = signal('');
  newCatColor     = signal('#6b7280');
  newTagName      = signal('');
  newTagCatId     = signal<number | null>(null);
  editingCat      = signal<AdminCategory | null>(null);

  // ── Contracts ─────────────────────────────────────────────────────────────
  contracts        = signal<AdminContract[]>([]);
  contractRevenue  = signal(0);
  exclusiveCount   = signal(0);
  nonExclusiveCount = signal(0);

  // ── Transactions ──────────────────────────────────────────────────────────
  transactions     = signal<AdminTransaction[]>([]);
  txStatus         = signal<'all' | 'awaiting' | 'in_progress' | 'completed'>('all');
  txCounts         = signal<Record<string, number>>({});
  txRevenue        = signal(0);

  constructor(
    private adminSvc: AdminService,
    private auth:     AuthService,
    private toast:    ToastService,
    private router:   Router,
  ) {}

  ngOnInit(): void {
    if (!this.auth.isAdmin()) {
      this.router.navigate(['/']);
      return;
    }
    this.loadDashboard();
  }

  // ── Tab navigation ────────────────────────────────────────────────────────

  setTab(tab: Tab): void {
    this.activeTab.set(tab);
    switch (tab) {
      case 'dashboard':    this.loadDashboard(); break;
      case 'tracks':       this.loadTracks(); break;
      case 'users':        this.loadUsers(); break;
      case 'engineers':    this.loadEngineers(); break;
      case 'categories':   this.loadCategories(); break;
      case 'contracts':    this.loadContracts(); break;
      case 'transactions': this.loadTransactions(); break;
    }
  }

  // ── Dashboard ─────────────────────────────────────────────────────────────

  loadDashboard(): void {
    this.loading.set(true);
    this.adminSvc.getStats().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) this.stats.set(res.data);
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur chargement stats.' });
      },
    });
  }

  // ── Tracks ────────────────────────────────────────────────────────────────

  loadTracks(): void {
    this.loading.set(true);
    this.adminSvc.getTracks(this.trackStatus()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.tracks.set(res.data.tracks);
          this.pendingCount.set(res.data.pending_count);
          this.approvedCount.set(res.data.approved_count);
        }
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur chargement tracks.' });
      },
    });
  }

  setTrackStatus(status: 'pending' | 'approved' | 'all'): void {
    this.trackStatus.set(status);
    this.loadTracks();
  }

  approveTrack(track: AdminTrack): void {
    this.adminSvc.approveTrack(track.id).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadTracks();
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  rejectTrack(track: AdminTrack): void {
    if (!confirm(`Supprimer le track "${track.title}" ?`)) return;
    this.adminSvc.rejectTrack(track.id).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadTracks();
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  openEditTrack(track: AdminTrack): void {
    this.editingTrack.set({ ...track });
  }

  patchTrack(field: string, value: any): void {
    const t = this.editingTrack();
    if (!t) return;
    this.editingTrack.set({ ...t, [field]: value });
  }

  saveTrack(): void {
    const t = this.editingTrack();
    if (!t) return;
    this.adminSvc.editTrack(t.id, {
      title: t.title, bpm: t.bpm, key: t.key, style: t.style,
      price_mp3: t.price_mp3, price_wav: t.price_wav, price_stems: t.price_stems,
    }).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) { this.editingTrack.set(null); this.loadTracks(); }
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  // ── Users ─────────────────────────────────────────────────────────────────

  loadUsers(): void {
    this.loading.set(true);
    this.adminSvc.getUsers(this.userType()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.users.set(res.data.users);
          this.userCounts.set(res.data.counts);
        }
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur chargement users.' });
      },
    });
  }

  setUserType(type: 'all' | 'beatmakers' | 'artists' | 'engineers'): void {
    this.userType.set(type);
    this.loadUsers();
  }

  toggleUserStatus(user: AdminUser): void {
    this.adminSvc.toggleUserStatus(user.id).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadUsers();
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  toggleRole(user: AdminUser, role: string): void {
    this.adminSvc.toggleUserRole(user.id, role).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadUsers();
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
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
    const obs = this.tokenType() === 'track'
      ? this.adminSvc.addTrackTokens(user.id, this.tokenAmount())
      : this.adminSvc.addToplineTokens(user.id, this.tokenAmount());
    obs.subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) { this.tokenUser.set(null); this.loadUsers(); }
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  togglePremium(user: AdminUser): void {
    this.adminSvc.togglePremium(user.id).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) this.loadUsers();
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  // ── Engineers ─────────────────────────────────────────────────────────────

  loadEngineers(): void {
    this.loading.set(true);
    this.adminSvc.getEngineers().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.certifiedEngineers.set(res.data.certified);
          this.pendingEngineers.set(res.data.pending);
          this.paRequests.set(res.data.pa_requests);
          this.priceRequests.set(res.data.price_requests);
        }
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
      },
    });
  }

  certifyEngineer(engineer: AdminEngineer): void {
    this.adminSvc.certifyEngineer(engineer.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  rejectSample(engineer: AdminEngineer): void {
    if (!confirm(`Rejeter la demande de ${engineer.username} ?`)) return;
    this.adminSvc.rejectEngineerSample(engineer.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  revokeEngineer(engineer: AdminEngineer): void {
    if (!confirm(`Révoquer la certification de ${engineer.username} ?`)) return;
    this.adminSvc.revokeEngineer(engineer.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  openPriceEdit(engineer: AdminEngineer): void {
    this.priceEditId.set(engineer.id);
    this.priceEditMin.set(engineer.mixmaster_price_min ?? 0);
    this.priceEditRef.set(engineer.mixmaster_reference_price ?? 0);
  }

  savePrices(): void {
    const id = this.priceEditId();
    if (!id) return;
    this.adminSvc.updateEngineerPrices(id, this.priceEditMin(), this.priceEditRef()).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) { this.priceEditId.set(null); this.loadEngineers(); } },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  approvePriceRequest(pr: PriceRequest): void {
    this.adminSvc.approvePriceRequest(pr.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  rejectPriceRequest(pr: PriceRequest): void {
    this.adminSvc.rejectPriceRequest(pr.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  approvePA(engineer: AdminEngineer): void {
    this.adminSvc.approveProducerArranger(engineer.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  rejectPA(engineer: AdminEngineer): void {
    this.adminSvc.rejectProducerArranger(engineer.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  revokePA(engineer: AdminEngineer): void {
    this.adminSvc.revokeProducerArranger(engineer.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadEngineers(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  // ── Categories ────────────────────────────────────────────────────────────

  loadCategories(): void {
    this.loading.set(true);
    this.adminSvc.getCategories().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) this.categories.set(res.data.categories);
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
      },
    });
  }

  createCategory(): void {
    const name = this.newCatName().trim();
    if (!name) return;
    this.adminSvc.createCategory(name, this.newCatColor()).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) { this.newCatName.set(''); this.loadCategories(); }
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  deleteCategory(cat: AdminCategory): void {
    if (!confirm(`Supprimer la catégorie "${cat.name}" et ses tags ?`)) return;
    this.adminSvc.deleteCategory(cat.id).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadCategories(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  createTag(cat: AdminCategory): void {
    const name = this.newTagName().trim();
    if (!name) return;
    this.adminSvc.createTag(name, cat.id).subscribe({
      next: res => {
        if (res.feedback) this.toast.showToast(res.feedback);
        if (res.success) { this.newTagName.set(''); this.loadCategories(); }
      },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  deleteTag(tagId: number): void {
    this.adminSvc.deleteTag(tagId).subscribe({
      next: res => { if (res.feedback) this.toast.showToast(res.feedback); if (res.success) this.loadCategories(); },
      error: err => this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' }),
    });
  }

  // ── Contracts ─────────────────────────────────────────────────────────────

  loadContracts(): void {
    this.loading.set(true);
    this.adminSvc.getContracts().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.contracts.set(res.data.contracts);
          this.contractRevenue.set(res.data.total_revenue);
          this.exclusiveCount.set(res.data.exclusive_count);
          this.nonExclusiveCount.set(res.data.non_exclusive_count);
        }
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
      },
    });
  }

  // ── Transactions ──────────────────────────────────────────────────────────

  loadTransactions(): void {
    this.loading.set(true);
    this.adminSvc.getTransactions(this.txStatus()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.transactions.set(res.data.transactions);
          this.txCounts.set(res.data.counts);
          this.txRevenue.set(res.data.total_revenue);
        }
      },
      error: err => {
        this.loading.set(false);
        this.toast.showToast(err?.error?.feedback ?? { level: 'error', message: 'Erreur.' });
      },
    });
  }

  setTxStatus(status: 'all' | 'awaiting' | 'in_progress' | 'completed'): void {
    this.txStatus.set(status);
    this.loadTransactions();
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

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
