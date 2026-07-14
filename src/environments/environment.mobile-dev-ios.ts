export const environment = {
  production: false,
  // Le simulateur iOS partage le réseau de la machine hôte : localhost fonctionne
  // directement, contrairement à l'émulateur Android (voir environment.mobile-dev-android.ts).
  apiUrl: 'http://localhost:5000',
  appTitle: '(dev) LaProd',
  testimonialsEnabled: true,
  isNative: true,
  turnstileSiteKey: '',
};
