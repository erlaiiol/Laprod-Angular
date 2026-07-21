export const environment = {
  production: false,
  apiUrl: '',
  appTitle: '(beta) LaProd',
  testimonialsEnabled: true,
  isNative: false,
  // Clé publique (site key) Cloudflare Turnstile. Vide = CAPTCHA désactivé côté
  // front. À activer en même temps que TURNSTILE_ENABLED côté backend.
  turnstileSiteKey: '',
};
