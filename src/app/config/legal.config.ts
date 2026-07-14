/**
 * Identité légale de l'exploitant — source unique pour les pages CGU,
 * mentions légales et DMCA (auparavant dupliquée et incohérente entre les
 * trois : CGU/mentions légales affirmaient « LaProd SAS » avec des
 * placeholders RCS/SIRET jamais remplis, tandis que la page DMCA
 * mentionnait « exploité par Eliott Raillère », une personne physique).
 *
 * Statut réel (2026-07) : entreprise individuelle (auto-entrepreneur),
 * non constituée en société. Ne pas réintroduire de mentions
 * « SAS » / RCS / capital social tant que ce statut n'a pas changé —
 * représenter une société qui n'existe pas expose à la fois à un risque
 * de mentions légales incomplètes (art. 6-III LCEN) et à une tromperie
 * du consommateur sur la forme juridique du cocontractant.
 */
export const LEGAL_ENTITY = {
  legalForm:    'Entreprise individuelle (auto-entrepreneur)',
  operatorName: 'Eliott Raillère',
  // TODO(legal): compléter après vérification — ne pas inventer de valeurs.
  siren:        '[SIREN — à compléter]',
  apeCode:      '[code APE — à compléter]',
  address:      '[adresse à compléter]',

  platformName: 'LaProd',
  platformUrl:  'laprod.net',

  contactEmail: 'contact@laprod.net',
  adminEmail:   'admin@laprod.net',
  dmcaEmail:    'dmca@laprod.net',
} as const;
