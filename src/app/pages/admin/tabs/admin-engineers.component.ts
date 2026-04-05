import { Component, OnInit, signal, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminService, AdminMixEngineer, PriceRequest } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

type EngTab = 'pending' | 'certified' | 'price' | 'pa' | 'direct';

@Component({
  selector: 'app-admin-engineers',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-engineers.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminEngineersComponent implements OnInit {
  @Output() pendingCountChange = new EventEmitter<number>();

  staticBase = `${environment.apiUrl.replace('/api', '')}/static/`;

  loading    = signal(false);
  activeTab  = signal<EngTab>('pending');

  certified    = signal<AdminMixEngineer[]>([]);
  pending      = signal<AdminMixEngineer[]>([]);
  paRequests   = signal<AdminMixEngineer[]>([]);
  priceReqs    = signal<PriceRequest[]>([]);

  // Prix inline
  priceEditId  = signal<number | null>(null);
  priceEditMin = signal(0);
  priceEditRef = signal(0);

  // Direct certification tab
  allMixEngineers = signal<AdminMixEngineer[]>([]);
  loadingDirect   = signal(false);
  // Per-engineer upload state
  directUploadRaw:  Record<number, File | null> = {};
  directUploadProc: Record<number, File | null> = {};
  directRefPrice:   Record<number, number> = {};
  directMinPrice:   Record<number, number> = {};
  directBio:        Record<number, string> = {};

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.load(); }

  setActiveTab(tab: EngTab): void {
    this.activeTab.set(tab);
    if (tab === 'direct' && this.allMixEngineers().length === 0) {
      this.loadDirect();
    }
  }

  loadDirect(): void {
    this.loadingDirect.set(true);
    this.adminSvc.getAllMixEngineers().subscribe({
      next: res => {
        this.loadingDirect.set(false);
        if (res.success && res.data) {
          this.allMixEngineers.set(res.data.engineers);
          for (const e of res.data.engineers) {
            this.directRefPrice[e.id] = e.mixmaster_reference_price ?? 50;
            this.directMinPrice[e.id] = e.mixmaster_price_min ?? 30;
            this.directBio[e.id]      = e.mixmaster_bio ?? '';
          }
        }
      },
      error: err => {
        this.loadingDirect.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement.' });
      },
    });
  }

  onDirectFileChange(engineerId: number, field: 'raw' | 'proc', event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0] ?? null;
    if (field === 'raw') this.directUploadRaw[engineerId] = file;
    else this.directUploadProc[engineerId] = file;
  }

  uploadSample(e: AdminMixEngineer): void {
    const raw  = this.directUploadRaw[e.id];
    const proc = this.directUploadProc[e.id];
    if (!raw && !proc) {
      this.toast.showToast({ level: 'error', message: 'Sélectionnez au moins un fichier audio.' });
      return;
    }
    const fd = new FormData();
    if (raw)  fd.append('sample_raw',       raw);
    if (proc) fd.append('sample_processed', proc);
    this.adminSvc.uploadEngineerSample(e.id, fd).subscribe({
      next: res => {
        if (res.success && res.data) {
          this.allMixEngineers.update(list =>
            list.map(eng => eng.id === e.id
              ? { ...eng, mixmaster_sample_raw: res.data!.sample_raw, mixmaster_sample_processed: res.data!.sample_processed }
              : eng
            )
          );
        }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur upload.' }); },
    });
  }

  saveDirectInfo(e: AdminMixEngineer): void {
    this.adminSvc.setEngineerInfo(e.id, {
      reference_price: this.directRefPrice[e.id],
      price_min:       this.directMinPrice[e.id],
      bio:             this.directBio[e.id],
    }).subscribe({
      next: () => { },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  certifyDirect(e: AdminMixEngineer): void {
    this.adminSvc.certifyEngineer(e.id).subscribe({
      next: res => {
        if (res.success) {
          this.allMixEngineers.update(list =>
            list.map(eng => eng.id === e.id ? { ...eng, is_mixmaster_engineer: true } : eng)
          );
          this.load();
        }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getEngineers().subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.certified.set(res.data.certified);
          this.pending.set(res.data.pending);
          this.paRequests.set(res.data.pa_requests);
          this.priceReqs.set(res.data.price_requests);
          this.pendingCountChange.emit(
            res.data.pending.length + res.data.price_requests.length + res.data.pa_requests.length
          );
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement engineers.' });
      },
    });
  }

  certify(e: AdminMixEngineer): void {
    this.adminSvc.certifyEngineer(e.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  rejectSample(e: AdminMixEngineer): void {
    if (!confirm(`Rejeter la demande de ${e.username} ?`)) return;
    this.adminSvc.rejectEngineerSample(e.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  revoke(e: AdminMixEngineer): void {
    if (!confirm(`Révoquer la certification de ${e.username} ?`)) return;
    this.adminSvc.revokeEngineer(e.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  openPriceEdit(e: AdminMixEngineer): void {
    this.priceEditId.set(e.id);
    this.priceEditMin.set(e.mixmaster_price_min ?? 0);
    this.priceEditRef.set(e.mixmaster_reference_price ?? 0);
  }

  savePrices(): void {
    const id = this.priceEditId();
    if (!id) return;
    this.adminSvc.updateEngineerPrices(id, this.priceEditMin(), this.priceEditRef()).subscribe({
      next: res => {
        if (res.success) { this.priceEditId.set(null); this.load(); }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  approvePriceReq(pr: PriceRequest): void {
    this.adminSvc.approvePriceRequest(pr.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  rejectPriceReq(pr: PriceRequest): void {
    this.adminSvc.rejectPriceRequest(pr.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  approvePA(e: AdminMixEngineer): void {
    this.adminSvc.approveProducerArranger(e.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  rejectPA(e: AdminMixEngineer): void {
    this.adminSvc.rejectProducerArranger(e.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  revokePA(e: AdminMixEngineer): void {
    this.adminSvc.revokeProducerArranger(e.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }
}
