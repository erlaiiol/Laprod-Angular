import { ChangeDetectionStrategy, Component, OnInit, OnDestroy, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { AdminService, AdminTopline } from '../../../services/admin.service';
import { AuthService } from '../../../services/auth.service';
import { ToastService } from '../../../services/toast.service';
import { environment } from '../../../../environments/environment';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-admin-toplines',
  standalone: true,
  imports: [CommonModule],
  styleUrl: '../admin.component.scss',
  template: `
<div class="sub-tabs">
  <button [class.active]="filter() === 'all'"     (click)="setFilter('all')">
    Toutes ({{ total() }})
  </button>
  <button [class.active]="filter() === 'true'"    (click)="setFilter('true')">
    Publiées
  </button>
  <button [class.active]="filter() === 'false'"   (click)="setFilter('false')">
    Non publiées
  </button>
</div>

@if (loading()) {
  <div class="loading-row"><span>Chargement…</span></div>
} @else if (toplines().length === 0) {
  <p class="empty">Aucune topline.</p>
} @else {
  <table class="data-table">
    <thead>
      <tr>
        <th>Track</th>
        <th>Beatmaker</th>
        <th>Artiste (topline)</th>
        <th>Date</th>
        <th>Statut</th>
        <th>Description</th>
        <th>Écouter</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
      @for (tl of toplines(); track tl.id) {
        <tr>
          <!-- Track -->
          <td>
            @if (tl.track) {
              <div class="cell-track">
                <img [src]="trackImg(tl.track.image_file)" class="thumb" alt="">
                <a [href]="'/track/' + tl.track.id" target="_blank" class="link-subtle">
                  {{ tl.track.title }}
                </a>
              </div>
            } @else {
              <span class="text-muted">—</span>
            }
          </td>

          <!-- Beatmaker -->
          <td class="small">
            @if (tl.track?.beatmaker) {
              <a [href]="'/profile/' + tl.track!.beatmaker!.username" target="_blank" class="link-subtle">
                {{ tl.track!.beatmaker!.username }}
              </a>
            } @else { — }
          </td>

          <!-- Artiste topline -->
          <td class="small">
            @if (tl.artist) {
              <div class="cell-user">
                <img [src]="userImg(tl.artist.profile_image)" class="thumb round" alt="">
                <a [href]="'/profile/' + tl.artist.username" target="_blank" class="link-subtle">
                  {{ tl.artist.username }}
                </a>
              </div>
            } @else { — }
          </td>

          <!-- Date -->
          <td class="small">{{ fmtDate(tl.created_at) }}</td>

          <!-- Statut -->
          <td>
            <span class="status-chip" [class.active]="tl.is_published">
              {{ tl.is_published ? 'Publiée' : 'Privée' }}
            </span>
            <span class="status-chip" [title]="tl.is_mobile_processed ? 'Enregistrée et mixée dans le studio mobile' : 'Enregistrée sur le site, traitée serveur'">
              {{ tl.is_mobile_processed ? 'Mobile' : 'Web' }}
            </span>
          </td>

          <!-- Description -->
          <td class="small desc-cell" [title]="tl.description || ''">
            {{ tl.description ? (tl.description.length > 60 ? tl.description.slice(0, 60) + '…' : tl.description) : '—' }}
          </td>

          <!-- Player -->
          <td>
            @if (playingId() === tl.id && blobUrl()) {
              <audio class="topline-audio"
                     [src]="blobUrl()!"
                     controls
                     autoplay>
              </audio>
            } @else {
              <button class="btn-icon"
                      [disabled]="loadingId() === tl.id"
                      title="Écouter cette topline"
                      (click)="play(tl)">
                <i class="bi" [class.bi-play-circle]="loadingId() !== tl.id"
                              [class.bi-hourglass-split]="loadingId() === tl.id"></i>
              </button>
            }
          </td>

          <!-- Actions -->
          <td class="actions">
            <button class="btn-icon btn-icon--danger"
                    title="Supprimer cette topline"
                    (click)="deleteTl(tl)">
              <i class="bi bi-trash3"></i>
            </button>
          </td>
        </tr>
      }
    </tbody>
  </table>

  <!-- Pagination -->
  @if (pages() > 1) {
    <div class="pagination-row">
      <button class="btn-page" [disabled]="page() === 1" (click)="goPage(page() - 1)">‹</button>
      @for (p of pageRange(); track p) {
        <button class="btn-page" [class.btn-page--active]="p === page()" (click)="goPage(p)">{{ p }}</button>
      }
      <button class="btn-page" [disabled]="page() === pages()" (click)="goPage(page() + 1)">›</button>
    </div>
  }
}
  `,
})
export class AdminToplineComponent implements OnInit, OnDestroy {

