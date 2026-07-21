import { ChangeDetectionStrategy, Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { PromoService, PromoCode } from '../../services/promo.service';
import { CampaignService, Campaign, CampaignQuota } from '../../services/campaign.service';

/**
 * Panneau « Marketing » — codes promo + campagnes, avec leurs résultats.
 *
 * Partagé par les espaces Beatmaker et Mix Engineer : les deux vendent, les deux
 * remisent, les deux mailent. Un composant unique évite que les deux tableaux de
 * bord divergent au premier ajout de métrique.
 */
@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-marketing-panel',
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './marketing-panel.component.html',
  styleUrls: ['./marketing-panel.component.scss'],
})
export class MarketingPanelComponent implements OnInit {

  private promoSvc    = inject(PromoService);
  private campaignSvc = inject(CampaignService);

  loading   = signal(true);
  promos    = signal<PromoCode[]>([]);
  campaigns = signal<Campaign[]>([]);
  quota     = signal<CampaignQuota | null>(null);

  activePromos = computed(() =>
    this.promos().filter(p => p.is_active && !p.is_expired && !p.is_exhausted),
  );

  /** Utilisations cumulées de tous les codes — le signal « est-ce que ça sert ? ». */
  totalRedemptions = computed(() =>
    this.promos().reduce((sum, p) => sum + (p.redemption_count || 0), 0),
  );

  sentCampaigns = computed(() => this.campaigns().filter(c => c.status === 'sent'));

  scheduledCampaigns = computed(() => this.campaigns().filter(c => c.status === 'scheduled'));

  /** CA réellement attribuable aux campagnes (via les codes promo qu'elles portaient). */
  campaignRevenue = computed(() =>
    this.sentCampaigns().reduce((sum, c) => sum + (c.stats?.revenue ?? 0), 0),
  );

  totalReached = computed(() =>
    this.sentCampaigns().reduce((sum, c) => sum + (c.stats?.sent_count ?? 0), 0),
  );

  totalConversions = computed(() =>
    this.sentCampaigns().reduce((sum, c) => sum + (c.stats?.conversions ?? 0), 0),
  );

  conversionRate = computed(() => {
    const reached = this.totalReached();
    if (!reached) return 0;
    return Math.round((this.totalConversions() / reached) * 1000) / 10;
  });

  /** Codes qui vont expirer sous 7 jours — le moment idéal pour une campagne. */
  expiringSoon = computed(() => {
    const limit = Date.now() + 7 * 24 * 60 * 60 * 1000;
    return this.activePromos().filter(p =>
      p.expires_at && new Date(p.expires_at).getTime() <= limit,
    );
  });

  ngOnInit(): void {
    this.promoSvc.list().subscribe({
      next:  res => { this.promos.set(res.data?.promo_codes ?? []); this.loading.set(false); },
      error: () => { this.promos.set([]); this.loading.set(false); },
    });

    this.campaignSvc.list().subscribe({
      next: res => {
        this.campaigns.set(res.data?.campaigns ?? []);
        this.quota.set(res.data?.quota ?? null);
      },
      error: () => this.campaigns.set([]),
    });
  }
}
