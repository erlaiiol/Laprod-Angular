import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { ErrorService } from '../services/error.service';

export const adminGuard: CanActivateFn = () => {
  const auth     = inject(AuthService);
  const router   = inject(Router);
  const errorSvc = inject(ErrorService);

  if (!auth.isLoggedIn()) {
    router.navigate(['/login']);
    return false;
  }

  if (auth.currentUser()?.roles?.is_admin) return true;

  errorSvc.set({ code: 403 });
  router.navigate(['/erreur']);
  return false;
};
