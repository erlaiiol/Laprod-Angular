export const environment = {
  production: false,
  // Le simulateur iOS partage le réseau de la machine hôte : localhost fonctionne
  // directement, contrairement à l'émulateur Android (voir environment.mobile-dev-android.ts).
  apiUrl: 'http://localhost:5000',
  appTitle: '(dev) LaProd',
  testimonialsEnabled: true,
  isNative: true,
  turnstileSiteKey: '',
  // Mode Clip — raccourcis de partage direct (docs/roadmap.md § Chantier 4, Passe 3).
  // Désactivés par défaut : la feuille de partage système reste la voie principale.
  // instagramAppId : App ID Meta (obligatoire pour instagram-stories://share).
  clipShortcuts: { instagramAppId: '', tiktok: false },
};
