import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { APP_STORES, AppDownloadService, detectStorePlatform, StorePlatform } from '../../services/app-download.service';
import { AppDownloadBannerComponent } from './app-download-banner.component';

describe('store platform detection', () => {
  for (const [agent, platform, touch, expected] of [
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', 'iPhone', 5, 'ios'],
    ['Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)', 'iPad', 5, 'ios'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Version/18.0 Safari/605.1', 'MacIntel', 5, 'ios'],
    ['Mozilla/5.0 (Linux; Android 15; Pixel 9)', 'Linux armv8l', 5, 'android'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15)', 'MacIntel', 0, null],
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'Win32', 10, null],
    ['unknown', '', 0, null],
  ] as const) {
    it(`routes ${platform || 'unknown platform'} with ${touch} touch points to ${expected ?? 'both stores'}`, () => {
      expect(detectStorePlatform(agent, platform, touch)).toBe(expected);
    });
  }
});

describe('app download banner', () => {
  function render(platform: StorePlatform | null, native = false) {
    const dismissed = signal(false);
    TestBed.configureTestingModule({ providers: [{ provide: AppDownloadService, useValue: {
      platform, isNative: native, stores: APP_STORES,
      suggestedStores: platform ? APP_STORES.filter(store => store.platform === platform) : APP_STORES,
      dismissed, dismiss: () => dismissed.set(true),
    } }] });
    const fixture = TestBed.createComponent(AppDownloadBannerComponent);
    fixture.detectChanges();
    return fixture;
  }

  for (const platform of ['ios', 'android'] as const) {
    it(`offers only the matching store on ${platform}`, () => {
      const fixture = render(platform);
      const links = fixture.nativeElement.querySelectorAll('a');
      expect(links.length).toBe(1);
      expect(links[0].href).toBe(APP_STORES.find(store => store.platform === platform)!.url);
    });
  }

  it('offers both stores on desktop', () => {
    expect(render(null).nativeElement.querySelectorAll('a').length).toBe(2);
  });

  it('does not advertise installation inside Capacitor', () => {
    expect(render('ios', true).nativeElement.querySelector('aside')).toBeNull();
  });

  it('can be dismissed', () => {
    const fixture = render('android');
    fixture.nativeElement.querySelector('button').click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('aside')).toBeNull();
  });
});
