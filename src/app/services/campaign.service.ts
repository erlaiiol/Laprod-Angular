import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';

export type CampaignSegment = 'buyers' | 'favorites' | 'listeners' | 'affinity' | 'all';
export type CampaignStatus  = 'draft' | 'scheduled' | 'sending' | 'sent' | 'failed' | 'cancelled';

/** Libellés et promesse de chaque segment — le vendeur choisit une intention,
 *  pas une requête SQL. */
export const SEGMENT_LABELS: Record<CampaignSegment, string> = {
  buyers:    'Mes acheteurs',
  favorites: 'Ceux qui m\'ont mis en favori',
  listeners: 'Mes auditeurs récents',
  affinity:  'Profils au goût proche du mien',
  all:       'Toute la plateforme',
};

export const SEGMENT_HINTS: Record<CampaignSegment, string> = {
  buyers:    'Ont déjà acheté un beat ou commandé un mix chez vous. L\'audience la plus qualifiée.',
  favorites: 'Ont ajouté un de vos beats à leurs favoris. Un signal d\'intérêt fort et explicite.',
  listeners: 'Ont écouté un de vos beats ces 90 derniers jours. Plus large, moins engagé.',
  affinity:  'Ne vous connaissent pas encore, mais écoutent et aiment le même style que vous. Des prospects tièdes qu\'aucun autre segment n\'atteint.',
  all:       'Tous les membres de LaProd ayant accepté de recevoir des offres. Diffusion payante.',
};

export interface CampaignStats {
  recipient_count: number;
  sent_count:      number;
  failed_count:    number;
  conversions:     number;   // destinataires ayant réellement utilisé le code promo
  revenue:         number;   // CA net généré par ces conversions
  discount_given:  number;
}

export interface Campaign {
  id:               number;
  subject:          string;
  body:             string;
  segment:          CampaignSegment;
  status:           CampaignStatus;
  promo_code_id:    number | null;
  promo_code:       string | null;
  promo_percent:    number | null;
  requires_payment: boolean;
  is_paid:          boolean;
  is_editable:      boolean;
  amount_paid:      number | null;
  scheduled_for:    string | null;
  sent_at:          string | null;
  created_at:       string | null;
  stats:            CampaignStats;
}

export interface CampaignQuota {
  used:            number;
  max:             number;
  remaining:       number;
  cooldown_days:   number;
  next_allowed_at: string | null;
}

export interface CampaignPromoRef {
  id: number; code: string; percent: number; scope: string;
}

/** Brouillon de campagne pré-rempli, dérivé de l'activité récente du vendeur. */
export interface CampaignTemplate {
  id:            string;
  label:         string;
  icon:          string;   // nom d'icône bootstrap (sans le préfixe bi-)
  subject:       string;
  body:          string;
  segment:       CampaignSegment;
  promo_code_id: number | null;
}

export interface CampaignContext {
  audiences:           Record<CampaignSegment, number>;
  slots:               string[];   // créneaux d'envoi proposés par le serveur
  quota:               CampaignQuota;
  promo_codes:         CampaignPromoRef[];
  templates:           CampaignTemplate[];
  super_premium_price: number;
}

export interface CampaignListData {
  campaigns:  Campaign[];
  quota:      CampaignQuota;
  can_create: boolean;
}

export interface CampaignPayload {
  subject:        string;
  body:           string;
  segment:        CampaignSegment;
  promo_code_id?: number | null;
}

@Injectable({ providedIn: 'root' })
export class CampaignService {

  private http = inject(HttpClient);
  private url  = `${environment.apiUrl}/api/campaigns`;

  list(): Observable<ApiResponse<CampaignListData>> {
    return this.http.get<ApiResponse<CampaignListData>>(this.url);
  }

  context(): Observable<ApiResponse<CampaignContext>> {
    return this.http.get<ApiResponse<CampaignContext>>(`${this.url}/context`);
  }

  create(payload: CampaignPayload): Observable<ApiResponse<{ campaign: Campaign }>> {
    return this.http.post<ApiResponse<{ campaign: Campaign }>>(this.url, payload);
  }

  update(id: number, payload: CampaignPayload): Observable<ApiResponse<{ campaign: Campaign }>> {
    return this.http.patch<ApiResponse<{ campaign: Campaign }>>(`${this.url}/${id}`, payload);
  }

  /** Planifie l'envoi. Rien ne part immédiatement : le serveur dispatche à l'heure dite. */
  schedule(id: number, scheduledFor: string):
      Observable<ApiResponse<{ campaign: Campaign; audience_size: number }>> {
    return this.http.post<ApiResponse<{ campaign: Campaign; audience_size: number }>>(
      `${this.url}/${id}/schedule`, { scheduled_for: scheduledFor },
    );
  }

  cancel(id: number): Observable<ApiResponse<{ campaign: Campaign }>> {
    return this.http.post<ApiResponse<{ campaign: Campaign }>>(`${this.url}/${id}/cancel`, {});
  }

  remove(id: number): Observable<ApiResponse<{ deleted: boolean }>> {
    return this.http.delete<ApiResponse<{ deleted: boolean }>>(`${this.url}/${id}`);
  }

  /** Super Premium : paiement unique débloquant la diffusion à toute la plateforme. */
  checkoutSuperPremium(id: number): Observable<ApiResponse<{ checkout_url: string; price: number }>> {
    return this.http.post<ApiResponse<{ checkout_url: string; price: number }>>(
      `${this.url}/${id}/checkout`, {},
    );
  }

  verifyPayment(sessionId: string): Observable<ApiResponse<{ campaign: Campaign }>> {
    return this.http.post<ApiResponse<{ campaign: Campaign }>>(
      `${this.url}/verify`, { session_id: sessionId },
    );
  }

  // ── Consentement (côté destinataire) ───────────────────────────────────────

  getMarketingPreferences(): Observable<ApiResponse<{ marketing_opt_in: boolean; email_verified: boolean }>> {
    return this.http.get<ApiResponse<{ marketing_opt_in: boolean; email_verified: boolean }>>(
      `${this.url}/marketing-preferences`,
    );
  }

  setMarketingOptIn(optIn: boolean): Observable<ApiResponse<{ marketing_opt_in: boolean }>> {
    return this.http.put<ApiResponse<{ marketing_opt_in: boolean }>>(
      `${this.url}/marketing-preferences`, { marketing_opt_in: optIn },
    );
  }

  /** Désinscription par token — public, sans authentification (art. L.34-5 CPCE :
   *  se désinscrire doit être au moins aussi simple que de s'inscrire). */
  unsubscribe(token: string): Observable<ApiResponse<{ unsubscribed: boolean }>> {
    return this.http.post<ApiResponse<{ unsubscribed: boolean }>>(
      `${this.url}/unsubscribe`, { token },
    );
  }
}
