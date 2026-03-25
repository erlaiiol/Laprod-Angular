import { computed, Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { catchError, Observable, tap, throwError } from 'rxjs';
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
      is_admin: boolean,
      is_beatmaker: boolean,
      is_mix_engineer : boolean,
      is_artist: boolean,
    },
    user_type_selected: boolean,
    email_verified: boolean,
    notif_count : number
}


export interface MeResponse {
  success : boolean,
  user : User
}


export interface RegisterSuccess{
  success: true,
  feedback: { level: string; message:string;};
  code?: string;
  data: {
    newUser : NewUser
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





@Injectable({
  providedIn: 'root',
})

export class AuthService {  

  private authUrl = `${environment.apiUrl}/auth`

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
          this.storeAuth(res);
          if (res.code === 'SHOW_SELECT_ROLE') {
            this.router.navigate(['/select_role']);
          }
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



    private storeAuth(res: LoginSuccess){

      localStorage.setItem('access_token', res.data.tokens.access_token);

      if (res.data.tokens.refresh_token) {
        localStorage.setItem('refresh_token', res.data.tokens.refresh_token);
      }

      localStorage.setItem('user', JSON.stringify(res.data.user));
      this._currentUser.set(res.data.user);
    }

    private failedAuth(res: LoginError){
      console.log('level :', res.feedback.level, ', message : ', res.feedback.message)
    }



  logout() : Observable<any> {
    return this.http.post(`${this.authUrl}/logout`, {}, {
      headers: { Authorization: `Bearer ${this.getToken()}`}
    }).pipe(tap(() => {
      localStorage.clear();
      this._currentUser.set(null);
      this.router.navigate(['/login'])
    }));
  }

  getToken(): string | null {
    return localStorage.getItem('access_token');
  }

  getUser() {
    const user = localStorage.getItem('user');
    return user ? JSON.parse(user) : null;
  }

  me(): Observable<MeResponse> {
    return this.http.get<MeResponse>(`${this.authUrl}/me`, {
      headers: { Authorization: `Bearer ${this.getToken()}` }
    }).pipe(
      tap((res) => {
        if (res.success) {
          this._currentUser.set(res.user);
        }
      })
    );
  }


  //// ======================================================
  //// NEW USER BLOCK (register)
  //// ======================================================
  
  register(identifier: string, 
    password: string, 
    password_confirm: string, 
    email: string, 
    signature: string) : Observable<RegisterResponse> {
    return this.http.post<RegisterResponse>(`${this.authUrl}/register`, {
      identifier, 
      password, 
      password_confirm, 
      email, 
      signature
    }).pipe(
      tap((res) => {
        if (res.success === true){
          ///////
          this.router.navigate(['/login']);
        }
      }),
      catchError((err) => {
        if (err.error) {
          ////////
        }
        return throwError(() => err)
      })
    )
  }

}
