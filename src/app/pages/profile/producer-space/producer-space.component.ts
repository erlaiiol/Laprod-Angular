import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterModule } from '@angular/router';
import { AuthService } from '../../../services/auth.service';
import { RosterService } from '../../../services/roster.service';

// ─────────────────────────────────────────────────────────────────────────────
// PRODUCER SPACE — hub contrats/roster/planning/royalties du producteur.
// Ex-ProducerHomeComponent (src/pages/home/producer-home) : déplacé sous le
// profil suite à l'abandon du système de vue active (roue) — tous les espaces
// par rôle vivent désormais sur /profile/:username plutôt que sur la home.
// Embarqué par ProfileComponent uniquement sur son propre profil, si isProducer().
// ─────────────────────────────────────────────────────────────────────────────

interface QuickAction {
  icon: string;
  title: string;
  desc: string;
  link: string;
  cta: string;
}

@Component({
  selector: 'app-producer-space',
  standalone: true,
  imports: [RouterModule],
  templateUrl: './producer-space.component.html',
  styleUrl: './producer-space.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ProducerSpaceComponent implements OnInit {

  readonly auth  = inject(AuthService);
  private roster = inject(RosterService);

  readonly activeCount  = signal(0);
  readonly pendingCount = signal(0);

  ngOnInit(): void {
    if (!this.auth.isProducer()) return;
    this.roster.mine().subscribe({
      next: res => {
        const links = res.data?.as_producer ?? [];
        this.activeCount.set(links.filter(l => l.status === 'active').length);
        this.pendingCount.set(links.filter(l => l.status === 'invited').length);
      },
      error: () => {},
    });
  }

  readonly actions: QuickAction[] = [
    {
      icon: 'bi-pencil-square',
      title: 'Créer un contrat',
      desc: 'Cession de droits, exclusivités, part SACEM, territoire, durée — configurés clause par clause, exportables en PDF signable.',
      link: '/contract-builder',
      cta: 'Ouvrir le builder',
    },
    {
      icon: 'bi-shield-check',
      title: 'Analyser un contrat',
      desc: 'Dépose n\'importe quel contrat musical : LaProd t\'explique droits, exclusivités et durée avant signature.',
      link: '/contract-analyzer',
      cta: 'Analyser',
    },
  ];
}
