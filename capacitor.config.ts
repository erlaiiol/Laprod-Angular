import type { CapacitorConfig } from '@capacitor/cli';

// En dev mobile (scripts/dev-android*.sh), le backend local (10.0.2.2:5000) est en HTTP.
// Si le WebView charge l'app en HTTPS, Chromium bloque en mixed content les XHR/images
// vers ce backend HTTP (l'autoupgrade HTTPS→échec de Chromium bloque même les <img>,
// indépendamment de WebSettings.setMixedContentMode côté natif — cf. MainActivity.java).
// On fait donc tourner l'app entière en HTTP le temps du dev local, pour rester sur une
// seule origine non sécurisée (page + API + images) et éviter tout mixed content.
const isMobileDev = process.env['MOBILE_DEV'] === '1';

const config: CapacitorConfig = {
  appId: 'net.laprod.app',
  appName: 'LaProd',
  webDir: 'dist/Laprod-Angular/browser',
  server: {
    // Sert les fichiers locaux sous le schéma HTTPS pour Android en prod
    // (http:// est refusé par les API modernes sur Android 9+) ; HTTP uniquement
    // en dev mobile local, voir commentaire ci-dessus.
    androidScheme: isMobileDev ? 'http' : 'https',
    hostname: 'app.laprod.net',
  },
  plugins: {
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
    SplashScreen: {
      launchShowDuration: 0,
      launchAutoHide: false,
      backgroundColor: '#101218',
      showSpinner: false,
    },
    Keyboard: {
      resize: 'body',
      style: 'dark',
    },
    // Évite que le plugin natif CapacitorSystemBars (Capacitor 8) ne gère les
    // insets en parallèle de @capacitor-community/safe-area — cf. sa doc.
    SystemBars: {
      insetsHandling: 'disable',
    },
  },
};

export default config;
