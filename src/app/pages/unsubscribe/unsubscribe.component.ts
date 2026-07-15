import { ChangeDetectionStrategy, Component, OnInit, signal, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { CampaignService } from '../../services/campaign.service';

/**
 * Désinscription des emails marketing, depuis le lien présent dans chaque campagne.
 *
 * Volontairement PUBLIQUE : exiger une connexion pour se désinscrire rendrait la
 * sortie plus difficile que l'entrée, ce que la loi interdit (art. L.34-5 CPCE,
 * « moyen simple et gratuit »). Le token signé porte l'identité.
 *
 * La désinscription est déclenchée automatiquement à l'ouverture : l'utilisateur a
 * déjà cliqué « me désinscrire » dans son email, lui redemander confirmation ici
 * serait une friction de mauvaise foi.
 */
@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-unsubscribe',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './unsubscribe.component.html',
  styleUrls: ['./unsubscribe.component.scss'],
})
export class UnsubscribeComponent implements OnInit {

  private route       = inject(ActivatedRoute);
  private campaignSvc = inject(CampaignService);

  state   = signal<'loading' | 'done' | 'error'>('loading');
  message = signal('');

  ngOnInit(): void {
    const token = this.route.snapshot.queryParamMap.get('token');
    if (!token) {
      this.state.set('error');
      this.message.set('Lien de désinscription invalide.');
      return;
    }

    this.campaignSvc.unsubscribe(token).subscribe({
      next: res => {
        this.state.set('done');
        this.message.set(res.feedback?.message ?? 'Vous êtes désinscrit.');
      },
      error: err => {
        this.state.set('error');
        this.message.set(
          err?.error?.feedback?.message ?? 'Ce lien de désinscription est invalide.',
        );
      },
    });
  }
}
