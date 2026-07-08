import { Injectable, signal } from '@angular/core';

const LS_KEY = 'laprod_guide_opened';

@Injectable({ providedIn: 'root' })
export class UserflowService {
  readonly isOpen        = signal(false);
  readonly hasEverOpened = signal(localStorage.getItem(LS_KEY) === '1');

  open(): void {
    if (!this.hasEverOpened()) {
      this.hasEverOpened.set(true);
      localStorage.setItem(LS_KEY, '1');
    }
    this.isOpen.set(true);
    document.body.style.overflow = 'hidden';
  }

  close(): void {
    this.isOpen.set(false);
    document.body.style.overflow = '';
  }
}
