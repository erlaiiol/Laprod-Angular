// feedback.interceptor.ts
import { inject, Injectable } from '@angular/core';
import { HttpEvent, HttpHandler, HttpHandlerFn, HttpInterceptor, HttpInterceptorFn, HttpRequest, HttpResponse } from '@angular/common/http';
import { tap } from 'rxjs/operators';
import { ToastService } from '../services/toast.service';

export const feedbackInterceptor: HttpInterceptorFn = (req: HttpRequest<any>, next: HttpHandlerFn) => {
    console.log('intercepted.')
  const toastService = inject(ToastService); // on injecte le service ici

  return next(req).pipe(
    tap((event: HttpEvent<any>) => {
      if (event instanceof HttpResponse) {
        const feedback = event.body?.feedback;
        if (feedback) {
            console.log('calling showToast()')
          toastService.showToast(feedback);
        }
      }
    })
  );
};

