import { Injectable, InjectionToken, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Capacitor } from '@capacitor/core';
import { environment } from '../../environments/environment';
import { ToastService } from './toast.service';

/**
 * Vrai uniquement dans l'app iOS (pas dans Safari sur iPhone). Token plutôt
 * qu'un appel direct à Capacitor pour pouvoir le forcer dans les specs — même
 * raison que IS_NATIVE_PLATFORM (draft-save.service.ts).
 */
export const IS_IOS_APP = new InjectionToken<boolean>(
  'IsIosApp',
  { factory: () => Capacitor.getPlatform() === 'ios' },
);

/** Catégories d'achat — mêmes clés que utils/apple_iap.py::ios_purchase_policy. */
export type PurchaseCategory = 'subscription' | 'beat_license' | 'mix_order' | 'campaign_boost';

/**
 *   stripe       paiement Stripe habituel (toujours le cas sur le web et Android)
 *   iap          achat intégré Apple (StoreKit) — abonnement uniquement
 *   unavailable  rien à vendre ici : ni bouton, ni lien, ni invitation à aller
 *                payer ailleurs
 */
export type PurchaseMode = 'stripe' | 'iap' | 'unavailable';

type IosPolicy = Record<PurchaseCategory, PurchaseMode>;

const UNAVAILABLE_MESSAGE = "Cet achat n'est pas disponible dans l'application iOS.";

/**
 * Ce que l'app a le droit de vendre, et par quel moyen.
 *
 * Apple refuse en review (guideline 3.1.1) une app iOS qui vend un contenu
 * numérique par un autre moyen que son achat intégré — y compris un simple
 * lien vers le site. TOUT point d'entrée vers un paiement doit donc passer par
 * ce service : `mode()` pour choisir quoi afficher, `guard()` juste avant la
 * redirection Stripe. Voir docs/development-rules.md (R18) et
 * docs/architecture.md § Paiements sur iOS.
 *
 * Hors de l'app iOS, tout est 'stripe' et aucun appel réseau n'est fait. Dans
 * l'app iOS, la politique vient du serveur ; tant qu'elle n'est pas chargée
 * (ou si l'appel échoue), tout est 'unavailable' — on préfère un bouton absent
 * à un paiement qu'Apple n'a pas validé.
 */
@Injectable({ providedIn: 'root' })
export class IosPurchasePolicyService {

  private http  = inject(HttpClient);
  private toast = inject(ToastService);

  readonly isIosApp = inject(IS_IOS_APP);

  private readonly policy = signal<IosPolicy | null>(null);

  /** La politique est-elle connue ? (toujours vrai hors de l'app iOS) */
  readonly ready = computed(() => !this.isIosApp || this.policy() !== null);

  readonly subscription  = computed(() => this.mode('subscription'));
  readonly beatLicense   = computed(() => this.mode('beat_license'));
  readonly mixOrder      = computed(() => this.mode('mix_order'));
  readonly campaignBoost = computed(() => this.mode('campaign_boost'));

  readonly unavailableMessage = UNAVAILABLE_MESSAGE;

  constructor() {
    if (this.isIosApp) this.load();
  }

  mode(category: PurchaseCategory): PurchaseMode {
    if (!this.isIosApp) return 'stripe';
    return this.policy()?.[category] ?? 'unavailable';
  }

  /**
   * À appeler juste avant toute redirection vers Stripe. Renvoie false (et
   * prévient l'utilisateur) si cette catégorie ne peut pas être payée par
   * Stripe ici — dernier filet si un bouton avait échappé au masquage.
   */
  guard(category: PurchaseCategory): boolean {
    if (this.mode(category) === 'stripe') return true;
    this.toast.showToast({ level: 'info', message: UNAVAILABLE_MESSAGE });
    return false;
  }

  private load(): void {
    this.http.get<{ data?: { policy?: Partial<IosPolicy> } }>(
      `${environment.apiUrl}/api/apple-iap/policy`,
    ).subscribe({
      next: res => {
        const p = res?.data?.policy ?? {};
        const pick = (v: unknown, allowed: PurchaseMode[]): PurchaseMode =>
          allowed.includes(v as PurchaseMode) ? (v as PurchaseMode) : 'unavailable';
        this.policy.set({
          // L'abonnement ne peut JAMAIS être 'stripe' dans l'app iOS, quoi que
          // réponde le serveur.
          subscription:   pick(p.subscription,   ['iap', 'unavailable']),
          beat_license:   pick(p.beat_license,   ['stripe', 'unavailable']),
          mix_order:      pick(p.mix_order,      ['stripe', 'unavailable']),
          campaign_boost: pick(p.campaign_boost, ['stripe', 'unavailable']),
        });
      },
      error: () => this.policy.set({
        subscription: 'unavailable', beat_license: 'unavailable',
        mix_order: 'unavailable', campaign_boost: 'unavailable',
      }),
    });
  }
}
