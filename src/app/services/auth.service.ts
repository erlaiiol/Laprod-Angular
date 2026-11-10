import { computed, inject, Injectable, signal } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { catchError, finalize, from, map, Observable, of, shareReplay, switchMap, tap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { Router } from '@angular/router';
import { Capacitor } from '@capacitor/core';
import { NativeShellService } from './native-shell.service';
import { AuthStorageService } from './auth-storage.service';
import { App } from '@capacitor/app';

/**
 * Paliers d'abonnement — miroir de utils/plans.py (PLAN_ORDER).
 * L'ordre est significatif : il sert aux comparaisons « au moins ce palier ».
 */
export const PLAN_ORDER = ['free', 'premium', 'semi_pro', 'pro_structure'] as const;
export type PlanKey = (typeof PLAN_ORDER)[number];

export const PLAN_LABELS: Record<PlanKey, string> = {
  free:          'Découverte',
  premium:       'Premium',
  semi_pro:      'Semi-Pro',
  pro_structure: 'Pro Structuré',
};

/** Capacités calculées par le serveur — la seule source de vérité. */
export interface PlanCapabilities {
  can_set_custom_prices:    boolean;
  can_offer_exclusive:      boolean;
  can_use_contract_builder: boolean;
  can_do_mastering:         boolean;
  /** null = illimité, 0 = aucun accès. */
  contract_quota:           number | null;
  /** Nouveaux beats publiables par jour. Le catalogue total en ligne est illimité. */
  uploads_per_day:          number;
  /** Formaliser un lien roster par un contrat de management. Le lien roster et
   *  le rétroplanning partagé restent libres à tous les paliers : seule cette
   *  capacité et can_view_royalties sont gatées Premium+. */
  can_use_management_contract: boolean;
  can_view_royalties:          boolean;
}

interface LoginSuccess {
  success: true;
  feedback: { level: string; message: string };
  code? : string,
    data: {
    tokens: { access_token: string; refresh_token: string };
    user: User;
  };

}

interface LoginError {
  success: false;
  feedback: { level: string; message: string };
  code?: string;
  data?: { password_email?: string; confirmation_email?: string };
}

type LoginResponse = LoginSuccess | LoginError;

export interface User {
    id: number,
    username: string,
    email: string,
    profile_image: string,
    roles : {
      is_admin:                       boolean;
      is_beatmaker:                   boolean;
      is_mix_engineer:                boolean;
      is_artist:                      boolean;
      is_producer:                    boolean;
      is_mixmaster_engineer:          boolean;
      is_certified_producer_arranger: boolean;
      mixmaster_sample_submitted:     boolean;
    },
    user_type_selected:  boolean,
    email_verified:      boolean,
    notif_count:         number,
    upload_track_tokens:     number,
    topline_tokens:          number,
    is_premium:              boolean,
    subscription_plan:       PlanKey,
    /** Capacités calculées PAR LE SERVEUR. Le front les lit, il ne les redérive
     *  jamais : une règle d'autorisation dupliquée en Angular finirait par se
     *  désynchroniser de celle qui protège réellement l'API. */
    capabilities?:           PlanCapabilities,
    preferred_tag_category:  string | null,
    instagram?: string | null,
    twitter?:   string | null,
    youtube?:   string | null,
    stripe_onboarding_complete?: boolean,
}


export interface MeResponse {
  success: boolean,
  data: { user: User },
}


export interface RegisterSuccess{
  success: true,
  feedback: { level: string; message:string;};
  code?: string;
  data: {
    user: NewUser;
  }
}

export interface RegisterError{
  success : false;
  feedback: { level: string; message: string};
  code?: string;
}

type RegisterResponse = RegisterSuccess | RegisterError;

export interface NewUser {
  username: string;
  email: string;
}

export interface OauthExchangeData {
  tokens:         { access_token: string; refresh_token: string };
  user:           User;
  next:           string;           // '/', 'select-role', 'complete-profile'
  suggested_name: string;
}

export interface CompleteOauthProfileData {
  tokens: { access_token: string; refresh_token: string };
  user:   User;
  next:   string;
}

export interface AppleNativeResult {
  success: boolean;
  data?:   OauthExchangeData;
  feedback?: { message: string };
  code?:   string;
}





@Injectable({
  providedIn: 'root',
})

export class AuthService {  

  private authUrl = `${environment.apiUrl}/api/auth`

  private nativeShell = inject(NativeShellService);
  private storage = inject(AuthStorageService);

  constructor(private http:HttpClient, private router:Router) {
    // Reprendre le timer si l'utilisateur était déjà connecté (rechargement de page)
    const token = this.getToken();
    if (token) this._scheduleProactiveRefresh(token);
  }


  /** Bootstrap waits for native credentials before guards and HTTP requests run. */
  async initialize(): Promise<void> {
    await this.storage.initialize();
    this._currentUser.set(this.getUser());
    const token = this.getToken();
    if (token) this._scheduleProactiveRefresh(token);
    if (this.storage.native) {
      await App.addListener('appStateChange', ({ isActive }) => {
        if (isActive && this.isLoggedIn()) {
          this.refreshIfExpiringSoon().subscribe({ error: () => {} });
        }
      });
    }
    window.addEventListener('online', () => {
      if (this.isLoggedIn()) this.refreshIfExpiringSoon().subscribe({ error: () => {} });
    });
  }

  // ── Timer de rafraîchissement proactif ───────────────────────────────────────

  private _refreshTimer?: ReturnType<typeof setTimeout>;

  /**
   * Planifie un rafraîchissement automatique du token 5 minutes avant son expiration.
   * S'enchaîne avec chaque nouveau token pour maintenir la session vivante indéfiniment
   * (tant que le refresh_token reste valide).
   */
  private _scheduleProactiveRefresh(token: string): void {
    if (this._refreshTimer) clearTimeout(this._refreshTimer);
    try {
      const payload     = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      const expiresInMs = payload.exp * 1000 - Date.now();
      if (expiresInMs <= 0) return; // déjà expiré — l'intercepteur gère le 401
      // Rafraîchir 5 min avant expiration, minimum 30 s pour éviter les boucles
      const delay = Math.max(30_000, expiresInMs - 5 * 60 * 1000);
      this._refreshTimer = setTimeout(() => {
        if (!this.getToken() || !this.isLoggedIn()) return;
        this.refreshToken().subscribe({
          next:  newToken => this._scheduleProactiveRefresh(newToken),
          error: () => { /* token expiré/révoqué — l'intercepteur gère le prochain 401 */ },
        });
      }, delay);
    } catch { /* JWT mal formé — l'intercepteur gèrera */ }
  }

  /** Renvoie true si l'access_token JWT est expiré (selon son claim `exp`). */
  isTokenExpired(): boolean {
    const token = this.getToken();
    if (!token) return true;
    try {
      const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      return payload.exp * 1000 < Date.now();
    } catch { return true; }
  }


  //// ======================================================
  //// VARIABLES BLOCK
  //// ======================================================

  private _currentUser = signal<User | null>(this.getUser());
  readonly currentUser = this._currentUser.asReadonly();

  readonly isLoggedIn = computed(() => this._currentUser() !== null);

  readonly isAdmin = computed(() => this._currentUser()?.roles?.is_admin || false);
  readonly isBeatmaker = computed(() => this._currentUser()?.roles?.is_beatmaker || false);
  readonly isMixEngineer = computed(() => this._currentUser()?.roles?.is_mix_engineer || false);
  /** Certifié par un admin (échantillon validé) — condition réelle pour vendre des
   *  prestations Mix/Master (codes promo, campagnes), contrairement à isMixEngineer
   *  qui n'est qu'une auto-déclaration non vérifiée. */
  readonly isCertifiedMixEngineer = computed(() => this._currentUser()?.roles?.is_mixmaster_engineer || false);
  readonly isArtist = computed(() => this._currentUser()?.roles?.is_artist || false);
  /** Auto-déclaré, sans certification (contrairement à isCertifiedMixEngineer). */
  readonly isProducer = computed(() => this._currentUser()?.roles?.is_producer || false);

  readonly mixSamplePending = computed(() =>
    this._currentUser()?.roles?.is_mix_engineer === true &&
    this._currentUser()?.roles?.mixmaster_sample_submitted === false
  );

  /** Un abonnement payant est-il actif (quel que soit le palier) ? */
  readonly isPremium = computed(() => {
    const u = this._currentUser();
    return !!u && u.is_premium && u.subscription_plan !== 'free';
  });

  /** Palier actif, normalisé (retombe sur 'free' si l'abonnement a expiré). */
  readonly plan = computed<PlanKey>(() => {
    const u = this._currentUser();
    return u && u.is_premium ? u.subscription_plan : 'free';
  });

  /** Le palier actif est-il au moins `minimum` ? Un rang, pas une cascade de
   *  comparaisons : ajouter un palier ne casse aucun appelant. */
  planAtLeast(minimum: PlanKey): boolean {
    return PLAN_ORDER.indexOf(this.plan()) >= PLAN_ORDER.indexOf(minimum);
  }

  /** Pro Structuré (accès total au contract builder). */
  readonly isPro = computed(() => this.planAtLeast('pro_structure'));

  /** Libellé lisible du palier actif. */
  readonly planLabel = computed(() => PLAN_LABELS[this.plan()]);

  // ── Capacités : lues du serveur, jamais recalculées ────────────────────────
  private caps = computed<PlanCapabilities | null>(
    () => this._currentUser()?.capabilities ?? null,
  );

  readonly canSetCustomPrices   = computed(() => this.caps()?.can_set_custom_prices    ?? false);
  readonly canOfferExclusive    = computed(() => this.caps()?.can_offer_exclusive      ?? false);
  readonly canUseContractBuilder = computed(() => this.caps()?.can_use_contract_builder ?? false);
  readonly canDoMastering       = computed(() => this.caps()?.can_do_mastering         ?? false);
  /** null = illimité, 0 = aucun accès. */
  readonly contractQuota        = computed(() => this.caps()?.contract_quota           ?? 0);
  readonly canUseManagementContract = computed(() => this.caps()?.can_use_management_contract ?? false);
  readonly canViewRoyalties         = computed(() => this.caps()?.can_view_royalties          ?? false);

  // Préférence locale pour les utilisateurs non connectés (pas persistée)
  private _localTagCategoryPref = signal<string | null>(null);

  readonly preferredTagCategory = computed(
    () => this._currentUser()?.preferred_tag_category ?? this._localTagCategoryPref()
  );

  // Mode d'affichage des infos dans les track cards (tags ou artistes similaires)
  private _cardInfoMode = signal<'tags' | 'artists'>(
    (localStorage.getItem('card_info_mode') as 'tags' | 'artists' | null) ?? 'artists'
  );
  readonly preferredCardInfoMode = this._cardInfoMode.asReadonly();

  setCardInfoMode(mode: 'tags' | 'artists'): void {
    this._cardInfoMode.set(mode);
    localStorage.setItem('card_info_mode', mode);
  }



  //// ======================================================
  //// ALREADY A USER BLOCK (/login, /me... )
  //// ======================================================

  login(identifier : string,
    password : string,
    remember : boolean,
    captchaToken : string | null = null ): Observable<LoginResponse>{
    return this.http.post<LoginResponse>(`${this.authUrl}/login`, {
      identifier,
      password,
      remember,
      captcha_token: captchaToken,
    }).pipe(
      tap((res) => {
        if (res.success === true) {
          this.storeAuth(res, remember);
        }

      }),
      switchMap(res => this.storage.native && res.success
        ? from(this.storage.flush()).pipe(map(() => res)) : of(res)),
      catchError((err)=> {
        if (err.error) {
          this.failedAuth(err.error)
        }
        return throwError(() => err)
      })
    );
  }



    private storeAuth(res: LoginSuccess, remember = true){
      // Session courte : mémoire native ou sessionStorage web.
      // Session persistante : coffre natif ou localStorage web.
      // Remove stale credentials from the other storage before switching sessions.
      for (const target of [this.storage.persistent, this.storage.session]) {
        for (const key of ['access_token', 'refresh_token', 'user']) target.removeItem(key);
      }
      const storage = remember ? this.storage.persistent : this.storage.session;

      storage.setItem('access_token', res.data.tokens.access_token);

      if (res.data.tokens.refresh_token) {
        storage.setItem('refresh_token', res.data.tokens.refresh_token);
      }

      storage.setItem('user', JSON.stringify(res.data.user));
      this._currentUser.set(res.data.user);

      // Si l'utilisateur avait sélectionné une catégorie en anonyme et que le serveur
      // n'en a pas, on migre la préférence locale vers le serveur.
      const localPref = this._localTagCategoryPref();
      if (localPref && !res.data.user.preferred_tag_category) {
        this.updateTagCategoryPreference(localPref);
      }
      this._localTagCategoryPref.set(null);
      this._scheduleProactiveRefresh(res.data.tokens.access_token);
    }

    private failedAuth(_res: LoginError){ /* noop — error handled by component */ }



  logout(): Observable<any> {
    return this.http.post(`${this.authUrl}/logout`, {}).pipe(
      catchError(() => of(null)),
      switchMap(result => {
        this._clearAuth();
        return this.storage.native ? from(this.storage.flush()).pipe(map(() => result)) : of(result);
      }),
    );
  }

  /** Vide la session localement sans appel API ni toast (ex: token expiré auto-détecté). */
  silentLogout(): void {
    this._clearAuth();
  }

  private _clearAuth(): void {
    // Annuler le timer proactif avant de déconnecter
    if (this._refreshTimer) { clearTimeout(this._refreshTimer); this._refreshTimer = undefined; }
    // Ne pas effacer tout le localStorage — les préférences UI (onboarding_done,
    // card_info_mode, display_mode…) doivent persister entre les sessions.
    this.storage.persistent.removeItem('access_token');
    this.storage.persistent.removeItem('refresh_token');
    this.storage.persistent.removeItem('user');
    // Session courte (remember=false) → tokens dans sessionStorage
    this.storage.session.removeItem('access_token');
    this.storage.session.removeItem('refresh_token');
    this.storage.session.removeItem('user');
    this._currentUser.set(null);
    this.router.navigate(['/login']);
  }

  updateTagCategoryPreference(category: string | null): void {
    const user = this._currentUser();
    if (!user) {
      this._localTagCategoryPref.set(category);
      return;
    }
    const persist = (u: User) => {
      if (this.storage.persistent.getItem('user')) {
        this.storage.persistent.setItem('user', JSON.stringify(u));
      } else {
        this.storage.session.setItem('user', JSON.stringify(u));
      }
    };

    // Optimistic update — l'UI répond immédiatement, sans attendre l'API
    const optimistic = { ...user, preferred_tag_category: category };
    this._currentUser.set(optimistic);
    persist(optimistic);

    this.http.patch<{ success: boolean; data: { preferred_tag_category: string | null } }>(
      '/api/main/users/preferences',
      { preferred_tag_category: category }
    ).subscribe({
      next: (res) => {
        // Confirme avec la valeur serveur (au cas où le serveur a validé différemment)
        const confirmed = { ...this._currentUser()!, preferred_tag_category: res.data.preferred_tag_category };
        this._currentUser.set(confirmed);
        persist(confirmed);
      },
      error: () => {
        // Révoque la mise à jour optimiste si l'API échoue
        this._currentUser.set(user);
        persist(user);
      },
    });
  }

  /** Met à jour le signal et le stockage actif avec un objet User partiel ou complet. */
  updateCurrentUser(partial: Partial<User>): void {
    const merged = { ...this._currentUser()!, ...partial } as User;
    if (this.storage.persistent.getItem('user')) {
      this.storage.persistent.setItem('user', JSON.stringify(merged));
    } else {
      this.storage.session.setItem('user', JSON.stringify(merged));
    }
    this._currentUser.set(merged);
  }

  getToken(): string | null {
    // localStorage d'abord (session persistante), puis sessionStorage (session courte)
    return this.storage.persistent.getItem('access_token') ?? this.storage.session.getItem('access_token');
  }

  getUser() {
    const user = this.storage.persistent.getItem('user') ?? this.storage.session.getItem('user');
    try { return user ? JSON.parse(user) : null; } catch { return null; }
  }

  /**
   * Rafraîchit le token d'accès si son expiration est dans moins de `windowMs` ms.
   * À appeler avant une opération longue (ex: upload) pour éviter une expiration en cours de route.
   */
  refreshIfExpiringSoon(windowMs = 5 * 60 * 1000): Observable<void> {
    const token = this.getToken();
    if (!token) return of(undefined);
    try {
      const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
      const expiresInMs = payload.exp * 1000 - Date.now();
      if (expiresInMs < windowMs) {
        return this.refreshToken().pipe(map(() => undefined));
      }
    } catch { /* token mal formé — laisser l'intercepteur gérer le 401 */ }
    return of(undefined);
  }

  me(): Observable<MeResponse> {
    return this.http.get<MeResponse>(`${this.authUrl}/me`).pipe(
      tap((res) => {
        if (res.success) {
          this._currentUser.set(res.data.user);
          // Persister dans le même stockage que la session en cours
          if (this.storage.persistent.getItem('user')) {
            this.storage.persistent.setItem('user', JSON.stringify(res.data.user));
          } else {
            this.storage.session.setItem('user', JSON.stringify(res.data.user));
          }
        }
      }),
      catchError((err) => {
        // 404 = user introuvable en DB (session stale) → logout silencieux
        if (err.status === 404) {
          this._clearAuth();
        }
        return throwError(() => err);
      })
    );
  }

  // ── USED IN JWT INTERCEPTOR ──────────────────────────────────────────────────

  getAuthUrl(): string { return this.authUrl; }

  // ── Connexion Google ──────────────────────────────────────────────────────

  readonly googleLoginUrl = `${this.authUrl}/google/login`;

  /**
   * Démarre le flow Google. Sur Android natif, ouvre un Chrome Custom Tab
   * (@capacitor/browser) au lieu de naviguer dans la WebView de l'app : Google
   * bloque l'authentification dans un user-agent WebView embarqué (erreur
   * disallowed_useragent). Le retour dans l'app se fait via le schéma custom
   * net.laprod.app:// (cf. routes/auth_api.py, NativeShellService.init()).
   *
   * Sur iOS natif : ASWebAuthenticationSession (plugin local WebAuthSession),
   * qui rend directement l'URL net.laprod.app://oauth-callback?… — sans ça, le
   * lien ouvrait Safari et la connexion se terminait sur le site web.
   *
   * Sur web, ne fait rien : l'appelant garde un <a [href]="googleLoginUrl">
   * classique, qui navigue normalement.
   *
   * import() dynamique pour ne jamais charger @capacitor/browser dans le
   * bundle web initial (même discipline que push.service.ts).
   */
  async startGoogleLogin(event: Event): Promise<void> {
    await this._startNativeOauth(event, this.googleLoginUrl);
  }

  private async _startNativeOauth(event: Event, loginUrl: string): Promise<void> {
    const platform = Capacitor.getPlatform();
    if (platform === 'web') return;

    event.preventDefault();
    const url = `${loginUrl}?platform=mobile`;

    if (platform === 'android') {
      const { Browser } = await import('@capacitor/browser');
      await Browser.open({ url });
      return;
    }

    const { WebAuthSession } = await import('./web-auth-session-plugin');
    try {
      const res = await WebAuthSession.start({ url, callbackScheme: 'net.laprod.app' });
      this.nativeShell.handleOauthCallbackUrl(res.url);
    } catch (err: any) {
      if (err?.code === 'CANCELED') return;  // feuille fermée par l'utilisateur
      this.router.navigate(['/oauth-callback'], { queryParams: { error: 'oauth_failed' } });
    }
  }

  // ── Connexion Apple ──────────────────────────────────────────────────────
  //
  // Deux chemins bien distincts (cf. routes/auth_api.py) :
  // - iOS natif : AuthenticationServices (via appleNativeSignIn ci-dessous),
  //   aucune redirection, réponse directe.
  // - Android + web : même flow que Google (Custom Tab sur Android, navigation
  //   normale sur web), le bouton garde un <a [href]="appleLoginUrl">.

  readonly appleLoginUrl = `${this.authUrl}/apple/login`;

  /** Sur Android natif : Chrome Custom Tabs, comme startGoogleLogin. Sur web,
   *  ne fait rien. iOS utilise normalement le flow natif (appleNativeSignIn) ;
   *  s'il passait quand même ici, même feuille système que Google. */
  async startAppleWebLogin(event: Event): Promise<void> {
    await this._startNativeOauth(event, this.appleLoginUrl);
  }

  /**
   * Sign in with Apple natif iOS (AuthenticationServices via
   * @capawesome/capacitor-apple-sign-in). import() dynamique pour ne jamais
   * charger ce plugin dans le bundle web/Android (même discipline que
   * @capacitor/browser — cf. startGoogleLogin).
   *
   * Ne stocke PAS l'auth elle-même : l'appelant décide (storeOauthAuth +
   * navigateAfterOauth), comme pour le retour du flow web via OauthCallbackComponent.
   */
  appleNativeSignIn(): Observable<AppleNativeResult> {
    return from(this._performAppleNativeSignIn());
  }

  private async _performAppleNativeSignIn(): Promise<AppleNativeResult> {
    const { AppleSignIn, SignInScope } = await import('@capawesome/capacitor-apple-sign-in');
    const result = await AppleSignIn.signIn({
      scopes: [SignInScope.Email, SignInScope.FullName],
    });

    const { firstValueFrom } = await import('rxjs');
    return firstValueFrom(this.http.post<AppleNativeResult>(`${this.authUrl}/apple/native`, {
      identity_token:      result.idToken,
      authorization_code:  result.authorizationCode,
      given_name:          result.givenName ?? '',
    }));
  }

  /**
   * Destination post-connexion OAuth commune aux deux entrées (redirection web
   * via OauthCallbackComponent, et réponse directe du flow natif Apple) — logique
   * déplacée ici depuis OauthCallbackComponent pour être partagée sans dupliquer
   * le switch sur `next`.
   */
  navigateAfterOauth(next: string, suggestedName: string = ''): void {
    // Filet de sécurité : le backend peut renvoyer '/' même si le profil est
    // incomplet (ex. compte dont l'email n'était pas vérifié à la création).
    if (next === '/') {
      const user = this._currentUser();
      if (user && !user.user_type_selected) {
        this.router.navigate(['/select-role']);
        return;
      }
    }

    switch (next) {
      case 'complete-profile':
        this.router.navigate(['/complete-profile'], {
          queryParams: suggestedName ? { name: suggestedName } : {},
        });
        break;
      case 'select-role':
        this.router.navigate(['/select-role']);
        break;
      default:
        this.router.navigate(['/']);
    }
  }

  /**
   * Rafraîchit l'access_token en utilisant le refresh_token stocké.
   *
   * Protection multi-refresh : si un refresh est déjà en cours, renvoie le
   * même Observable partagé (shareReplay) — une seule requête HTTP, tous les
   * appelants simultanés reçoivent le même nouveau token.
   */
  private _refreshing$: Observable<string> | null = null;

  refreshToken(): Observable<string> {
    if (this._refreshing$) return this._refreshing$;

    const rt = this.storage.persistent.getItem('refresh_token') ?? this.storage.session.getItem('refresh_token');
    if (!rt) {
      this.silentLogout();
      return throwError(() => new Error('no_refresh_token'));
    }

    const sessionToken = this.getToken();
    this._refreshing$ = this.http.post<{ data: { access_token: string; refresh_token?: string } }>(
      `${this.authUrl}/refresh`, {},
      { headers: { Authorization: `Bearer ${rt}` } },
    ).pipe(
      switchMap(res => {
        // A logout or a new login while the request was in flight must win.
        if (this.getToken() !== sessionToken) return throwError(() => new Error('session_changed'));
        const storage = this.storage.persistent.getItem('refresh_token') ? this.storage.persistent : this.storage.session;
        storage.setItem('access_token', res.data.access_token);
        if (res.data.refresh_token) storage.setItem('refresh_token', res.data.refresh_token);
        return this.storage.native
          ? from(this.storage.flush()).pipe(map(() => res.data.access_token))
          : of(res.data.access_token);
      }),
      tap(token => this._scheduleProactiveRefresh(token)),
      catchError(error => {
        // Definitive rejection only; offline/5xx/rate limiting preserve the session.
        if (this.getToken() === sessionToken && error instanceof HttpErrorResponse &&
            [401, 422].includes(error.status)) this.silentLogout();
        return throwError(() => error);
      }),
      finalize(() => { this._refreshing$ = null; }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );

    return this._refreshing$;
  }


  //// ======================================================
  //// NEW USER BLOCK (register)
  //// ======================================================
  
  // ── Google OAuth ─────────────────────────────────────────────────────────

  /** Échange un code OAuth court-durée contre les tokens JWT. */
  tokenExchange(code: string): Observable<{ success: boolean; data?: OauthExchangeData; feedback?: { message: string } }> {
    return this.http.get<any>(`${this.authUrl}/token-exchange`, { params: { code } });
  }

  /** Finalise le profil d'un nouveau compte Google (username + signature + CGU). */
  completeOauthProfile(
    username: string,
    signature: string,
    accept_terms: boolean,
  ): Observable<{ success: boolean; data?: CompleteOauthProfileData; feedback?: { message: string } }> {
    return this.http.post<any>(
      `${this.authUrl}/complete-oauth-profile`,
      { username, signature, accept_terms },
    );
  }

  /** Sélectionne les rôles de l'utilisateur. */
  selectRole(roles: { is_artist: boolean; is_beatmaker: boolean; is_mix_engineer: boolean; is_producer: boolean }):
      Observable<{ success: boolean; data?: { user: User; next: string }; feedback?: { message: string } }> {
    return this.http.post<any>(
      `${this.authUrl}/select-role`,
      roles,
    );
  }

  /** Stocke les tokens et l'utilisateur après échange OAuth (toujours persistent). */
  storeOauthAuth(data: OauthExchangeData | CompleteOauthProfileData): Promise<void> | void {
    for (const key of ['access_token', 'refresh_token', 'user']) this.storage.session.removeItem(key);
    this.storage.persistent.setItem('access_token',  data.tokens.access_token);
    this.storage.persistent.setItem('refresh_token', data.tokens.refresh_token);
    this.storage.persistent.setItem('user', JSON.stringify(data.user));
    this._currentUser.set(data.user);
    this._scheduleProactiveRefresh(data.tokens.access_token);
    if (this.storage.native) return this.storage.flush();
  }

  // ── Inscription ───────────────────────────────────────────────────────────

  register(
    username: string,
    password: string,
    password_confirm: string,
    email: string,
    signature: string,
    accept_terms: boolean,
    captchaToken: string | null = null,
  ): Observable<RegisterResponse> {
    return this.http.post<RegisterResponse>(`${this.authUrl}/register`, {
      username,
      password,
      password_confirm,
      email,
      signature,
      accept_terms,
      captcha_token: captchaToken,
    }).pipe(
      catchError((err) => throwError(() => err))
    );
  }

  verifyEmail(token: string): Observable<any> {
    return this.http.post(`${this.authUrl}/verify-email`, { token });
  }

  resendVerification(identifier: string): Observable<any> {
    return this.http.post(`${this.authUrl}/resend-verification`, { identifier });
  }

  forgotPassword(email: string): Observable<any> {
    return this.http.post(`${this.authUrl}/forgot-password`, { email });
  }

  resetPassword(token: string, password: string, passwordConfirm: string): Observable<any> {
    return this.http.post(`${this.authUrl}/reset-password`, { token, password, password_confirm: passwordConfirm });
  }

}
