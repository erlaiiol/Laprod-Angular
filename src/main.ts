import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { environment } from './environments/environment';
import { Capacitor } from '@capacitor/core';

document.title = environment.appTitle;

// App native : pas de zoom du tout. Un double-tap accidentel zoomait la page
// et le WebView ne permettait plus de revenir à l'échelle 1. maximum-scale=1
// empêche aussi l'auto-zoom iOS au focus d'un champ < 16px. Sur le web on garde
// le zoom (accessibilité), seul le double-tap est neutralisé en CSS.
if (Capacitor.isNativePlatform()) {
  document.querySelector('meta[name="viewport"]')?.setAttribute(
    'content',
    'width=device-width, initial-scale=1, minimum-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover',
  );
}

bootstrapApplication(App, appConfig)
  .catch(async (err) => {
    console.error(err);
    // A temporarily locked/unavailable credential store must allow a retry,
    // without deleting the saved session or leaving the native splash visible.
    if (Capacitor.isNativePlatform()) {
      const { SplashScreen } = await import('@capacitor/splash-screen');
      await SplashScreen.hide().catch(() => {});
    }
    const panel = document.createElement('div');
    panel.setAttribute('role', 'alert');
    panel.style.cssText = 'padding:3rem 1.5rem;text-align:center;color:#fff;background:#101218;min-height:100vh';
    const message = document.createElement('p');
    message.textContent = 'Impossible d’ouvrir l’application. Déverrouillez votre appareil, puis réessayez.';
    const retry = document.createElement('button');
    retry.textContent = 'Réessayer';
    retry.onclick = () => window.location.reload();
    panel.append(message, retry);
    document.querySelector('app-root')?.replaceChildren(panel);
  });
