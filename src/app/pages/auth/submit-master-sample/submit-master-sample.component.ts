import { ChangeDetectionStrategy, Component, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../../environments/environment';
import { AuthService } from '../../../services/auth.service';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-submit-master-sample',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './submit-master-sample.component.html',
  styleUrl:    './submit-master-sample.component.scss',
})
export class SubmitMasterSampleComponent {

  private apiUrl = `${environment.apiUrl}/api/auth/submit-master-sample`;

  rawFile       = signal<File | null>(null);
  processedFile = signal<File | null>(null);

  loading = signal(false);
  error   = signal<string | null>(null);
  success = signal(false);

  canSubmit = computed(() =>
    !!this.rawFile() && !!this.processedFile() && !this.loading()
  );

  constructor(
    private http:   HttpClient,
    private router: Router,
    readonly auth:  AuthService,
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
    fd.append('sample_raw',       this.rawFile()!);
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
