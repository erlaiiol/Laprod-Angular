import { Injectable, signal } from '@angular/core';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'laprod-theme';

@Injectable({ providedIn: 'root' })
export class ThemeService {

  readonly theme = signal<Theme>('dark');

  constructor() {
    const saved = localStorage.getItem(STORAGE_KEY) as Theme | null;
    this._apply(saved ?? 'dark');
  }

  toggle(): void {
    this._apply(this.theme() === 'dark' ? 'light' : 'dark');
  }

  private _apply(t: Theme): void {
    this.theme.set(t);
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem(STORAGE_KEY, t);
  }
}
