import { Injectable, signal } from '@angular/core';
import { Subject } from 'rxjs';


export interface Toast {
  level : 'info' | 'warning' | 'error';
  message : string;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  private _toast = signal<Toast[]>([]);
  _toasts = this._toast.asReadonly(); // signal readonly accessible au composant

  showToast(toast: Toast) {
    console.log('toast émis:', toast);
    this._toast.set([...this._toast(), toast]);

    setTimeout(() => {
      this._toast.set(this._toast().filter(t => t !== toast));
    }, 3000);
  }
}
