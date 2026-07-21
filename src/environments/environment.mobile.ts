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
};