  private adminSvc = inject(AdminService);
  private authSvc  = inject(AuthService);
  private http     = inject(HttpClient);
  private toast    = inject(ToastService);

  toplines  = signal<AdminTopline[]>([]);
  loading   = signal(true);
  filter    = signal<'all' | 'true' | 'false'>('all');
  page      = signal(1);
  pages     = signal(1);
  total     = signal(0);

  // Player
  playingId  = signal<number | null>(null);
  loadingId  = signal<number | null>(null);
  blobUrl    = signal<string | null>(null);

  private static base = `${environment.apiUrl}/db_assets/`;

  ngOnInit(): void { this.load(); }

  ngOnDestroy(): void { this.revokeBlobUrl(); }

  load(): void {
    this.loading.set(true);
    this.adminSvc.getToplines(this.page(), this.filter()).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.toplines.set(res.data.toplines);
          this.total.set(res.data.total);
          this.pages.set(res.data.pages);
        }
      },
      error: () => {
        this.loading.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur chargement toplines.' });
      },
    });
  }

  setFilter(f: 'all' | 'true' | 'false'): void {
    this.filter.set(f);
    this.page.set(1);
    this.stopPlayer();
    this.load();
  }

  goPage(p: number): void {
    this.page.set(p);
    this.stopPlayer();
    this.load();
  }

  pageRange(): number[] {
    return Array.from({ length: this.pages() }, (_, i) => i + 1);
  }

  play(tl: AdminTopline): void {
    if (this.playingId() === tl.id) { this.stopPlayer(); return; }
    this.stopPlayer();
    this.loadingId.set(tl.id);

    const url = `${environment.apiUrl}${tl.stream_url}`;
    const token = this.authSvc.getToken();

    this.http.get(url, {
      responseType: 'blob',
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    }).subscribe({
      next: blob => {
        const objectUrl = URL.createObjectURL(blob);
        this.blobUrl.set(objectUrl);
        this.playingId.set(tl.id);
        this.loadingId.set(null);
      },
      error: () => {
        this.loadingId.set(null);
        this.toast.showToast({ level: 'error', message: 'Impossible de charger cette topline.' });
      },
    });
  }

  stopPlayer(): void {
    this.revokeBlobUrl();
    this.playingId.set(null);
    this.loadingId.set(null);
  }

  deleteTl(tl: AdminTopline): void {
    if (!confirm(`Supprimer la topline #${tl.id} de ${tl.artist?.username ?? '?'} ?`)) return;
    this.adminSvc.deleteTopline(tl.id).subscribe({
      next: res => {
        if (res.success) {
          if (this.playingId() === tl.id) this.stopPlayer();
          this.toplines.update(list => list.filter(t => t.id !== tl.id));
          this.total.update(n => n - 1);
          this.toast.showToast({ level: 'success', message: 'Topline supprimée.' });
        }
      },
      error: () => this.toast.showToast({ level: 'error', message: 'Erreur lors de la suppression.' }),
    });
  }

  private revokeBlobUrl(): void {
    const url = this.blobUrl();
    if (url) { URL.revokeObjectURL(url); this.blobUrl.set(null); }
  }

  trackImg(path: string | null): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    return AdminToplineComponent.base + path;
  }

  userImg(path: string | null): string {
    if (!path) return '/assets/placeholders/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return AdminToplineComponent.base + path;
  }

  fmtDate(d: string | null): string {
    if (!d) return '—';
    return new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
}
