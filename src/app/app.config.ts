import { ApplicationConfig, isDevMode, provideBrowserGlobalErrorListeners, provideCheckNoChangesConfig, provideZonelessChangeDetection } from '@angular/core';
import { provideRouter, withInMemoryScrolling, withPreloading } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';

import { routes } from './app.routes';
import { IdlePreloadStrategy } from './routing/idle-preload.strategy';
import { toastInterceptor } from './interceptors/toast.interceptor';
import { jwtInterceptor } from './interceptors/jwt.interceptor';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZonelessChangeDetection(),
    provideBrowserGlobalErrorListeners(),
    // Filet de sécurité du rollout OnPush (dev uniquement, tree-shaké en prod) :
    // re-vérifie périodiquement les arbres OnPush et jette ExpressionChanged...
    // si un binding a changé sans notification signal — pointe directement
    // les champs qui auraient dû être des signals.
    ...(isDevMode() ? [provideCheckNoChangesConfig({ exhaustive: true, interval: 1000 })] : []),
    provideRouter(
      routes,
      withInMemoryScrolling({ scrollPositionRestoration: 'top' }),
      withPreloading(IdlePreloadStrategy),
    ),
    provideHttpClient(
      withInterceptors([toastInterceptor, jwtInterceptor])
    )
  ]
};
