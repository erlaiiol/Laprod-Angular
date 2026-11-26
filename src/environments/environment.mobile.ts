export const environment = {
  production: true,
  // En mode Capacitor natif, l'app tourne dans un WebView local.
  // Les URLs relatives ne pointent pas vers laprod.net → préfixe absolu obligatoire.
  apiUrl: 'https://laprod.net',
  appTitle: 'LaProd',
  testimonialsEnabled: false,
  isNative: true,
  // CAPTCHA web uniquement : jamais rendu en natif (isNative), clé laissée vide.
  turnstileSiteKey: '',
  // Mode Clip — raccourcis de partage direct (docs/roadmap.md § Chantier 4, Passe 3).
  // Désactivés par défaut : la feuille de partage système reste la voie principale.
  // instagramAppId : App ID Meta (obligatoire pour instagram-stories://share).
  clipShortcuts: { instagramAppId: '', tiktok: false },
};
