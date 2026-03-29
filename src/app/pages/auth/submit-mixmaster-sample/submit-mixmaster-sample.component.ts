import { Component, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../../environments/environment';
import { AuthService } from '../../../services/auth.service';

@Component({
  selector: 'app-submit-mixmaster-sample',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './submit-mixmaster-sample.component.html',
  styleUrl:    './submit-mixmaster-sample.component.scss',
})
export class SubmitMixmasterSampleComponent {

  private apiUrl = `${environment.apiUrl}/auth/submit-mixmaster-sample`;

  // ── Form fields ──────────────────────────────────────────────────────────
  referencePrice = signal<number | null>(null);
  priceMin       = signal<number | null>(null);
  bio            = signal('');
  rawFile        = signal<File | null>(null);
  processedFile  = signal<File | null>(null);

  // ── UI state ─────────────────────────────────────────────────────────────
  loading = signal(false);
  error   = signal<string | null>(null);
  success = signal(false);

  // ── Price validation ─────────────────────────────────────────────────────
  minRequired = computed(() => {
    const ref = this.referencePrice();
    return ref ? Math.round(ref * 0.35) : null;
  });

  maxAllowed = computed(() => {
    const ref = this.referencePrice();
    return ref ? Math.round(ref * 0.65) : null;
  });

  priceError = computed(() => {
    const ref = this.referencePrice();
    const min = this.priceMin();
    if (!ref || !min) return null;
    if (min < (this.minRequired() ?? 0))
      return `Le prix minimum doit être au moins ${this.minRequired()}€ (35% du prix de référence).`;
    if (min > (this.maxAllowed() ?? Infinity))
      return `Le prix minimum ne peut pas dépasser ${this.maxAllowed()}€ (65% de ${Math.round(ref)}€).`;
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
      { name: 'Nettoyage seul',                    pct: 35,  price: cleaning },
      { name: 'Nettoyage + Mastering',              pct: 55,  price: r2(cleaning + mastering) },
      { name: 'Nettoyage + Effets + Mastering',     pct: 100, price: r2(cleaning + effects + mastering) },
      { name: 'Tous les services',                   pct: 160, price: r2(cleaning + effects + artistic + mastering) },
      { name: 'Tous + pistes séparées',              pct: 180, price: r2(cleaning + effects + artistic + mastering + stems) },
    ];
  });

  // ── Auto-included services at price_min ───────────────────────────────────
  autoServices = computed(() => {
    const ref = this.referencePrice();
    const min = this.priceMin();
    if (!ref || !min || ref <= 0) return [];
    const pct = (min / ref) * 100;
    const services = [];
    if (pct >= 35) services.push({ name: 'Nettoyage et équilibre', pct: 35, price: Math.round(ref * 0.35 * 100) / 100 });
    if (pct >= 80) services.push({ name: 'Mixage avec effets',     pct: 45, price: Math.round(ref * 0.45 * 100) / 100 });
    if (pct >= 100) services.push({ name: 'Mastering final',       pct: 20, price: Math.round(ref * 0.20 * 100) / 100 });
    return services;
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

    this.http.post<any>(this.apiUrl, fd, {
      headers: { Authorization: `Bearer ${this.auth.getToken()}` },
    }).subscribe({
      next: (res) => {
        this.loading.set(false);
        if (res.success) {
          this.success.set(true);
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur lors de la soumission.');
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur. Réessayez.');
      },
    });
  }

  goHome(): void {
    this.router.navigate(['/']);
  }
}
