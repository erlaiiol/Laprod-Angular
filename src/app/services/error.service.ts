import { Injectable, signal } from '@angular/core';

export type ErrorCode = 0 | 403 | 404 | 500 | 503;

export interface AppError {
  code:    ErrorCode;
  /** Contexte optionnel transmis à la page d'erreur (ex: 'admin') */
  context?: string;
}

/**
 * Service léger pour transmettre un contexte d'erreur avant une navigation
 * programmatique vers /erreur.
 *
 * Usage :
 *   errorSvc.set({ code: 403 });
 *   router.navigate(['/erreur']);
 */
@Injectable({ providedIn: 'root' })
export class ErrorService {
  readonly current = signal<AppError | null>(null);

  set(err: AppError): void  { this.current.set(err); }
  clear(): void             { this.current.set(null); }
}
