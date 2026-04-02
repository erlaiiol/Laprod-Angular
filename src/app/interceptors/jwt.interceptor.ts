import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {

  const authService = inject(AuthService);
  const authUrl     = authService.getAuthUrl();
  const token       = authService.getToken();

  if (token) {
    req = req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
  }

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      // Laisser passer toutes les erreurs non-401
      if (error.status !== 401) return throwError(() => error);

      // Si c'est le refresh lui-même qui 401 → logout silencieux (refresh token expiré/révoqué)
      if (req.url.includes(`${authUrl}/refresh`)) {
        authService.silentLogout();
        return throwError(() => error);
      }

      // Tenter un refresh (shareReplay garantit une seule requête même en cas de 401 simultanés)
      return authService.refreshToken().pipe(
        switchMap(newToken =>
          next(req.clone({ setHeaders: { Authorization: `Bearer ${newToken}` } })),
        ),
        catchError(err => {
          // Refresh échoué (token expiré, révoqué, réseau…) → logout silencieux
          authService.silentLogout();
          return throwError(() => err);
        }),
      );
    }),
  );
};
