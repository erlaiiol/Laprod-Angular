export const environment = {
  production: false,
  // 10.0.2.2 est l'alias réseau que l'émulateur Android utilise pour joindre
  // le localhost de la machine hôte (voir docker-compose.dev.yml : Flask sur :5000).
  apiUrl: 'http://10.0.2.2:5000',
  appTitle: '(dev) LaProd',
  testimonialsEnabled: true,
  isNative: true,
  turnstileSiteKey: '',
  // Mode Clip — raccourcis de partage direct (docs/roadmap.md § Chantier 4, Passe 3).
  // Désactivés par défaut : la feuille de partage système reste la voie principale.
  // instagramAppId : App ID Meta (obligatoire pour instagram-stories://share).
  clipShortcuts: { instagramAppId: '', tiktok: false },
};
