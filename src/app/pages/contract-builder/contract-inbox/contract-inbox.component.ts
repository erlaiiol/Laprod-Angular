import { ChangeDetectionStrategy, Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule, Router } from '@angular/router';
import { ContractBuilderService, ContractShareEntry } from '../../../services/contract-builder.service';
import { environment } from '../../../../environments/environment';

// ─────────────────────────────────────────────────────────────────────────────
// Inbox/outbox de signature de contrat : role-agnostique (n'importe quel
// utilisateur peut être invité à signer, indépendamment de is_producer/is_artist),
// d'où une page autonome plutôt qu'un onglet dashboard — voir roster.component.ts
// pour le précédent UI le plus proche (listes "de mon côté" / "de l'autre côté").
// ─────────────────────────────────────────────────────────────────────────────

@Component({
  selector: 'app-contract-inbox',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './contract-inbox.component.html',
  styleUrl: './contract-inbox.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ContractInboxComponent implements OnInit {

  loading  = signal(true);
  sent     = signal<ContractShareEntry[]>([]);
  received = signal<ContractShareEntry[]>([]);

  constructor(private svc: ContractBuilderService, private router: Router) {}

  ngOnInit(): void {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.svc.getInbox().subscribe({
      next: res => {
        this.sent.set(res.data?.sent ?? []);
        this.received.set(res.data?.received ?? []);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  open(id: number): void {
    this.router.navigate(['/contract-builder', id]);
  }

  imgUrl(path: string | null | undefined): string {
    if (!path) return '/assets/placeholders/default_profile.png';
    if (path.startsWith('http')) return path;
    return `${environment.apiUrl}/db_assets/${path}`;
  }

  signatureStatusLabel(status: ContractShareEntry['signature_status']): string {
    const labels: Record<ContractShareEntry['signature_status'], string> = {
      not_sent: 'Non envoyé',
      pending:  'En attente',
      declined: 'Refusé',
      signed:   'Signé',
    };
    return labels[status];
  }

  inviteStatusLabel(status: ContractShareEntry['my_invite_status']): string {
    if (!status) return '';
    const labels: Record<string, string> = {
      none: 'Aucune invitation',
      pending: 'À signer',
      signed: 'Signé',
      declined: 'Décliné',
    };
    return labels[status] ?? status;
  }
}
