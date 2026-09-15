import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { Capacitor } from '@capacitor/core';
import { Observable, firstValueFrom } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';
import { IS_NATIVE_PLATFORM } from './draft-save.service';
import type { FirebaseMessagingPlugin } from '@capacitor-firebase/messaging';

// ── Service ───────────────────────────────────────────────────────────────────
//
// Notifications push (Firebase Cloud Messaging, mobile natif uniquement).
// Voir docs/roadmap.md § Chantier 2 pour la spécification complète.
//
// Décision structurante : AUCUN push web, jamais. Ce service ne fait rien quand
// IS_NATIVE_PLATFORM est faux, et surtout n'importe même pas le SDK Firebase
// dans ce cas (import() dynamique dans _loadMessaging()) — un import statique
// alourdirait le bundle web initial de plusieurs centaines de kO pour un code
// jamais exécuté, ce qui ferait sauter le budget verrouillé à 850 kB
// (angular.json, config "production"). C'est aussi ce qui rend la décision
// § 2.1 du chantier vérifiable par lecture : aucune tentative de solliciter
// Firebase sur le web.
//
// @capacitor-firebase/messaging, pas @capacitor/push-notifications : ce
// dernier ne renvoie qu'un jeton APNs brut sur iOS (pas un jeton FCM), ce qui
// aurait forcé le backend à gérer deux chemins d'envoi distincts. Le plugin
// Firebase renvoie un vrai jeton FCM sur les deux plateformes — un seul
// utils/push_service.py::send_push() suffit côté serveur.
//
// _loadMessaging() plutôt qu'un import statique + IS_NATIVE_PLATFORM en
// InjectionToken (même pattern que CAPACITOR_FILESYSTEM dans
// draft-save.service.ts) : vi.mock() sur un import dynamique s'est révélé peu
// fiable dans cette suite (hoisting Vitest partagé entre fichiers) — une
// méthode overridable par un spy TestBed l'est.

@Injectable({ providedIn: 'root' })
export class PushService {

  private http     = inject(HttpClient);
  private router   = inject(Router);
  readonly isNative = inject(IS_NATIVE_PLATFORM);
  private url      = `${environment.apiUrl}/api/push`;

  private _initialized = false;
  private _currentToken: string | null = null;

  protected _loadMessaging(): Promise<{ FirebaseMessaging: FirebaseMessagingPlugin }> {
    return import('@capacitor-firebase/messaging');
  }

  /**
   * À appeler une seule fois au démarrage de l'app (App.ngOnInit), après
   * NativeShellService.init(). Pose les listeners de jeton/tap mais ne
   * demande AUCUNE permission — ça reste le rôle de enablePush(), déclenché
   * uniquement par l'activation explicite du toggle dans les réglages.
   */
  async init(): Promise<void> {
    if (!this.isNative || this._initialized) return;
    this._initialized = true;

    const { FirebaseMessaging } = await this._loadMessaging();

    // Le jeton peut être renouvelé par l'OS à tout moment (réinstall, rotation) :
    // sans ce listener, le backend continuerait d'envoyer vers un jeton mort.
    FirebaseMessaging.addListener('tokenReceived', (event) => {
      this._currentToken = event.token;
      this.registerDevice(event.token).subscribe({ error: () => {} });
    });

    // Tap sur la notification (app en arrière-plan ou fermée) : deep-link vers
    // le lien porté par le payload (posé côté job, cf. utils/scheduled_tasks.py).
    FirebaseMessaging.addListener('notificationActionPerformed', (event) => {
      const link = (event.notification?.data as Record<string, string> | undefined)?.['link'];
      if (link) this.router.navigateByUrl(link);
    });

    // Si la permission a déjà été accordée lors d'une session précédente,
    // récupère un jeton frais silencieusement (pas de nouvelle demande OS).
    const { receive } = await FirebaseMessaging.checkPermissions();
    if (receive === 'granted') {
      await this._fetchAndRegisterToken(FirebaseMessaging);
    }
  }

  /**
   * Déclenché UNIQUEMENT par l'activation explicite du toggle « Notifications
   * push » dans les réglages — jamais au premier lancement de l'app. Une
   * demande de permission contextuelle a un taux d'acceptation nettement
   * supérieur à une demande au premier écran, et surtout : solliciter la
   * permission OS avant le consentement produit inverserait l'ordre voulu par
   * docs/roadmap.md § Chantier 2 décision 2.3.
   */
  async enablePush(): Promise<boolean> {
    if (!this.isNative) return false;

    const { FirebaseMessaging } = await this._loadMessaging();
    const { receive } = await FirebaseMessaging.requestPermissions();
    if (receive !== 'granted') return false;

    await this._fetchAndRegisterToken(FirebaseMessaging);
    return true;
  }

  /** Désactive le jeton de cet appareil (retrait du toggle). Le retrait du
   *  consentement (push_opt_in=False) est géré côté serveur par setPreference —
   *  cet appel ne fait que nettoyer l'appareil courant en plus. */
  async disablePush(): Promise<void> {
    if (this._currentToken) {
      await firstValueFrom(this.unregisterDevice(this._currentToken)).catch(() => {});
      this._currentToken = null;
    }
  }

  private async _fetchAndRegisterToken(FirebaseMessaging: FirebaseMessagingPlugin): Promise<void> {
    const { token } = await FirebaseMessaging.getToken();
    this._currentToken = token;
    await firstValueFrom(this.registerDevice(token)).catch(() => {});
  }

  // ── API ───────────────────────────────────────────────────────────────────

  private registerDevice(token: string): Observable<ApiResponse<void>> {
    const platform = Capacitor.getPlatform() === 'ios' ? 'ios' : 'android';
    return this.http.post<ApiResponse<void>>(`${this.url}/register`, { token, platform });
  }

  private unregisterDevice(token: string): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(`${this.url}/unregister`, { token });
  }

  getPreference(): Observable<ApiResponse<{ push_opt_in: boolean }>> {
    return this.http.get<ApiResponse<{ push_opt_in: boolean }>>(`${this.url}/preference`);
  }

  setPreference(enabled: boolean): Observable<ApiResponse<{ push_opt_in: boolean }>> {
    return this.http.put<ApiResponse<{ push_opt_in: boolean }>>(`${this.url}/preference`, { enabled });
  }
}
