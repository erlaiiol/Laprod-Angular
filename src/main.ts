import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';
import { environment } from './environments/environment';
import { Capacitor } from '@capacitor/core';

document.title = environment.appTitle;

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
