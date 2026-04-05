import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { tap, catchError, throwError } from 'rxjs';
import { Toast, ToastService } from '../services/toast.service';
import { ErrorService } from '../services/error.service';

export const toastInterceptor: HttpInterceptorFn = (req, next) => {
  const toastService = inject(ToastService);
  const errorService = inject(ErrorService);
  const router       = inject(Router);

  return next(req).pipe(

    // Réponses 2xx : on lit event.body.feedback
    tap((event) => {
      if (event instanceof HttpResponse) {
        const body = event.body as { feedback?: Toast };
        if (body?.feedback) {
          toastService.showToast(body.feedback);
        }
      }
    }),

    // Réponses 4xx/5xx et erreurs réseau
    catchError((err) => {

      // Affiche le feedback métier (toast) pour les erreurs applicatives
      if (err.error?.feedback) {
        toastService.showToast(err.error.feedback);
      }

      // ── Redirection page d'erreur pour les pannes critiques ──────────────────
      // On évite de rediriger si on est déjà sur /erreur ou sur une route d'auth.
      const currentUrl = router.url;
      const isErrorPage = currentUrl.startsWith('/erreur') || currentUrl.startsWith('/login');

      if (!isErrorPage) {
        if (err.status === 0) {
          // Réseau indisponible (CORS, serveur totalement arrêté, hors-ligne)
          errorService.set({ code: 0 });
          router.navigate(['/erreur']);
        } else if (err.status === 503) {
          // Service temporairement indisponible (maintenance…)
          errorService.set({ code: 503 });
          router.navigate(['/erreur']);
        } else if (err.status === 500 && !err.error?.feedback) {
          // Erreur serveur sans feedback métier → page d'erreur générique
          errorService.set({ code: 500 });
          router.navigate(['/erreur']);
        }
      }

      return throwError(() => err);
    })

  );
};
