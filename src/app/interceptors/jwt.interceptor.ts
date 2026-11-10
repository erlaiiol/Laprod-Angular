import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, of, switchMap, throwError } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { environment } from '../../environments/environment';

export const jwtInterceptor: HttpInterceptorFn = (req, next) => {
  const apiBase = environment.apiUrl.replace(/\/$/, '');
  // Never send app credentials to an external service or signed upload URL.
  if (!(req.url.startsWith('/api/') || (apiBase && req.url.startsWith(`${apiBase}/api/`)))) {
    return next(req);
  }

  const auth = inject(AuthService);
  const authUrl = auth.getAuthUrl();
  const isRefresh = req.url.split('?')[0] === `${authUrl}/refresh`;
  const isLogin = req.url.split('?')[0] === `${authUrl}/login`;
  const token = auth.getToken();
  const headers: Record<string, string> = {
    'X-Client-Platform': environment.isNative ? 'native' : 'web',
  };
  // /refresh explicitly carries the refresh token supplied by AuthService.
  if (token && !isRefresh) headers['Authorization'] = `Bearer ${token}`;
  req = req.clone({ setHeaders: headers });

  return next(req).pipe(
    catchError((error: HttpErrorResponse) => {
      // Refresh rejection is handled centrally in AuthService, including proactive calls.
      if (error.status !== 401 || !token || isLogin || isRefresh) {
        return throwError(() => error);
      }
      // A late 401 may belong to a request sent before another refresh completed.
      const currentToken = auth.getToken();
      if (!currentToken) return throwError(() => error);
      return (currentToken !== token ? of(currentToken) : auth.refreshToken()).pipe(
        switchMap(newToken => next(req.clone({
          setHeaders: { Authorization: `Bearer ${newToken}` },
        })).pipe(
          catchError(retryError => {
            if (retryError.status === 401 && auth.getToken() === newToken) auth.silentLogout();
            return throwError(() => retryError);
          }),
        )),
      );
    }),
  );
};
