export const environment = {
  production: true,
  // En prod, Angular est servi par le même nginx que Flask.
  // apiUrl vide = même origine → pas de CORS, pas de préfixe absolu.
  apiUrl: ''
};
