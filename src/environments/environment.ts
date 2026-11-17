export const environment = {
  production: false,
  apiUrl: '',
  appTitle: '(beta) LaProd',
  testimonialsEnabled: true,
  isNative: false,
  // Clé publique (site key) Cloudflare Turnstile. Vide = CAPTCHA désactivé côté
  // front. À activer en même temps que TURNSTILE_ENABLED côté backend.
  turnstileSiteKey: '',
  // Mode Clip — raccourcis de partage direct (docs/roadmap.md § Chantier 4, Passe 3).
  // Désactivés par défaut : la feuille de partage système reste la voie principale.
  // instagramAppId : App ID Meta (obligatoire pour instagram-stories://share).
  clipShortcuts: { instagramAppId: '', tiktok: false },
};
