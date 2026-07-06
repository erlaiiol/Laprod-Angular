import {
  Component,
  signal,
  inject,
  ChangeDetectionStrategy,
  OnInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormBuilder, Validators } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { AuthService } from '../../services/auth.service';

interface Testimonial {
  id: number;
  email: string;
  role: string | null;
  message: string;
  rating: number | null;
  created_at: string | null;
  username: string | null;
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}

const ROLE_LABELS: Record<string, string> = {
  beatmaker:    'Beatmaker',
  artist:       'Artiste',
  mix_engineer: 'Ingénieur son',
};

@Component({
  selector: 'app-testimonials',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule],
  templateUrl: './testimonials.component.html',
  styleUrls: ['./testimonials.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TestimonialsComponent implements OnInit {

  private http = inject(HttpClient);
  private auth = inject(AuthService);
  private fb   = inject(FormBuilder);

  readonly apiUrl = environment.apiUrl;
  readonly isDev  = !environment.production;

  testimonials  = signal<Testimonial[]>([]);
  loading       = signal(true);
  submitLoading = signal(false);
  submitSuccess = signal(false);
  submitError   = signal<string | null>(null);

  readonly roles = [
    { value: 'beatmaker',    label: 'Beatmaker' },
    { value: 'artist',       label: 'Artiste' },
    { value: 'mix_engineer', label: 'Ingénieur son' },
  ];

  readonly form = this.fb.group({
    email:   ['', [Validators.required, Validators.email]],
    role:    [''],
    message: ['', [Validators.required, Validators.minLength(20)]],
    rating:  [null as number | null],
  });

  ngOnInit(): void {
    const user = this.auth.currentUser();
    if (user?.email) {
      this.form.patchValue({ email: user.email });
    }

    this.http
      .get<ApiResponse<Testimonial[]>>(`${this.apiUrl}/api/testimonials/published`)
      .subscribe({
        next: (res) => {
          if (res.success) this.testimonials.set(res.data);
          this.loading.set(false);
        },
        error: () => this.loading.set(false),
      });
  }

  roleLabel(role: string | null): string {
    return role ? (ROLE_LABELS[role] ?? role) : '';
  }

  stars(rating: number | null): boolean[] {
    if (!rating) return [];
    return Array.from({ length: 5 }, (_, i) => i < rating);
  }

  setRating(n: number): void {
    this.form.patchValue({ rating: n });
  }

  currentRating(): number {
    return this.form.get('rating')?.value ?? 0;
  }

  onSubmit(): void {
    if (this.form.invalid || this.submitLoading()) return;
    this.submitLoading.set(true);
    this.submitError.set(null);

    this.http
      .post<ApiResponse<{ id: number }>>(
        `${this.apiUrl}/api/testimonials/submit`,
        this.form.value,
      )
      .subscribe({
        next: () => {
          this.submitLoading.set(false);
          this.submitSuccess.set(true);
          this.form.reset();
        },
        error: (e) => {
          this.submitLoading.set(false);
          this.submitError.set(
            e?.error?.message ?? 'Une erreur est survenue, réessaie plus tard.',
          );
        },
      });
  }

  // Cas illustratifs visibles uniquement en DEV — clairement étiquetés
  readonly illustrativeCases = [
    {
      name: 'Artiste A.',
      role: 'Artiste',
      quote: 'J\'ai posé ma voix sur un beat LaProd et j\'ai signé avec mon label 3 mois après.',
      tag: 'CAS ILLUSTRATIF',
    },
    {
      name: 'Beatmaker B.',
      role: 'Beatmaker',
      quote: 'En 6 mois j\'ai généré mes premières ventes grâce aux analytics du dashboard.',
      tag: 'CAS ILLUSTRATIF',
    },
    {
      name: 'Ingénieur C.',
      role: 'Ingénieur son',
      quote: 'La plateforme m\'a permis de décrocher mes premières missions mix en ligne.',
      tag: 'CAS ILLUSTRATIF',
    },
  ];
}
