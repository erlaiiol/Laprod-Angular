import { Component, OnInit, signal, Output, EventEmitter } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { AdminService, AdminTrack } from '../../../services/admin.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-admin-tracks',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './admin-tracks.component.html',
  styleUrl: '../admin.component.scss',
})
export class AdminTracksComponent implements OnInit {
  @Output() pendingCountChange = new EventEmitter<number>();

  staticBase = `${environment.apiUrl.replace('/api', '')}/static/`;

  loading      = signal(false);
  tracks       = signal<AdminTrack[]>([]);
  trackStatus  = signal<'pending' | 'approved' | 'all'>('pending');
  pendingCount = signal(0);
  approvedCount = signal(0);
  editingTrack = signal<AdminTrack | null>(null);

  constructor(private adminSvc: AdminService, private toast: ToastService) {}

  ngOnInit(): void { this.load(); }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getTracks(this.trackStatus()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.tracks.set(res.data.tracks);
          this.pendingCount.set(res.data.pending_count);
          this.approvedCount.set(res.data.approved_count);
          this.pendingCountChange.emit(res.data.pending_count);
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur chargement tracks.' });
      },
    });
  }

  setStatus(status: 'pending' | 'approved' | 'all'): void {
    this.trackStatus.set(status);
    this.load();
  }

  approve(track: AdminTrack): void {
    this.adminSvc.approveTrack(track.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  reject(track: AdminTrack): void {
    if (!confirm(`Supprimer le track "${track.title}" ?`)) return;
    this.adminSvc.rejectTrack(track.id).subscribe({
      next: res => { if (res.success) this.load(); },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
    });
  }

  openEdit(track: AdminTrack): void { this.editingTrack.set({ ...track }); }

  patch(field: string, value: unknown): void {
    const t = this.editingTrack();
    if (t) this.editingTrack.set({ ...t, [field]: value });
  }

  saveEdit(): void {
    const t = this.editingTrack();
    if (!t) return;
    this.adminSvc.editTrack(t.id, {
      title: t.title, bpm: t.bpm, key: t.key, style: t.style,
      price_mp3: t.price_mp3, price_wav: t.price_wav, price_stems: t.price_stems,
    }).subscribe({
      next: res => {
        if (res.success) { this.editingTrack.set(null); this.load(); }
      },
      error: err => { if (!err?.error?.feedback) this.toast.showToast({ level: 'error', message: 'Erreur.' }); },
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
