import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'net.laprod.app',
  appName: 'LaProd',
  webDir: 'dist/Laprod-Angular/browser',
  server: {
    // Sert les fichiers locaux sous le schéma HTTPS pour Android
    // (http:// est refusé par les API modernes sur Android 9+)
    androidScheme: 'https',
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
