import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { environment } from '../../environments/environment';

export const testimonialsGuard: CanActivateFn = () => {
  if (!environment.testimonialsEnabled) {
    inject(Router).navigate(['/']);
    return false;
  }
  return true;
};
