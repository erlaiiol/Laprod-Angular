import { ChangeDetectionStrategy, Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { AuthService } from '../../services/auth.service';
import { PurchasesService, PurchasesData, PurchaseItem } from '../../services/purchases.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';
import { FormatDatePipe } from '../../pipes/format-date.pipe';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-purchases',
  standalone: true,
  imports: [CommonModule, RouterModule, FormatDatePipe],
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
  private http         = inject(HttpClient);

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
    return path ? `${environment.apiUrl}/db_assets/${path}` : '/assets/placeholders/placeholder-track.png';
  }


  formatLabel(format: string): string {
    const labels: Record<string, string> = { mp3: 'MP3', wav: 'WAV', stems: 'STEMS' };
    return labels[format] ?? format.toUpperCase();
  }

  private _jwtDownload(relativeUrl: string, filename: string, mime: string): void {
    this.http.get(`${environment.apiUrl}${relativeUrl}`, {
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

  downloadPurchase(p: PurchaseItem): void {
    const ext  = p.format === 'stems' ? 'zip' : p.format;
    const mime = p.format === 'stems' ? 'application/zip'
               : p.format === 'wav'   ? 'audio/wav' : 'audio/mpeg';
    this._jwtDownload(p.stream_url, `${p.track?.title ?? 'beat'}.${ext}`, mime);
  }

  downloadContract(p: PurchaseItem): void {
    if (!p.contract_url) return;
    this._jwtDownload(p.contract_url, `contrat_${p.track?.title ?? 'beat'}_${p.format}.pdf`, 'application/pdf');
  }

  downloadInvoice(p: PurchaseItem): void {
    this._jwtDownload(p.invoice_url, `facture_laprod_${p.track?.title ?? 'beat'}.pdf`, 'application/pdf');
  }
}
