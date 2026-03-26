import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap, catchError, throwError } from 'rxjs';
import { Toast, ToastService } from '../services/toast.service';

export const toastInterceptor: HttpInterceptorFn = (req, next) => {
  const toastService = inject(ToastService);

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

    // Réponses 4xx/5xx : on lit err.error.feedback
    catchError((err) => {
      if (err.error?.feedback) {
        toastService.showToast(err.error.feedback);
      }
      return throwError(() => err);
    })

  );
};
