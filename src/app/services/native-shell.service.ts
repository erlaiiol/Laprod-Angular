import { Injectable } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { App } from '@capacitor/app';
import { SplashScreen } from '@capacitor/splash-screen';
import { SafeArea, SystemBarsStyle } from '@capacitor-community/safe-area';

// ── Service ───────────────────────────────────────────────────────────────────
//
// Regroupe l'initialisation du "chrome" natif (status bar, splash screen) et
// la gestion du bouton retour matériel Android.
//
// Le bouton retour est un événement global unique côté natif : les overlays
// plein écran (mobile-studio, modales de confirmation, etc.) empilent un
// handler via pushBackHandler() pour l'intercepter tant qu'ils sont ouverts,
// au lieu de laisser Android quitter l'app ou naviguer de façon inattendue.

type BackHandler = () => boolean; // true = consommé, false = laisse remonter à la pile suivante

@Injectable({ providedIn: 'root' })
export class NativeShellService {

  private readonly _handlers: BackHandler[] = [];
  private _listening = false;

  /** À appeler une seule fois au démarrage de l'app (App.ngOnInit). */
  async init(): Promise<void> {
    if (!Capacitor.isNativePlatform()) return;

    await SafeArea.setSystemBarsStyle({ style: SystemBarsStyle.Dark }).catch(() => {});
    await SplashScreen.hide().catch(() => {});

    if (!this._listening) {
      this._listening = true;
      App.addListener('backButton', ({ canGoBack }) => {
        // Le handler le plus récent (overlay ouvert) intercepte en premier.
        for (let i = this._handlers.length - 1; i >= 0; i--) {
          if (this._handlers[i]()) return;
        }
        if (canGoBack) {
          window.history.back();
        } else {
          App.exitApp();
        }
      });
    }
  }

  /** Empile un handler de retour (ex. fermer une modale). Retourne la fonction pour le retirer. */
  pushBackHandler(handler: BackHandler): () => void {
    this._handlers.push(handler);
    return () => {
      const i = this._handlers.indexOf(handler);
      if (i !== -1) this._handlers.splice(i, 1);
    };
  }
}
