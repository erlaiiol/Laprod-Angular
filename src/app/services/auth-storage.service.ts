import { inject, Injectable, InjectionToken } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { SecureStorage } from '@aparajita/capacitor-secure-storage';

const AUTH_KEYS = ['access_token', 'refresh_token', 'user'] as const;
const SESSION_KEY = 'net.laprod.auth.v1';
type AuthStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export const AUTH_NATIVE_PLATFORM = new InjectionToken<boolean>('AUTH_NATIVE_PLATFORM', {
  providedIn: 'root', factory: () => Capacitor.isNativePlatform(),
});
export const AUTH_SECURE_STORAGE = new InjectionToken<Pick<typeof SecureStorage, 'get' | 'set' | 'remove'>>('AUTH_SECURE_STORAGE', {
  providedIn: 'root', factory: () => ({
    get: (...args: Parameters<typeof SecureStorage.get>) => SecureStorage.get(...args),
    set: (...args: Parameters<typeof SecureStorage.set>) => SecureStorage.set(...args),
    remove: (...args: Parameters<typeof SecureStorage.remove>) => SecureStorage.remove(...args),
  }),
});

/** Native credentials live in Keychain/Keystore; only an in-memory copy is read synchronously. */
@Injectable({ providedIn: 'root' })
export class AuthStorageService {
  readonly native = inject(AUTH_NATIVE_PLATFORM);
  private secure = inject(AUTH_SECURE_STORAGE);
  private values: Record<string, string> = {};
  private temporary = new Map<string, string>();
  private pending: Promise<void> = Promise.resolve();

  readonly persistent: AuthStorage = this.native ? {
    getItem: key => this.values[key] ?? null,
    setItem: (key, value) => { this.values[key] = value; this.enqueueSave(); },
    removeItem: key => { delete this.values[key]; this.enqueueSave(); },
  } : localStorage;

  readonly session: AuthStorage = this.native ? {
    getItem: key => this.temporary.get(key) ?? null,
    setItem: (key, value) => { this.temporary.set(key, value); },
    removeItem: key => { this.temporary.delete(key); },
  } : sessionStorage;

  async initialize(): Promise<void> {
    if (!this.native) return;
    const saved = await this.secure.get(SESSION_KEY, false, false);
    if (saved !== null) {
      if (typeof saved !== 'object' || Array.isArray(saved) ||
          !AUTH_KEYS.every(key => typeof (saved as Record<string, unknown>)[key] === 'string')) {
        await this.secure.remove(SESSION_KEY, false);
      } else {
        this.values = saved as Record<string, string>;
      }
    } else {
      // Keep the legacy session until its secure copy has actually been saved.
      for (const key of AUTH_KEYS) {
        const value = localStorage.getItem(key);
        if (value !== null) this.values[key] = value;
        const temporary = sessionStorage.getItem(key);
        if (temporary !== null) this.temporary.set(key, temporary);
      }
      if (Object.keys(this.values).length) {
        await this.secure.set(SESSION_KEY, { ...this.values }, false, false);
      }
    }
    for (const key of AUTH_KEYS) {
      localStorage.removeItem(key);
      sessionStorage.removeItem(key);
    }
  }

  /** Serialized writes prevent a slow old write from restoring a logged-out session. */
  private enqueueSave(): void {
    this.pending = this.pending.catch(() => {}).then(async () => {
      const snapshot = { ...this.values };
      if (Object.keys(snapshot).length) await this.secure.set(SESSION_KEY, snapshot, false, false);
      else await this.secure.remove(SESSION_KEY, false);
    });
    // Callers of flush still receive the error. Never fall back to WebView storage.
    void this.pending.catch(error => console.error('Native auth storage unavailable', error));
  }

  flush(): Promise<void> { return this.pending; }
}
