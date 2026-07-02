import { computed, Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { catchError, finalize, map, Observable, of, shareReplay, tap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { Router } from '@angular/router';

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
      is_mixmaster_engineer:          boolean;
      is_certified_producer_arranger: boolean;
    },
    user_type_selected:  boolean,
    email_verified:      boolean,
    notif_count:         number,
    upload_track_tokens:     number,
    topline_tokens:          number,
    is_premium:              boolean,
    subscription_plan:       'free' | 'amateur' | 'pro',
    preferred_tag_category:  string | null,
    instagram?: string | null,
    twitter?:   string | null,
    youtube?:   string | null,
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





@Injectable({
  providedIn: 'root',
})

export class AuthService {  

  private authUrl = `${environment.apiUrl}/api/auth`

  constructor(private http:HttpClient, private router:Router) {}


  //// ======================================================
  //// VARIABLES BLOCK
  //// ======================================================

  private _currentUser = signal<User | null>(this.getUser());
  readonly currentUser = this._currentUser.asReadonly();

  readonly isLoggedIn = computed(() => this._currentUser() !== null);

  readonly isAdmin = computed(() => this._currentUser()?.roles?.is_admin || false);
  readonly isBeatmaker = computed(() => this._currentUser()?.roles?.is_beatmaker || false);
  readonly isMixEngineer = computed(() => this._currentUser()?.roles?.is_mix_engineer || false);
  readonly isArtist = computed(() => this._currentUser()?.roles?.is_artist || false);

  readonly isPremium = computed(() => {
    const u = this._currentUser();
    return !!u && u.is_premium && u.subscription_plan !== 'free';
  });
  readonly isPro = computed(() => {
    const u = this._currentUser();
    return !!u && u.is_premium && u.subscription_plan === 'pro';
  });
  readonly isAmateur = computed(() => {
    const u = this._currentUser();
    return !!u && u.is_premium && u.subscription_plan === 'amateur';
  });

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
    remember : boolean ): Observable<LoginResponse>{
    return this.http.post<LoginResponse>(`${this.authUrl}/login`, {
      identifier,
      password,
      remember
    }).pipe(
      tap((res) => {
        if (res.success === true) {
          this.storeAuth(res, remember);
        }

      }),
      catchError((err)=> {
        if (err.error) {
          this.failedAuth(err.error)
        }
        return throwError(() => err)
      })
    );
  }



    private storeAuth(res: LoginSuccess, remember = true){
      // remember=false → sessionStorage (effacé à la fermeture du navigateur)
      // remember=true  → localStorage (persistant entre les sessions)
      const storage = remember ? localStorage : sessionStorage;

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
    }

    private failedAuth(_res: LoginError){ /* noop — error handled by component */ }



  logout(): Observable<any> {
    return this.http.post(`${this.authUrl}/logout`, {}).pipe(
      tap(() => this._clearAuth()),
      catchError(() => { this._clearAuth(); return of(null); })
    );
  }

  /** Vide la session localement sans appel API ni toast (ex: token expiré auto-détecté). */
  silentLogout(): void {
    this._clearAuth();
  }

  private _clearAuth(): void {
    // Ne pas effacer tout le localStorage — les préférences UI (onboarding_done,
    // card_info_mode, display_mode…) doivent persister entre les sessions.
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    // Session courte (remember=false) → tokens dans sessionStorage
    sessionStorage.removeItem('access_token');
    sessionStorage.removeItem('refresh_token');
    sessionStorage.removeItem('user');
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
      if (localStorage.getItem('user')) {
        localStorage.setItem('user', JSON.stringify(u));
      } else {
        sessionStorage.setItem('user', JSON.stringify(u));
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
    if (localStorage.getItem('user')) {
      localStorage.setItem('user', JSON.stringify(merged));
    } else {
      sessionStorage.setItem('user', JSON.stringify(merged));
    }
    this._currentUser.set(merged);
  }

  getToken(): string | null {
    // localStorage d'abord (session persistante), puis sessionStorage (session courte)
    return localStorage.getItem('access_token') ?? sessionStorage.getItem('access_token');
  }

  getUser() {
    const user = localStorage.getItem('user') ?? sessionStorage.getItem('user');
    return user ? JSON.parse(user) : null;
  }

  /**
   * Rafraîchit le token d'accès si son expiration est dans moins de `windowMs` ms.
   * À appeler avant une opération longue (ex: upload) pour éviter une expiration en cours de route.
   */
  refreshIfExpiringSoon(windowMs = 5 * 60 * 1000): Observable<void> {
    const token = this.getToken();
    if (!token) return of(undefined);
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
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
          if (localStorage.getItem('user')) {
            localStorage.setItem('user', JSON.stringify(res.data.user));
          } else {
            sessionStorage.setItem('user', JSON.stringify(res.data.user));
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

    const rt = localStorage.getItem('refresh_token') ?? sessionStorage.getItem('refresh_token');
    if (!rt) return throwError(() => new Error('no_refresh_token'));

    this._refreshing$ = this.http.post<any>(
      `${this.authUrl}/refresh`, {},
      { headers: { Authorization: `Bearer ${rt}` } },
    ).pipe(
      map((res): string => res.data.access_token),
      tap(token => localStorage.setItem('access_token', token)),
      shareReplay(1),
      finalize(() => { this._refreshing$ = null; }),
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
  selectRole(roles: { is_artist: boolean; is_beatmaker: boolean; is_mix_engineer: boolean }):
      Observable<{ success: boolean; data?: { user: User; next: string }; feedback?: { message: string } }> {
    return this.http.post<any>(
      `${this.authUrl}/select-role`,
      roles,
    );
  }

  /** Stocke les tokens et l'utilisateur après échange OAuth (toujours persistent). */
  storeOauthAuth(data: OauthExchangeData | CompleteOauthProfileData): void {
    localStorage.setItem('access_token',  data.tokens.access_token);
    localStorage.setItem('refresh_token', data.tokens.refresh_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    this._currentUser.set(data.user);
  }

  // ── Inscription ───────────────────────────────────────────────────────────

  register(
    username: string,
    password: string,
    password_confirm: string,
    email: string,
    signature: string,
    accept_terms: boolean,
  ): Observable<RegisterResponse> {
    return this.http.post<RegisterResponse>(`${this.authUrl}/register`, {
      username,
      password,
      password_confirm,
      email,
      signature,
      accept_terms,
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

}
