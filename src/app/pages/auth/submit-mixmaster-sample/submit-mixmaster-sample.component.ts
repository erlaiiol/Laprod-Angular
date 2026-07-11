import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { HttpClient, HttpEventType, HttpResponse } from '@angular/common/http';
import { environment } from '../../../../environments/environment';
import { AuthService } from '../../../services/auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-submit-mixmaster-sample',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './submit-mixmaster-sample.component.html',
  styleUrl:    './submit-mixmaster-sample.component.scss',
})
export class SubmitMixmasterSampleComponent {

  private apiUrl = `${environment.apiUrl}/api/auth/submit-mixmaster-sample`;

  // ── Form fields ──────────────────────────────────────────────────────────
  referencePrice = signal<number | null>(null);
  priceMin       = signal<number | null>(null);
  bio            = signal('');
  rawFile        = signal<File | null>(null);
  processedFile  = signal<File | null>(null);

  // ── UI state ─────────────────────────────────────────────────────────────
  loading        = signal(false);
  uploadProgress = signal(0);
  error          = signal<string | null>(null);
  success        = signal(false);

  // ── Price validation ─────────────────────────────────────────────────────
  minRequired = computed(() => {
    const ref = this.referencePrice();
    return ref ? Math.round(ref * 0.35) : null;
  });

  maxAllowed = computed(() => {
    const ref = this.referencePrice();
    return ref ? Math.round(ref * 0.80) : null;
  });

  priceError = computed(() => {
    const ref = this.referencePrice();
    const min = this.priceMin();
    if (!ref || !min) return null;
    if (min < (this.minRequired() ?? 0))
      return `Le prix minimum doit être au moins ${this.minRequired()}€ (35% du prix de référence).`;
    if (min > (this.maxAllowed() ?? Infinity))
      return `Le prix minimum ne peut pas dépasser ${this.maxAllowed()}€ (80% de ${Math.round(ref)}€).`;
    return null;
  });

  // ── Simulator rows ────────────────────────────────────────────────────────
  simulatorRows = computed(() => {
    const ref = this.referencePrice();
    if (!ref || ref <= 0) return [];
    const r2 = (x: number) => Math.round(x * 100) / 100;
    const cleaning  = r2(ref * 0.35);
    const effects   = r2(ref * 0.45);
    const artistic  = r2(ref * 0.60);
    const mastering = r2(ref * 0.20);
    const stems     = r2(ref * 0.20);
    return [
      { name: 'Nettoyage seul',                       pct: 35,  price: cleaning,                                          certified: false },
      { name: 'Nettoyage + Mastering',                 pct: 55,  price: r2(cleaning + mastering),                         certified: false },
      { name: 'Nettoyage + Effets',                    pct: 80,  price: r2(cleaning + effects),                           certified: false },
      { name: 'Nettoyage + Effets + Mastering',        pct: 100, price: r2(cleaning + effects + mastering),               certified: false },
      { name: 'Tous les services (+ artistique)',       pct: 160, price: r2(cleaning + effects + artistic + mastering),    certified: true  },
      { name: 'Tous les services + pistes séparées',   pct: 180, price: r2(cleaning + effects + artistic + mastering + stems), certified: true },
    ];
  });

  // ── Palier actif selon price_min ─────────────────────────────────────────
  // 35%–54% → Nettoyage seul
  // 55%–79% → Nettoyage + Mastering
  // 80%–99% → Nettoyage + Effets  (remplace le mastering par les effets)
  // ≥ 100%  → Nettoyage + Effets + Mastering
  autoServices = computed(() => {
    const ref = this.referencePrice();
    const min = this.priceMin();
    if (!ref || !min || ref <= 0) return [];
    const pct = (min / ref) * 100;
    const r2 = (x: number) => Math.round(x * 100) / 100;
    if (pct >= 100) return [
      { name: 'Nettoyage & équilibre', pct: 35, price: r2(ref * 0.35) },
      { name: 'Mixage avec effets',    pct: 45, price: r2(ref * 0.45) },
      { name: 'Mastering final',       pct: 20, price: r2(ref * 0.20) },
    ];
    if (pct >= 80) return [
      { name: 'Nettoyage & équilibre', pct: 35, price: r2(ref * 0.35) },
      { name: 'Mixage avec effets',    pct: 45, price: r2(ref * 0.45) },
    ];
    if (pct >= 55) return [
      { name: 'Nettoyage & équilibre', pct: 35, price: r2(ref * 0.35) },
      { name: 'Mastering final',       pct: 20, price: r2(ref * 0.20) },
    ];
    return [
      { name: 'Nettoyage & équilibre', pct: 35, price: r2(ref * 0.35) },
    ];
  });

  canSubmit = computed(() =>
    !!this.referencePrice() &&
    !!this.priceMin() &&
    !this.priceError() &&
    !!this.bio().trim() &&
    !!this.rawFile() &&
    !!this.processedFile() &&
    !this.loading()
  );

  constructor(
    private http: HttpClient,
    private router: Router,
    private auth: AuthService,
  ) {}

  onFileChange(field: 'raw' | 'processed', event: Event): void {
    const input = event.target as HTMLInputElement;
    const file  = input.files?.[0] ?? null;
    if (file && file.size > 50 * 1024 * 1024) {
      this.error.set('Fichier trop volumineux (max 50 MB).');
      input.value = '';
      return;
    }
    if (field === 'raw') this.rawFile.set(file);
    else                  this.processedFile.set(file);
  }

  onSubmit(): void {
    if (!this.canSubmit()) return;
    this.loading.set(true);
    this.error.set(null);

    const fd = new FormData();
    fd.append('reference_price', String(this.referencePrice()));
    fd.append('price_min',       String(this.priceMin()));
    fd.append('bio',             this.bio());
    fd.append('sample_raw',      this.rawFile()!);
    fd.append('sample_processed', this.processedFile()!);

    this.uploadProgress.set(0);

    this.http.post<any>(this.apiUrl, fd, {
      headers: { Authorization: `Bearer ${this.auth.getToken()}` },
      reportProgress: true,
      observe: 'events',
    }).subscribe({
      next: (event) => {
        if (event.type === HttpEventType.UploadProgress) {
          const pct = event.total ? Math.round(event.loaded / event.total * 100) : 0;
          this.uploadProgress.set(pct);
        } else if (event.type === HttpEventType.Response) {
          this.loading.set(false);
          const res = (event as HttpResponse<any>).body;
          if (res?.success) {
            this.uploadProgress.set(100);
            this.success.set(true);
          } else {
            this.error.set(res?.feedback?.message ?? 'Erreur lors de la soumission.');
          }
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.uploadProgress.set(0);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur. Réessayez.');
      },
    });
  }

  goHome(): void {
    this.router.navigate(['/']);
  }
}
