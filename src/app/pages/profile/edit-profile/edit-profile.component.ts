import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UserService } from '../../../services/user.service';
import { AuthService } from '../../../services/auth.service';
import { environment } from '../../../../environments/environment';

@Component({
  selector: 'app-edit-profile',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './edit-profile.component.html',
  styleUrl:    './edit-profile.component.scss',
})
export class EditProfileComponent implements OnInit {

  staticBase = `${environment.apiUrl}/db_assets/`;

  // ── Form state ────────────────────────────────────────────────────────────
  bio        = signal('');
  instagram  = signal('');
  twitter    = signal('');
  youtube    = signal('');
  soundcloud = signal('');
  signature  = signal('');
  isArtist       = signal(false);
  isBeatmaker    = signal(false);
  isMixEngineer  = signal(false);
  requestProducerArranger = signal(false);

  // Mixmaster pricing (certifié uniquement)
  refPrice = signal<number | null>(null);
  priceMin = signal<number | null>(null);

  avatarPreview  = signal<string | null>(null);
  selectedFile   = signal<File | null>(null);

  // ── UI state ──────────────────────────────────────────────────────────────
  loading = signal(false);
  error   = signal<string | null>(null);
  success = signal<string | null>(null);

  isMixmasterCertified        = signal(false);
  isCertifiedProducer         = signal(false);
  producerReqSubmitted        = signal(false);
  isCertifiedMasterEngineer   = signal(false);
  masterSampleSubmitted       = signal(false);

  // Computed premium helpers (lus depuis le signal auth)
  private authSvc = inject(AuthService);
  readonly subscriptionPlan   = computed(() => this.authSvc.currentUser()?.subscription_plan ?? 'free');
  readonly isPremium           = computed(() => this.authSvc.isPremium());
  readonly isPro               = computed(() => this.authSvc.isPro());

  constructor(
    private userSvc: UserService,
    readonly auth:   AuthService,
    private router:  Router,
  ) {}

  ngOnInit(): void {
    const user = this.auth.currentUser();
    if (!user) { this.router.navigate(['/login']); return; }

    // Prefill from stored user
    this.bio.set((user as any).bio ?? '');
    this.instagram.set((user as any).instagram ?? '');
    this.twitter.set((user as any).twitter ?? '');
    this.youtube.set((user as any).youtube ?? '');
    this.soundcloud.set((user as any).soundcloud ?? '');
    this.signature.set((user as any).signature ?? '');
    this.isArtist.set(user.roles?.is_artist ?? false);
    this.isBeatmaker.set(user.roles?.is_beatmaker ?? false);
    this.isMixEngineer.set(user.roles?.is_mix_engineer ?? false);
    this.isMixmasterCertified.set((user as any).roles?.is_mixmaster_engineer ?? false);
    this.isCertifiedProducer.set((user as any).is_certified_producer_arranger ?? false);
    this.producerReqSubmitted.set((user as any).producer_arranger_request_submitted ?? false);

    // Fetch fresh data (prices, master certification — not all in User signal)
    this.userSvc.getProfile(user.username).subscribe(res => {
      if (!res.success || !res.data) return;
      const u = res.data.user;
      if (u.mixmaster) {
        this.refPrice.set(u.mixmaster.reference_price);
        this.priceMin.set(u.mixmaster.price_min);
      }
      if (u.is_certified_master_engineer !== undefined) {
        this.isCertifiedMasterEngineer.set(u.is_certified_master_engineer);
      }
      if (u.master_sample_submitted !== undefined) {
        this.masterSampleSubmitted.set(u.master_sample_submitted);
      }
    });
  }

  onAvatarChange(event: Event): void {
    const file = (event.target as HTMLInputElement).files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      this.error.set('Image trop lourde (max 5 MB).');
      return;
    }
    this.selectedFile.set(file);
    const reader = new FileReader();
    reader.onload = e => this.avatarPreview.set(e.target?.result as string);
    reader.readAsDataURL(file);
  }

  onSubmit(): void {
    this.loading.set(true);
    this.error.set(null);
    this.success.set(null);

    const fd = new FormData();
    fd.append('bio',        this.bio());
    fd.append('instagram',  this.instagram());
    fd.append('twitter',    this.twitter());
    fd.append('youtube',    this.youtube());
    fd.append('soundcloud', this.soundcloud());
    fd.append('signature',  this.signature());
    fd.append('is_artist',      String(this.isArtist()));
    fd.append('is_beatmaker',   String(this.isBeatmaker()));
    fd.append('is_mix_engineer', String(this.isMixEngineer()));

    if (this.isMixmasterCertified()) {
      fd.append('request_producer_arranger', String(this.requestProducerArranger()));
      if (this.refPrice() !== null) fd.append('mixmaster_reference_price', String(this.refPrice()));
      if (this.priceMin() !== null) fd.append('mixmaster_price_min',       String(this.priceMin()));
    }

    const file = this.selectedFile();
    if (file) fd.append('profile_picture', file);

    this.userSvc.updateProfile(fd).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success) {
          if (res.data?.user) this.auth.updateCurrentUser(res.data.user);
          this.success.set(res.feedback.message);
          if (res.data?.next === 'submit-sample') {
            this.router.navigate(['/submit-sample']);
          }
        } else {
          this.error.set(res.feedback?.message ?? 'Erreur lors de la mise à jour.');
        }
      },
      error: err => {
        this.loading.set(false);
        this.error.set(err?.error?.feedback?.message ?? 'Erreur serveur.');
      },
    });
  }

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }
}
