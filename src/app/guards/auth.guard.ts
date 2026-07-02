import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  if (!auth.isLoggedIn()) {
    router.navigate(['/login']);
    return false;
  }

  const redirectIfIncomplete = () => {
    const user = auth.currentUser();
    if (user && !user.user_type_selected) {
      router.navigate(['/complete-profile']);
      return false;
    }
    return true;
  };

  // Si le token est expiré, tenter un refresh silencieux avant d'autoriser la navigation.
  // Cela évite d'afficher brièvement une page protégée puis de la quitter sur 401.
  if (auth.isTokenExpired()) {
    return auth.refreshToken().pipe(
      map(() => redirectIfIncomplete()),
      catchError(() => {
        auth.silentLogout();
        return of(false);
      }),
    );
  }

  return redirectIfIncomplete();
};
