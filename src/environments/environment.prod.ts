export const environment = {
  production: true,
  // En prod, Angular est servi par le même nginx que Flask.
  // apiUrl vide = même origine → pas de CORS, pas de préfixe absolu.
  apiUrl: '',
  appTitle: 'LaProd',
  testimonialsEnabled: false,
  isNative: false,
  // Clé publique (site key) Cloudflare Turnstile. Vide = CAPTCHA désactivé côté
  // front. À renseigner + TURNSTILE_ENABLED=true côté backend pour activer.
  turnstileSiteKey: '',
  // Mode Clip — raccourcis de partage direct (docs/roadmap.md § Chantier 4, Passe 3).
  // Désactivés par défaut : la feuille de partage système reste la voie principale.
  // instagramAppId : App ID Meta (obligatoire pour instagram-stories://share).
  clipShortcuts: { instagramAppId: '', tiktok: false },
};
