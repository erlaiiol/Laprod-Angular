import { Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { PurchasesService, PurchasesData } from '../../services/purchases.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-purchases',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './purchases.component.html',
  styleUrls: ['./purchases.component.scss'],
})
export class PurchasesComponent implements OnInit {

  loading = signal(true);
  error   = signal<string | null>(null);
  data    = signal<PurchasesData | null>(null);

  readonly auth        = inject(AuthService);
  private purchasesSvc = inject(PurchasesService);
  private router       = inject(Router);
  private toast        = inject(ToastService);

  ngOnInit(): void {
    if (!this.auth.isLoggedIn()) { this.router.navigate(['/login']); return; }

    this.purchasesSvc.getMyPurchases().subscribe({
      next: (res) => {
        if (res.success) this.data.set(res.data!);
        else this.error.set(res.feedback?.message ?? 'Erreur de chargement.');
        this.loading.set(false);
      },
      error: (err) => {
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger vos achats.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger vos achats.');
        this.loading.set(false);
      },
    });
  }

  imgUrl(path: string | null): string {
    return path ? `${environment.apiUrl}/static/${path}` : '/assets/placeholder-track.png';
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }

  formatLabel(format: string): string {
    const labels: Record<string, string> = { mp3: 'MP3', wav: 'WAV', stems: 'STEMS' };
    return labels[format] ?? format.toUpperCase();
  }

  downloadUrl(streamUrl: string): string {
    return `${environment.apiUrl}${streamUrl}`;
  }

  contractUrl(url: string): string {
    return `${environment.apiUrl}${url}`;
  }
}
