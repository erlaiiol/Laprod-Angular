import { Injectable, InjectionToken, NgZone, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { registerPlugin, type PluginListenerHandle } from '@capacitor/core';
import { Observable, firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';
import type { PlanKey } from './auth.service';

/** L'utilisateur a refermé la feuille d'achat d'Apple : ce n'est pas une erreur. */
export class IosPurchaseCancelledError extends Error {}

/**
 * Achat en attente d'une validation externe (« Demander l'autorisation
 * d'achat »). Rien à créditer pour l'instant : la transaction arrivera plus
 * tard par onTransactionUpdated().
 */
export class IosPurchasePendingError extends Error {}

interface SignedTransaction { transactionJWS: string; }

/** Un produit tel que l'App Store le décrit (prix dans la devise du compte Apple). */
export interface StoreProduct {
  productId:    string;
  displayName:  string;
  description:  string;
  displayPrice: string;
}

/** Miroir exact de ios/App/App/StoreKitPurchasePlugin.swift. */
export interface StoreKitPurchasePlugin {
  getProducts(options: { productIds: string[] }): Promise<{ products: StoreProduct[] }>;
  purchase(options: { productId: string; appAccountToken?: string }): Promise<SignedTransaction>;
  restorePurchases(): Promise<{ transactions: SignedTransaction[] }>;
  getActiveEntitlements(): Promise<{ transactions: SignedTransaction[] }>;
  addListener(
    eventName: 'transactionsUpdated',
    listenerFunc: (event: SignedTransaction) => void,
  ): Promise<PluginListenerHandle>;
}

export const STOREKIT_PURCHASE = new InjectionToken<StoreKitPurchasePlugin>(
  'StoreKitPurchase',
  { factory: () => registerPlugin<StoreKitPurchasePlugin>('StoreKitPurchase') },
);

export interface AppleProductsData {
  configured:        boolean;
  products:          { plan: PlanKey; product_id: string }[];
  app_account_token: string;
}

export interface AppleVerifyData {
  credited:          number;
  subscription_plan: PlanKey;
  is_premium_active: boolean;
}

/** Une offre achetable : le palier LaProd + son produit App Store. */
export interface IosPlanOffer {
  plan:         PlanKey;
  productId:    string;
  displayPrice: string;
}

/**
 * Abonnement LaProd+ acheté dans l'app iOS (StoreKit 2) — le pendant iOS du
 * checkout Stripe de la page Premium.
 *
 * Ce service ne manipule que des transactions SIGNÉES opaques : il ne décide
 * jamais qu'un achat est valide, c'est le serveur qui revérifie la signature
 * d'Apple avant de créditer (POST /api/apple-iap/verify). Une même transaction
 * peut lui être envoyée plusieurs fois sans risque : elle n'est créditée qu'une
 * fois.
 *
 * N'est appelé que dans l'app iOS (cf. IosPurchasePolicyService).
 */
@Injectable({ providedIn: 'root' })
export class IosPurchaseService {

  private http   = inject(HttpClient);
  private zone   = inject(NgZone);
  private plugin = inject(STOREKIT_PURCHASE);
  private url    = `${environment.apiUrl}/api/apple-iap`;

  private accountToken: string | null = null;

  /**
   * Offres achetables : identifiants de produit fournis par le serveur, prix
   * fournis par l'App Store. Un palier dont le produit n'existe pas (encore)
   * côté App Store est simplement absent de la liste.
   */
  async loadOffers(): Promise<IosPlanOffer[]> {
    const res = await firstValueFrom(
      this.http.get<ApiResponse<AppleProductsData>>(`${this.url}/products`),
    );
    const data = res.data;
    if (!data?.configured || !data.products.length) return [];
    this.accountToken = data.app_account_token;

    const { products } = await this.plugin.getProducts({
      productIds: data.products.map(p => p.product_id),
    });
    const byId = new Map(products.map(p => [p.productId, p]));
    return data.products
      .filter(p => byId.has(p.product_id))
      .map(p => ({
        plan:         p.plan,
        productId:    p.product_id,
        displayPrice: byId.get(p.product_id)!.displayPrice,
      }));
  }

  /** Ouvre la feuille d'achat d'Apple, puis fait créditer l'achat par le serveur. */
  async purchase(productId: string): Promise<AppleVerifyData> {
    let signed: SignedTransaction;
    try {
      signed = await this.plugin.purchase({
        productId,
        appAccountToken: this.accountToken ?? undefined,
      });
    } catch (error) {
      const code = (error as { code?: string } | null)?.code;
      if (code === 'USER_CANCELLED') throw new IosPurchaseCancelledError();
      if (code === 'PENDING') throw new IosPurchasePendingError();
      throw error;
    }
    return firstValueFrom(this.verify([signed.transactionJWS]));
  }

  /**
   * Bouton « Restaurer mes achats » : resynchronise l'historique avec Apple
   * (peut demander le mot de passe du compte Apple) et fait créditer ce qui ne
   * l'aurait pas été.
   */
  async restore(): Promise<AppleVerifyData | null> {
    const { transactions } = await this.plugin.restorePurchases();
    return this.verifyAll(transactions);
  }

  /**
   * Rattrapage silencieux, sans appel à Apple ni demande de mot de passe :
   * couvre l'achat payé dont la vérification serveur a échoué (réseau coupé
   * juste après le paiement).
   */
  async reconcile(): Promise<AppleVerifyData | null> {
    const { transactions } = await this.plugin.getActiveEntitlements();
    return this.verifyAll(transactions);
  }

  /**
   * Transaction arrivée hors de tout achat en cours (validation parentale,
   * achat interrompu puis repris). Les callbacks de plugin Capacitor sortent
   * de la zone Angular : on y revient avant de prévenir l'appelant.
   */
  onTransactionUpdated(callback: (result: AppleVerifyData) => void): Promise<PluginListenerHandle> {
    return this.plugin.addListener('transactionsUpdated', event => {
      this.verify([event.transactionJWS]).subscribe({
        next: data => this.zone.run(() => callback(data)),
        error: () => { /* rattrapé au prochain reconcile() */ },
      });
    });
  }

  private async verifyAll(transactions: SignedTransaction[]): Promise<AppleVerifyData | null> {
    if (!transactions.length) return null;
    return firstValueFrom(this.verify(transactions.map(t => t.transactionJWS)));
  }

  private verify(transactions: string[]): Observable<AppleVerifyData> {
    return new Observable<AppleVerifyData>(subscriber => {
      const sub = this.http.post<ApiResponse<AppleVerifyData>>(
        `${this.url}/verify`, { transactions },
      ).subscribe({
        next: res => {
          if (res.success && res.data) { subscriber.next(res.data); subscriber.complete(); }
          else subscriber.error(res);
        },
        error: err => subscriber.error(err),
      });
      return () => sub.unsubscribe();
    });
  }
}
