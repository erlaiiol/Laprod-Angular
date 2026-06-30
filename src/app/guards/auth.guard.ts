import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth   = inject(AuthService);
  const router = inject(Router);

  if (!auth.isLoggedIn()) {
    router.navigate(['/login']);
    return false;
  }

  // Utilisateur connecté mais profil non finalisé (OAuth sans username/rôle sélectionné)
  const user = auth.currentUser();
  if (user && !user.user_type_selected) {
    router.navigate(['/complete-profile']);
    return false;
  }

  return true;
};
