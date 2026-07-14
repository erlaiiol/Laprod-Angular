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
};
