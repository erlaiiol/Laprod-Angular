import { ChangeDetectionStrategy, Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { ContractBuilderService, ContractSummary, ContractType } from '../../services/contract-builder.service';
import { RosterService } from '../../services/roster.service';
import { ToastService } from '../../services/toast.service';
import { AuthService } from '../../services/auth.service';
import { FormatDatePipe } from '../../pipes/format-date.pipe';
import { BetaBadgeComponent } from '../../components/beta-badge/beta-badge.component';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-contract-builder',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, FormatDatePipe, BetaBadgeComponent],
  templateUrl: './contract-builder.component.html',
  styleUrl: './contract-builder.component.scss',
})
export class ContractBuilderComponent implements OnInit {

  private auth = inject(AuthService);
  readonly isPro      = this.auth.isPro;
  readonly isLoggedIn = this.auth.isLoggedIn;
  readonly canManage  = this.auth.canUseManagementContract;

  loading   = signal(false);
  creating  = signal(false);
  contracts = signal<ContractSummary[]>([]);
  newTitle  = signal('');
  newType   = signal<ContractType>('exploitation');
  deletingId = signal<number | null>(null);

  readonly contractTypes: { value: ContractType; icon: string; label: string; desc: string; placeholder: string; minPlanLabel: string }[] = [
    {
      value: 'exploitation',
      icon: 'bi-vinyl-fill',
      label: "Contrat d'exploitation",
      desc: 'Licence, cession, édition, distribution d\'une œuvre musicale.',
      placeholder: "Titre de l'œuvre ou du projet...",
      minPlanLabel: 'Pro',
    },
    {
      value: 'performance',
      icon: 'bi-mic-fill',
      label: 'Contrat de représentation',
      desc: 'Concert, festival, DJ set, showcase, évènement privé.',
      placeholder: "Nom de l'évènement ou du concert...",
      minPlanLabel: 'Pro',
    },
    {
      value: 'management',
      icon: 'bi-briefcase-fill',
      label: 'Contrat de management',
      desc: 'Mandat de management entre un producteur et un artiste de son roster.',
      placeholder: "Nom de l'artiste ou du projet...",
      minPlanLabel: 'Premium',
    },
  ];

  typeLabel(t: ContractType): string {
    return this.contractTypes.find(ct => ct.value === t)?.label ?? '';
  }

  placeholderForType(): string {
    return this.contractTypes.find(ct => ct.value === this.newType())?.placeholder ?? '';
  }

  /** Chaque type de contrat a son propre seuil de palier — le management
   *  (Premium+) est accessible plus tôt que le reste du builder (Pro+). */
  canCreateType(type: ContractType): boolean {
    return type === 'management' ? this.canManage() : this.isPro();
  }

  canCreateSelected(): boolean {
    return this.canCreateType(this.newType());
  }

  /** Renseigné via ?link_id=... quand on arrive depuis "Formaliser par contrat"
   *  sur la fiche roster : le contrat créé est automatiquement attaché au lien. */
  private pendingRosterLinkId: number | null = null;

  constructor(
    private svc:    ContractBuilderService,
    private roster: RosterService,
    private router: Router,
    private route:  ActivatedRoute,
    private toast:  ToastService,
  ) {}

  ngOnInit(): void {
    if (this.isLoggedIn()) this.load();

    const params = this.route.snapshot.queryParamMap;
    const type = params.get('type');
    if (type === 'management' || type === 'performance' || type === 'exploitation') {
      this.newType.set(type);
    }
    const title = params.get('title');
    if (title) this.newTitle.set(title);
    const linkId = params.get('link_id');
    if (linkId) this.pendingRosterLinkId = Number(linkId);
  }

  load(): void {
    this.loading.set(true);
    this.svc.listContracts().subscribe({
      next: res => {
        if (res.success && res.data) this.contracts.set(res.data.contracts);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  create(): void {
    const title = this.newTitle().trim();
    if (!title) return;
    this.creating.set(true);
    this.svc.createContract(title, this.newType()).subscribe({
      next: res => {
        this.creating.set(false);
        if (res.success && res.data) {
          const contractId = res.data.contract.id;
          if (this.pendingRosterLinkId) {
            // Attachement au lien roster best-effort : un échec ne doit pas
            // bloquer l'accès au contrat qui, lui, a bien été créé.
            this.roster.attachContract(this.pendingRosterLinkId, contractId).subscribe({ error: () => {} });
          }
          this.router.navigate(['/contract-builder', contractId]);
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
      },
      error: err => {
        this.creating.set(false);
        const msg = err?.error?.feedback?.message ?? 'Erreur lors de la création.';
        this.toast.showToast({ level: 'error', message: msg });
      },
    });
  }

  open(id: number): void {
    this.router.navigate(['/contract-builder', id]);
  }

  /** Brouillons uniquement — le backend refuse un contrat finalisé (409). */
  deleteDraft(contract: ContractSummary, event: MouseEvent): void {
    event.stopPropagation(); // ne pas déclencher open() sur la ligne
    if (!confirm(`Supprimer le brouillon "${contract.title}" ? C'est définitif.`)) return;

    this.deletingId.set(contract.id);
    this.svc.deleteContract(contract.id).subscribe({
      next: () => {
        this.deletingId.set(null);
        this.contracts.update(list => list.filter(c => c.id !== contract.id));
      },
      error: err => {
        this.deletingId.set(null);
        const msg = err?.error?.feedback?.message ?? 'Erreur lors de la suppression.';
        this.toast.showToast({ level: 'error', message: msg });
      },
    });
  }

}
