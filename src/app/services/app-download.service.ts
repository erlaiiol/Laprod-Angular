import { Injectable, signal } from '@angular/core';
import { Capacitor } from '@capacitor/core';

export type StorePlatform = 'ios' | 'android';
export const APP_STORES = [
  { platform: 'ios' as const, name: 'App Store', hint: 'Télécharger dans l’', url: 'https://apps.apple.com/fr/app/laprod-musique-beats/id6812515891' },
  { platform: 'android' as const, name: 'Google Play', hint: 'Disponible sur', url: 'https://play.google.com/store/apps/details?id=net.laprod.app&hl=fr' },
];
const DISMISSED_KEY = 'laprod_app_banner_dismissed';

export function detectStorePlatform(userAgent: string, platform: string, maxTouchPoints: number): StorePlatform | null {
  if (/android/i.test(userAgent)) return 'android';
  // iPadOS can advertise a desktop Safari user agent.
  if (/iPad|iPhone|iPod/i.test(userAgent) || (platform === 'MacIntel' && maxTouchPoints > 1)) return 'ios';
  return null;
}

@Injectable({ providedIn: 'root' })
export class AppDownloadService {
  readonly isNative = Capacitor.isNativePlatform();
  readonly platform = detectStorePlatform(navigator.userAgent, navigator.platform, navigator.maxTouchPoints);
  readonly stores = APP_STORES;
  readonly suggestedStores = this.platform ? APP_STORES.filter(store => store.platform === this.platform) : APP_STORES;
  readonly dismissed = signal(this.wasDismissed());

  dismiss(): void {
    this.dismissed.set(true);
    // Dismiss for this browsing session, including navigation and reloads.
    try { sessionStorage.setItem(DISMISSED_KEY, '1'); } catch { /* Storage may be disabled. */ }
  }

  private wasDismissed(): boolean {
    try { return sessionStorage.getItem(DISMISSED_KEY) === '1'; } catch { return false; }
  }
}
