import { ChangeDetectionStrategy, Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { RosterService, RosterLinkDTO, RosterSearchResult } from '../../../services/roster.service';
import { AuthService } from '../../../services/auth.service';
import { ImgFallbackDirective } from '../../../directives/img-fallback.directive';
import { ProducerTabsComponent } from '../producer-tabs/producer-tabs.component';
import { BetaBadgeComponent } from '../../../components/beta-badge/beta-badge.component';
import { environment } from '../../../../environments/environment';

// ─────────────────────────────────────────────────────────────────────────────
// ROSTER — côté producteur uniquement : "qui je gère". Le côté artiste ("qui me
// gère") vit désormais dans /dashboard/artist (onglet Roster) — relation
// asymétrique, un artiste pur n'a rien à faire sur une URL /producer/*.
// ─────────────────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-roster',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, ImgFallbackDirective, ProducerTabsComponent, BetaBadgeComponent],
  templateUrl: './roster.component.html',
  styleUrl: './roster.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RosterComponent implements OnInit {

  loading    = signal(true);
  asProducer = signal<RosterLinkDTO[]>([]);

  inviteIdentifier = signal('');
  inviting         = signal(false);
  inviteError      = signal<string | null>(null);

  searchResults = signal<RosterSearchResult[]>([]);
  actingOnLink  = signal<number | null>(null);

  constructor(
    readonly auth: AuthService,
    private roster: RosterService,
    private router: Router,
  ) {}

  ngOnInit(): void {
    this.reload();
  }

  private reload(): void {
    this.loading.set(true);
    this.roster.mine().subscribe({
      next: res => {
        this.asProducer.set(res.data?.as_producer ?? []);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  onIdentifierChange(value: string): void {
    this.inviteIdentifier.set(value);
    this.inviteError.set(null);
    if (value.trim().length < 2) {
      this.searchResults.set([]);
      return;
    }
    this.roster.searchArtist(value.trim()).subscribe({
      next: res => this.searchResults.set(res.data?.users ?? []),
      error: () => this.searchResults.set([]),
    });
  }

  invite(): void {
    const identifier = this.inviteIdentifier().trim();
    if (!identifier) return;

    this.inviting.set(true);
    this.inviteError.set(null);
    this.roster.invite(identifier).subscribe({
      next: () => {
        this.inviting.set(false);
        this.inviteIdentifier.set('');
        this.searchResults.set([]);
        this.reload();
      },
      error: err => {
        this.inviting.set(false);
        this.inviteError.set(err?.error?.feedback?.message ?? "Impossible d'envoyer l'invitation.");
      },
    });
  }

  revoke(link: RosterLinkDTO): void {
    this.actingOnLink.set(link.id);
    this.roster.revoke(link.id).subscribe({
      next: () => { this.actingOnLink.set(null); this.reload(); },
      error: () => this.actingOnLink.set(null),
    });
  }

  formalize(link: RosterLinkDTO): void {
    this.router.navigate(['/contract-builder'], {
      queryParams: {
        type: 'management',
        title: `Mandat de management — ${link.counterpart.username}`,
        link_id: link.id,
      },
    });
  }

  imgUrl(path: string | null): string {
    if (!path) return '/assets/placeholders/default_profile.png';
    if (path.startsWith('http')) return path;
    return `${environment.apiUrl}/db_assets/${path}`;
  }

  statusLabel(status: RosterLinkDTO['status']): string {
    const labels: Record<RosterLinkDTO['status'], string> = {
      invited:  'Invitation en attente',
      active:   'Actif',
      declined: 'Déclinée',
      revoked:  'Annulée',
      ended:    'Terminé',
    };
    return labels[status];
  }
}
