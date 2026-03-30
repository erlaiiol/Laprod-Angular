import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';



export const jwtInterceptor: HttpInterceptorFn = (req, next) => {

  
  const http = inject(HttpClient);
  const authService = inject(AuthService);
  const authUrl = authService.getAuthUrl();

  const access_token = authService.getToken();
  const refresh_token = localStorage.getItem('refresh_token');

  //===================================
  //DEBUG LINE 
  // console.log('jwtInterceptor online')
  //===================================
    
  if (access_token) {
    //===================================
    //DEBUG LINE 
    // console.log('interceptor checks token, token = ', token)
    //===================================
    

    req = req.clone({
      setHeaders: {
        Authorization: `Bearer ${access_token}`
      }
    });
  }

  return next(req).pipe(
    
    catchError((error:HttpErrorResponse) => {
      if (error.status !== 401) {
        return throwError(() => error);
      }

      if (!refresh_token){
        authService.logout().subscribe();
        return throwError(() => error);
      }

      if (req.url.includes(`${authUrl}/refresh`)) {
        authService.logout().subscribe();
        return throwError(() => error);
      }

      return http.post<any>(`${authUrl}/refresh`, {}, {
        headers: {
          Authorization: `Bearer ${refresh_token}`
        }
      }).pipe(

        switchMap((response) => {

          const newAccessToken = response.data.access_token;

          // 💾 sauvegarde
          localStorage.setItem('access_token', newAccessToken);

          // 🔁 rejouer requête originale
          const newReq = req.clone({
            setHeaders: {
              Authorization: `Bearer ${newAccessToken}`
            }
          });

          return next(newReq);
        }),

        catchError(err => {
          // ❌ refresh failed → logout
          authService.logout().subscribe();
          return throwError(() => err);
        })
      );
    })
  );
};