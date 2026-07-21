import { ChangeDetectionStrategy, Component, OnInit, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import {
  RoyaltiesService, TrackSplitDTO, TrackSplitRole, TRACK_SPLIT_ROLE_LABELS,
} from '../../../services/royalties.service';
import { RosterService } from '../../../services/roster.service';
import { UserService, UserTrack } from '../../../services/user.service';
import { AuthService } from '../../../services/auth.service';
import { ToastService } from '../../../services/toast.service';
import { ProducerTabsComponent } from '../producer-tabs/producer-tabs.component';
import { BetaBadgeComponent } from '../../../components/beta-badge/beta-badge.component';

interface ArtistOption {
  username: string;
  label:    string;
}

@Component({
  selector: 'app-royalties',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, ProducerTabsComponent, BetaBadgeComponent],
  templateUrl: './royalties.component.html',
  styleUrl: './royalties.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RoyaltiesComponent implements OnInit {

  readonly roleLabels = TRACK_SPLIT_ROLE_LABELS;
  readonly roleKeys   = Object.keys(TRACK_SPLIT_ROLE_LABELS) as TrackSplitRole[];

  loadingArtists = signal(true);
  artistOptions  = signal<ArtistOption[]>([]);
  selectedArtist = signal<string | null>(null);

  loadingTracks = signal(false);
  tracks        = signal<UserTrack[]>([]);
  selectedTrackId = signal<number | null>(null);

  loadingSplits  = signal(false);
  splits         = signal<TrackSplitDTO[]>([]);
  totalPercentage = signal(0);
  canManage       = signal(false);

  showForm    = signal(false);
  saving      = signal(false);
  formError   = signal<string | null>(null);
  formRole    = signal<TrackSplitRole>('beatmaker');
  formPercentage = signal<number | null>(null);
  formName    = signal('');

  actingOnSplit = signal<number | null>(null);
  downloading   = signal(false);

  readonly remainingPercentage = computed(() => Math.max(0, 100 - this.totalPercentage()));

  constructor(
    readonly auth: AuthService,
    private royalties: RoyaltiesService,
    private roster: RosterService,
    private userSvc: UserService,
    private toast: ToastService,
  ) {}

  ngOnInit(): void {
    this.loadingArtists.set(true);
    const options: ArtistOption[] = [];
    const me = this.auth.currentUser();
    if (me && (this.auth.isArtist() || this.auth.isBeatmaker())) {
      options.push({ username: me.username, label: `${me.username} (moi)` });
    }

    this.roster.mine().subscribe({
      next: res => {
        for (const link of res.data?.as_producer ?? []) {
          if (link.status === 'active') {
            options.push({ username: link.counterpart.username, label: link.counterpart.username });
          }
        }
        this.artistOptions.set(options);
        this.loadingArtists.set(false);
        if (options.length > 0) this.selectArtist(options[0].username);
      },
      error: () => { this.artistOptions.set(options); this.loadingArtists.set(false); },
    });
  }

  selectArtist(username: string): void {
    this.selectedArtist.set(username);
    this.selectedTrackId.set(null);
    this.splits.set([]);
    this.loadingTracks.set(true);
    this.userSvc.getProfile(username).subscribe({
      next: res => {
        const t = res.data?.user?.tracks ?? [];
        this.tracks.set(t);
        this.loadingTracks.set(false);
        if (t.length > 0) this.selectTrack(t[0].id);
      },
      error: () => { this.tracks.set([]); this.loadingTracks.set(false); },
    });
  }

  selectTrack(trackId: number): void {
    this.selectedTrackId.set(trackId);
    this.reloadSplits();
  }

  private reloadSplits(): void {
    const trackId = this.selectedTrackId();
    if (!trackId) return;
    this.loadingSplits.set(true);
    this.royalties.list(trackId).subscribe({
      next: res => {
        this.splits.set(res.data?.splits ?? []);
        this.totalPercentage.set(res.data?.total_percentage ?? 0);
        this.canManage.set(res.data?.can_manage ?? false);
        this.loadingSplits.set(false);
      },
      error: () => this.loadingSplits.set(false),
    });
  }

  toggleForm(): void {
    this.showForm.set(!this.showForm());
    this.formError.set(null);
  }

  submitSplit(): void {
    const trackId = this.selectedTrackId();
    const percentage = this.formPercentage();
    const name = this.formName().trim();
    if (!trackId || !percentage || !name) {
      this.formError.set('Nom, rôle et pourcentage sont obligatoires.');
      return;
    }

    this.saving.set(true);
    this.formError.set(null);
    this.royalties.add(trackId, { role: this.formRole(), percentage, external_name: name }).subscribe({
      next: () => {
        this.saving.set(false);
        this.formName.set('');
        this.formPercentage.set(null);
        this.showForm.set(false);
        this.reloadSplits();
      },
      error: err => {
        this.saving.set(false);
        this.formError.set(err?.error?.feedback?.message ?? "Impossible d'ajouter cette part.");
      },
    });
  }

  confirmSplit(split: TrackSplitDTO): void {
    this.actingOnSplit.set(split.id);
    this.royalties.confirm(split.id).subscribe({
      next: () => { this.actingOnSplit.set(null); this.reloadSplits(); },
      error: () => this.actingOnSplit.set(null),
    });
  }

  removeSplit(split: TrackSplitDTO): void {
    this.actingOnSplit.set(split.id);
    this.royalties.remove(split.id).subscribe({
      next: () => { this.actingOnSplit.set(null); this.reloadSplits(); },
      error: () => this.actingOnSplit.set(null),
    });
  }

  canConfirm(split: TrackSplitDTO): boolean {
    if (split.status === 'confirmed') return false;
    const myId = this.auth.currentUser()?.id;
    return split.user?.id === myId || this.canManage();
  }

  /** Le relevé PDF est l'artefact à faire sortir de LaProd : label, comptable,
   *  PRO/SACEM, nouveau collaborateur — ce document ne fait que mettre en forme
   *  ce que l'utilisateur voit déjà à l'écran. */
  downloadPdf(): void {
    const trackId = this.selectedTrackId();
    if (!trackId || this.downloading()) return;

    this.downloading.set(true);
    this.royalties.downloadPdf(trackId).subscribe({
      next: blob => {
        const title = this.tracks().find(t => t.id === trackId)?.title || 'titre';
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `royalties_${title.replace(/[^a-z0-9]/gi, '_')}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        this.downloading.set(false);
      },
      error: () => {
        this.downloading.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors du téléchargement.' });
      },
    });
  }
}
