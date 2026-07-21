import { ContractType } from '../../services/contract-builder.service';

/**
 * Configuration par famille de contrat (exploitation | performance).
 *
 * Le moteur du builder (renderer, variables, validation, preview, brouillons,
 * export) est entièrement mutualisé dans BuilderFormComponent : chaque famille
 * ne fournit ici que sa spécialisation — variables d'introduction, presets,
 * quick-start et avertissements juridiques.
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export interface PresetClauseSpec {
  group: string;
  clause: string;
  value?: any;
}

export interface Preset {
  id: string;
  icon: string;
  label: string;
  description: string;
  meta: string;
  badge: string;
  level: 'easy' | 'medium' | 'expert';
  clauses: PresetClauseSpec[];
}

export interface QuickStartSpec {
  group:  string;
  clause: string;
  field:  string;
  value:  string;
}

export interface IntroFieldDef {
  id:          string;               // clé de stockage locale
  label:       string;
  placeholder?: string;
  inputType:   'text' | 'number' | 'select';
  options?:    string[];
  bracket?:    string;               // variable exposée, ex "[l'Œuvre]"
  suffix?:     string;               // suffixe appliqué à la valeur résolue, ex '%'
  wide?:       boolean;
  min?:        number;
  max?:        number;
}

export interface IntroSectionDef {
  title:  string;
  icon:   string;
  hint?:  string;
  fields: IntroFieldDef[];
}

export interface ContractTypeConfig {
  type:  ContractType;
  label: string;
  /** Badge affiché sur le Contractant 1 dans l'intro */
  firstPartyBadge: string;
  /** Placeholder du champ "Rôle dans le contrat" */
  rolePlaceholder: string;
  /** Variables requises pour activer le Quick Start (en plus des 2 parties) */
  keyBrackets: string[];
  /** Message affiché quand les infos clés manquent */
  keyInfoHint: string;
  /** Description du bandeau Quick Start */
  quickStartDescription: string;
  /** Note juridique du panneau latéral */
  guideNote: string;
  introSections:     IntroSectionDef[];
  presets:           Preset[];
  quickStartClauses: QuickStartSpec[];
  quickStartToggles: string[];
  /** Carte d'avertissement statique dans l'intro (ex : salariat du spectacle) */
  legalWarning?: { title: string; text: string };
  /** Clauses (clé "Groupe||Clause") qui, activées avec un Contractant 1 personne
   *  physique, déclenchent l'avertissement de requalification en salariat */
  salariatWatch?: { keys: string[]; message: string };
}

// ═══════════════════════════════════════════════════════════════════════════════
// EXPLOITATION — contrat d'exploitation d'œuvre musicale (config historique)
// ═══════════════════════════════════════════════════════════════════════════════

const EXPLOITATION_CONFIG: ContractTypeConfig = {
  type: 'exploitation',
  label: "Contrat d'exploitation",
  firstPartyBadge: 'Contractant 1 — Artiste / Titulaire',
  rolePlaceholder: 'ex : Artiste, Éditeur, Distributeur…',
  keyBrackets: ["[l'Œuvre]"],
  keyInfoHint: "Pour activer le pré-remplissage, renseignez le nom des deux parties et le titre de l'œuvre.",
  quickStartDescription: "Pré-remplissez les clauses essentielles d'une licence numérique à partir de vos champs automatiques.",
  guideNote: 'Ces modèles respectent le CPI (Code de la Propriété Intellectuelle). Consultez un avocat spécialisé pour toute clause sensible.',

  introSections: [
    {
      title: "L'œuvre concernée",
      icon: 'bi-music-note-beamed',
      fields: [
        { id: 'oeuvreTitle', label: "Titre de l'œuvre", placeholder: 'ex : Midnight Drive', inputType: 'text', bracket: "[l'Œuvre]", wide: true },
        { id: 'oeuvreType', label: 'Type', inputType: 'select', options: ['Chanson', 'Album', 'Instrumental', 'Autre'] },
        { id: 'oeuvreIsrc', label: 'Code ISRC', placeholder: 'ex : FR-ABC-23-01234', inputType: 'text', bracket: '[ISRC]' },
        { id: 'anneeCreation', label: 'Année de création', placeholder: 'ex : 2024', inputType: 'number', bracket: '[année de création]', min: 1900, max: 2099 },
        { id: 'dureeOeuvre', label: "Durée de l'œuvre", placeholder: 'ex : 3 min 42 s', inputType: 'text', bracket: "[durée de l'œuvre]" },
        { id: 'debutExploitation', label: "Début d'exploitation", placeholder: 'ex : 01/01/2025', inputType: 'text', bracket: "[début d'exploitation]" },
        { id: 'finExploitation', label: "Fin d'exploitation", placeholder: 'ex : 31/12/2027', inputType: 'text', bracket: "[fin d'exploitation]" },
      ],
    },
    {
      title: 'Clés financières',
      icon: 'bi-percent',
      fields: [
        { id: 'pctArtiste', label: '% Artiste', placeholder: 'ex : 70', inputType: 'number', bracket: '[% Artiste]', suffix: '%', min: 0, max: 100 },
        { id: 'pctEditeur', label: '% Éditeur', placeholder: 'ex : 20', inputType: 'number', bracket: '[% Éditeur]', suffix: '%', min: 0, max: 100 },
        { id: 'pctProducteur', label: '% Producteur', placeholder: 'ex : 10', inputType: 'number', bracket: '[% Producteur]', suffix: '%', min: 0, max: 100 },
        { id: 'montantAvance', label: "Montant de l'avance (€)", placeholder: 'ex : 2000', inputType: 'number', bracket: "[montant de l'avance]", suffix: ' €', min: 0 },
        { id: 'budgetMarketing', label: 'Budget marketing minimum (€)', placeholder: 'ex : 1500', inputType: 'number', bracket: '[budget marketing minimum]', suffix: ' €', min: 0 },
      ],
    },
  ],

  presets: [
    {
      id: 'licence-numerique',
      icon: 'bi-music-note-beamed',
      label: 'Licence numérique',
      description: 'Distribution digitale non-exclusive — Spotify, Apple Music, TikTok.',
      meta: '3 ans · France · Non-exclusive',
      badge: 'Débutant',
      level: 'easy',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Licence' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'Désignation des œuvres', clause: 'Description de l\'œuvre' },
        { group: 'Désignation des œuvres', clause: 'Versions concernées', value: { selected: ['Version originale'] } },
        { group: 'Nature des droits concédés', clause: 'Droit de reproduction' },
        { group: 'Nature des droits concédés', clause: 'Droit de représentation' },
        { group: 'Nature des droits concédés', clause: 'Droit de distribution' },
        { group: 'Nature des droits concédés', clause: 'Mise à disposition / Streaming' },
        { group: 'Modalités d\'exploitation', clause: 'Supports autorisés', value: { selected: ['Téléchargement numérique', 'Streaming', 'Réseaux sociaux'] } },
        { group: 'Territoire', clause: 'Territoire d\'exploitation', value: { territory: 'France' } },
        { group: 'Durée', clause: 'Durée du contrat', value: { amount: 3, unit: 'ans' } },
        { group: 'Obligations de l\'exploitant', clause: 'Obligation de distribution' },
        { group: 'Obligations de l\'auteur / artiste', clause: 'Respect des délais contractuels' },
        { group: 'Livraison des éléments techniques', clause: 'Éléments à livrer', value: { selected: ['Fichier WAV (master final)', 'Pochette haute résolution', 'Métadonnées complètes'] } },
        { group: 'Livraison des éléments techniques', clause: 'Délai de livraison', value: { amount: 1, unit: 'mois' } },
        { group: 'Royalties', clause: 'Mode de calcul', value: { selected: 'Sur net distributeur' } },
        { group: 'Royalties', clause: 'Taux — streaming (%)', value: { number: 20 } },
        { group: 'Comptabilité et audit', clause: 'Fréquence des relevés de comptes', value: { selected: 'Semestriel' } },
        { group: 'Comptabilité et audit', clause: 'Conservation des données comptables (années)', value: { number: 5 } },
        { group: 'Comptabilité et audit', clause: 'Droit d\'audit' },
        { group: 'Garanties et propriété intellectuelle', clause: 'Obtention des autorisations nécessaires' },
        { group: 'Responsabilité et indemnisation', clause: 'Limitation de responsabilité' },
        { group: 'Responsabilité et indemnisation', clause: 'Prise en charge des litiges tiers' },
        { group: 'Exploitation numérique et plateformes', clause: 'Plateformes DSP (Spotify, Apple Music...)' },
        { group: 'Exploitation numérique et plateformes', clause: 'YouTube Content ID' },
        { group: 'Exploitation numérique et plateformes', clause: 'TikTok' },
        { group: 'Exploitation numérique et plateformes', clause: 'Meta (Instagram, Facebook Reels)' },
        { group: 'Données, métadonnées et collecte', clause: 'Gestion des identifiants (ISRC, ISWC, UPC)' },
        { group: 'Données, métadonnées et collecte', clause: 'Reporting plateforme' },
        { group: 'Données, métadonnées et collecte', clause: 'Collecte SACEM / droits voisins' },
        { group: 'Communication et image', clause: 'Droit d\'utiliser le nom / image / voix' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Suspension du contrat' } },
        { group: 'Résiliation', clause: 'Résiliation pour non-paiement' },
        { group: 'Résiliation', clause: 'Résiliation pour faillite / liquidation' },
        { group: 'Résiliation', clause: 'Effets et délais de résiliation' },
        { group: 'Réversion des droits', clause: 'Retour automatique des droits' },
        { group: 'Réversion des droits', clause: 'Conditions de réversion' },
        { group: 'Notifications', clause: 'Email contractuel du cessionnaire' },
        { group: 'Clauses générales', clause: 'Clause de non-renonciation' },
        { group: 'Clauses générales', clause: 'Survie des clauses' },
      ],
    },
    {
      id: 'licence-exclusive',
      icon: 'bi-shield-check',
      label: 'Licence exclusive',
      description: 'Contrat label ou distributeur avec exclusivité, avances et royalties.',
      meta: '5 ans · Monde entier · Exclusive',
      badge: 'Intermédiaire',
      level: 'medium',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Définitions contractuelles', clause: 'Glossaire des termes' },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Licence' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'Désignation des œuvres', clause: 'Description de l\'œuvre' },
        { group: 'Désignation des œuvres', clause: 'Versions concernées', value: { selected: ['Version originale', 'Version instrumentale'] } },
        { group: 'Nature des droits concédés', clause: 'Droit de reproduction' },
        { group: 'Nature des droits concédés', clause: 'Droit de représentation' },
        { group: 'Nature des droits concédés', clause: 'Droit de distribution' },
        { group: 'Nature des droits concédés', clause: 'Mise à disposition / Streaming' },
        { group: 'Modalités d\'exploitation', clause: 'Supports autorisés', value: { selected: ['Vinyle', 'CD', 'Téléchargement numérique', 'Streaming', 'Réseaux sociaux', 'Télévision / Radio'] } },
        { group: 'Territoire', clause: 'Territoire d\'exploitation', value: { territory: 'Monde entier' } },
        { group: 'Durée', clause: 'Durée du contrat', value: { amount: 5, unit: 'ans' } },
        { group: 'Exclusivité', clause: 'Exclusivité totale' },
        { group: 'Exclusivité', clause: 'Exceptions à l\'exclusivité' },
        { group: 'Obligations de l\'exploitant', clause: 'Obligation de distribution' },
        { group: 'Obligations de l\'exploitant', clause: 'Minimum marketing' },
        { group: 'Obligations de l\'exploitant', clause: 'Obligation de maintien de disponibilité' },
        { group: 'Obligations de l\'auteur / artiste', clause: 'Disponibilité promotionnelle' },
        { group: 'Obligations de l\'auteur / artiste', clause: 'Respect des délais contractuels' },
        { group: 'Livraison des éléments techniques', clause: 'Éléments à livrer', value: { selected: ['Fichier WAV (master final)', 'Stems / pistes séparées', 'Pochette haute résolution', 'Métadonnées complètes', 'Paroles (lyrics)', 'Crédits complets'] } },
        { group: 'Livraison des éléments techniques', clause: 'Formats et normes techniques' },
        { group: 'Livraison des éléments techniques', clause: 'Délai de livraison', value: { amount: 1, unit: 'mois' } },
        { group: 'Avances', clause: 'Type d\'avance', value: { selected: 'Avance recoupable' } },
        { group: 'Avances', clause: 'Montant de l\'avance (€)' },
        { group: 'Avances', clause: 'Conditions de versement' },
        { group: 'Royalties', clause: 'Mode de calcul', value: { selected: 'Sur net distributeur' } },
        { group: 'Royalties', clause: 'Taux — exploitation physique (%)' },
        { group: 'Royalties', clause: 'Taux — streaming (%)', value: { number: 25 } },
        { group: 'Royalties', clause: 'Taux — synchronisation (%)' },
        { group: 'Recoupement', clause: 'Recoupement prévu' },
        { group: 'Recoupement', clause: 'Dépenses recoupables' },
        { group: 'Comptabilité et audit', clause: 'Fréquence des relevés de comptes', value: { selected: 'Trimestriel' } },
        { group: 'Comptabilité et audit', clause: 'Conservation des données comptables (années)', value: { number: 5 } },
        { group: 'Comptabilité et audit', clause: 'Droit d\'audit' },
        { group: 'Comptabilité et audit', clause: 'Procédure d\'audit' },
        { group: 'Garanties et propriété intellectuelle', clause: 'Obtention des autorisations nécessaires' },
        { group: 'Responsabilité et indemnisation', clause: 'Limitation de responsabilité' },
        { group: 'Responsabilité et indemnisation', clause: 'Prise en charge des litiges tiers' },
        { group: 'Droits moraux', clause: 'Validation artistique requise' },
        { group: 'Exploitation numérique et plateformes', clause: 'Plateformes DSP (Spotify, Apple Music...)' },
        { group: 'Exploitation numérique et plateformes', clause: 'YouTube Content ID' },
        { group: 'Exploitation numérique et plateformes', clause: 'TikTok' },
        { group: 'Exploitation numérique et plateformes', clause: 'Meta (Instagram, Facebook Reels)' },
        { group: 'Données, métadonnées et collecte', clause: 'Gestion des identifiants (ISRC, ISWC, UPC)' },
        { group: 'Données, métadonnées et collecte', clause: 'Reporting plateforme' },
        { group: 'Données, métadonnées et collecte', clause: 'Collecte SACEM / droits voisins' },
        { group: 'Communication et image', clause: 'Droit d\'utiliser le nom / image / voix' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Suspension du contrat' } },
        { group: 'Résiliation', clause: 'Résiliation pour non-paiement' },
        { group: 'Résiliation', clause: 'Résiliation pour faillite / liquidation' },
        { group: 'Résiliation', clause: 'Résiliation pour absence d\'exploitation' },
        { group: 'Résiliation', clause: 'Résiliation pour violation d\'exclusivité' },
        { group: 'Résiliation', clause: 'Effets et délais de résiliation' },
        { group: 'Réversion des droits', clause: 'Retour automatique des droits' },
        { group: 'Réversion des droits', clause: 'Récupération des masters' },
        { group: 'Réversion des droits', clause: 'Conditions de réversion' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Médiation préalable obligatoire' },
        { group: 'Notifications', clause: 'Email contractuel du cessionnaire' },
        { group: 'Clauses générales', clause: 'Clause de non-renonciation' },
        { group: 'Clauses générales', clause: 'Survie des clauses' },
        { group: 'Clauses générales', clause: 'Ordre de priorité des annexes' },
      ],
    },
    {
      id: 'edition-musicale',
      icon: 'bi-music-note-list',
      label: 'Édition musicale',
      description: 'Auteur-compositeur confiant la gestion de ses droits à un éditeur (SACEM).',
      meta: '3 ans · Monde entier · Éditeur musical',
      badge: 'Expert',
      level: 'expert',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Préambule', clause: 'Historique de collaboration' },
        { group: 'Définitions contractuelles', clause: 'Glossaire des termes' },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Édition' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'Désignation des œuvres', clause: 'Description de l\'œuvre' },
        { group: 'Désignation des œuvres', clause: 'Code ISWC' },
        { group: 'Désignation des œuvres', clause: 'Code ISRC' },
        { group: 'Désignation des œuvres', clause: 'Versions concernées', value: { selected: ['Version originale', 'Version instrumentale', 'Stems / pistes séparées'] } },
        { group: 'Désignation des œuvres', clause: 'Fichiers et éléments livrés' },
        { group: 'Nature des droits concédés', clause: 'Droit de reproduction' },
        { group: 'Nature des droits concédés', clause: 'Droit de représentation' },
        { group: 'Nature des droits concédés', clause: 'Droit de distribution' },
        { group: 'Nature des droits concédés', clause: 'Mise à disposition / Streaming' },
        { group: 'Nature des droits concédés', clause: 'Droit d\'adaptation / arrangement' },
        { group: 'Modalités d\'exploitation', clause: 'Supports autorisés', value: { selected: ['Vinyle', 'CD', 'Cassette', 'Téléchargement numérique', 'Streaming', 'Réseaux sociaux', 'Télévision / Radio', 'Cinéma', 'Jeux vidéo', 'Applications mobiles'] } },
        { group: 'Territoire', clause: 'Territoire d\'exploitation', value: { territory: 'Monde entier' } },
        { group: 'Durée', clause: 'Durée du contrat', value: { amount: 3, unit: 'ans' } },
        { group: 'Exclusivité', clause: 'Exclusivité totale' },
        { group: 'Exclusivité', clause: 'Exceptions à l\'exclusivité' },
        { group: 'Obligations de l\'exploitant', clause: 'Obligation de distribution' },
        { group: 'Obligations de l\'exploitant', clause: 'Minimum marketing' },
        { group: 'Obligations de l\'exploitant', clause: 'Obligation de maintien de disponibilité' },
        { group: 'Obligations de l\'auteur / artiste', clause: 'Disponibilité promotionnelle' },
        { group: 'Obligations de l\'auteur / artiste', clause: 'Respect des délais contractuels' },
        { group: 'Livraison des éléments techniques', clause: 'Éléments à livrer', value: { selected: ['Fichier WAV (master final)', 'Stems / pistes séparées', 'Pochette haute résolution', 'Métadonnées complètes', 'Paroles (lyrics)', 'Crédits complets', 'Photos presse'] } },
        { group: 'Livraison des éléments techniques', clause: 'Formats et normes techniques' },
        { group: 'Livraison des éléments techniques', clause: 'Délai de livraison', value: { amount: 1, unit: 'mois' } },
        { group: 'Avances', clause: 'Type d\'avance', value: { selected: 'Avance recoupable' } },
        { group: 'Avances', clause: 'Montant de l\'avance (€)' },
        { group: 'Avances', clause: 'Conditions de versement' },
        { group: 'Royalties', clause: 'Mode de calcul', value: { selected: 'Sur net distributeur' } },
        { group: 'Royalties', clause: 'Taux — exploitation physique (%)' },
        { group: 'Royalties', clause: 'Taux — streaming (%)', value: { number: 25 } },
        { group: 'Royalties', clause: 'Taux — synchronisation (%)' },
        { group: 'Royalties', clause: 'Taux — YouTube / UGC (%)' },
        { group: 'Recoupement', clause: 'Recoupement prévu' },
        { group: 'Recoupement', clause: 'Dépenses recoupables' },
        { group: 'Comptabilité et audit', clause: 'Fréquence des relevés de comptes', value: { selected: 'Trimestriel' } },
        { group: 'Comptabilité et audit', clause: 'Conservation des données comptables (années)', value: { number: 5 } },
        { group: 'Comptabilité et audit', clause: 'Droit d\'audit' },
        { group: 'Comptabilité et audit', clause: 'Procédure d\'audit' },
        { group: 'Garanties et propriété intellectuelle', clause: 'Obtention des autorisations nécessaires' },
        { group: 'Responsabilité et indemnisation', clause: 'Limitation de responsabilité' },
        { group: 'Responsabilité et indemnisation', clause: 'Prise en charge des litiges tiers' },
        { group: 'Droits moraux', clause: 'Validation artistique requise' },
        { group: 'Synchronisation et usages audiovisuels', clause: 'Cinéma / Séries télévisées' },
        { group: 'Synchronisation et usages audiovisuels', clause: 'Plateformes sociales (Reels, Shorts, TikTok)' },
        { group: 'Synchronisation et usages audiovisuels', clause: 'Trailers / Bande-annonces' },
        { group: 'Synchronisation et usages audiovisuels', clause: 'Précisions synchro' },
        { group: 'Exploitation numérique et plateformes', clause: 'Plateformes DSP (Spotify, Apple Music...)' },
        { group: 'Exploitation numérique et plateformes', clause: 'YouTube Content ID' },
        { group: 'Exploitation numérique et plateformes', clause: 'TikTok' },
        { group: 'Exploitation numérique et plateformes', clause: 'Meta (Instagram, Facebook Reels)' },
        { group: 'Exploitation numérique et plateformes', clause: 'UGC / Remix utilisateurs' },
        { group: 'Données, métadonnées et collecte', clause: 'Gestion des identifiants (ISRC, ISWC, UPC)' },
        { group: 'Données, métadonnées et collecte', clause: 'Reporting plateforme' },
        { group: 'Données, métadonnées et collecte', clause: 'Collecte SACEM / droits voisins' },
        { group: 'Données, métadonnées et collecte', clause: 'Matching Content ID' },
        { group: 'Communication et image', clause: 'Droit d\'utiliser le nom / image / voix' },
        { group: 'Communication et image', clause: 'Biographie pour la presse' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Suspension du contrat' } },
        { group: 'Résiliation', clause: 'Résiliation pour non-paiement' },
        { group: 'Résiliation', clause: 'Résiliation pour faillite / liquidation' },
        { group: 'Résiliation', clause: 'Résiliation pour absence d\'exploitation' },
        { group: 'Résiliation', clause: 'Résiliation pour violation d\'exclusivité' },
        { group: 'Résiliation', clause: 'Effets et délais de résiliation' },
        { group: 'Réversion des droits', clause: 'Retour automatique des droits' },
        { group: 'Réversion des droits', clause: 'Récupération des masters' },
        { group: 'Réversion des droits', clause: 'Conditions de réversion' },
        { group: 'Cession du contrat et sous-licence', clause: 'Sous-licence autorisée' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Médiation préalable obligatoire' },
        { group: 'Notifications', clause: 'Email contractuel du cessionnaire' },
        { group: 'Clauses générales', clause: 'Clause de non-renonciation' },
        { group: 'Clauses générales', clause: 'Survie des clauses' },
        { group: 'Clauses générales', clause: 'Ordre de priorité des annexes' },
        { group: 'Annexes', clause: 'Liste des annexes' },
      ],
    },
  ],

  quickStartClauses: [
    {
      group: 'Préambule', clause: 'Contexte et volonté des parties', field: 'text',
      value:
        "[Contractant 1], en qualité de [Rôle 1], ci-après dénommé(e) « le [Rôle 1] », " +
        "et [Contractant 2], en qualité de [Rôle 2], ci-après dénommé(e) « le [Rôle 2] », " +
        "ont convenu, d'un commun accord, de formaliser les conditions d'exploitation de " +
        "l'œuvre musicale intitulée [l'Œuvre], aux fins et dans les limites définies par " +
        "le présent contrat. Les parties déclarent avoir pris connaissance de l'ensemble " +
        "des dispositions ci-après et en accepter les termes sans réserve.",
    },
    {
      group: 'Objet du contrat', clause: 'Finalité et description', field: 'text',
      value:
        "Le présent contrat a pour objet de définir les conditions dans lesquelles " +
        "[Contractant 1], en qualité de [Rôle 1], concède à [Contractant 2], en qualité " +
        "de [Rôle 2], le droit d'exploiter l'œuvre musicale intitulée [l'Œuvre], du " +
        "[début d'exploitation] au [fin d'exploitation], dans les limites territoriales et " +
        "selon les modalités précisées aux articles suivants. Cette exploitation s'inscrit " +
        "dans le cadre du développement de la carrière artistique de [Contractant 1] et " +
        "de la promotion de [l'Œuvre] sur l'ensemble des marchés couverts par le présent accord.",
    },
    {
      group: 'Désignation des œuvres', clause: 'Description de l\'œuvre', field: 'text',
      value:
        "L'œuvre faisant l'objet du présent contrat est une composition musicale originale " +
        "intitulée [l'Œuvre], créée en [année de création], d'une durée de [durée de l'œuvre], " +
        "dont les droits d'auteur appartiennent à [Contractant 1]. Elle est identifiée par " +
        "le code ISRC [ISRC] et livrée sous format WAV 24 bits / 44,1 kHz, accompagnée des " +
        "stems multipistes, du visuel de pochette haute résolution et des métadonnées " +
        "complètes conformes aux standards DDEX.",
    },
    {
      group: 'Exclusivité', clause: 'Exclusivité totale', field: 'details',
      value:
        "[Contractant 1] concède à [Contractant 2] une exclusivité totale sur l'ensemble " +
        "des droits d'exploitation de [l'Œuvre] définis au présent contrat, pour tous les " +
        "territoires couverts et pour toute la durée du présent accord. Pendant cette période, " +
        "[Contractant 1] s'engage à ne pas concéder à un tiers le droit d'exploiter [l'Œuvre], " +
        "directement ou indirectement, sous quelque forme que ce soit.",
    },
    {
      group: 'Comptabilité et audit', clause: 'Procédure d\'audit', field: 'text',
      value:
        "[Contractant 1] ou son mandataire dûment habilité pourra, après notification écrite " +
        "adressée à [Contractant 2] avec un préavis minimum de trente (30) jours, procéder à " +
        "la vérification des livres de compte et documents comptables afférents à l'exploitation " +
        "de [l'Œuvre]. Cet audit ne pourra être effectué qu'une seule fois par exercice " +
        "comptable. Les frais d'audit seront à la charge de [Contractant 1], sauf si l'audit " +
        "révèle un écart supérieur à 5 % en défaveur de [Contractant 1], auquel cas ils seront " +
        "supportés par [Contractant 2].",
    },
    {
      group: 'Résiliation', clause: 'Effets et délais de résiliation', field: 'text',
      value:
        "En cas de résiliation du présent contrat, pour quelque cause que ce soit, " +
        "[Contractant 2] s'engage à retirer [l'Œuvre] de l'ensemble des plateformes de " +
        "distribution dans un délai de trente (30) jours ouvrés à compter de la notification " +
        "de résiliation. Les créances antérieures à la date de résiliation demeurent exigibles. " +
        "[Contractant 1] conserve le droit de percevoir les royalties afférentes aux " +
        "exploitations intervenues avant la date de résiliation effective.",
    },
    {
      group: 'Réversion des droits', clause: 'Retour automatique des droits', field: 'details',
      value:
        "À l'issue du présent contrat ou en cas de résiliation anticipée pour quelque cause " +
        "que ce soit, l'ensemble des droits concédés par [Contractant 1] seront automatiquement " +
        "et de plein droit révertis à ce dernier, sans formalité ni indemnité. [Contractant 2] " +
        "s'engage à prendre toutes les mesures nécessaires pour que ces droits soient " +
        "effectivement libérés dans les meilleurs délais.",
    },
    {
      group: 'Réversion des droits', clause: 'Conditions de réversion', field: 'text',
      value:
        "Les droits concédés par [Contractant 1] seront automatiquement révertis dans les " +
        "cas suivants : (i) si [Contractant 2] n'a pas procédé à la première exploitation " +
        "commerciale de [l'Œuvre] avant le [début d'exploitation] convenu ou dans les " +
        "dix-huit (18) mois suivant la livraison des masters définitifs ; (ii) si [l'Œuvre] " +
        "cesse d'être disponible à l'écoute sur les principales plateformes de streaming " +
        "(Spotify, Apple Music, Deezer) pendant une période continue de douze (12) mois ; " +
        "(iii) en cas de liquidation judiciaire de [Contractant 2] ; (iv) à l'échéance " +
        "du [fin d'exploitation] si aucun renouvellement n'a été signé.",
    },
  ],

  quickStartToggles: [
    'Préambule||Contexte et volonté des parties',
    'Nature des droits concédés||Droit de reproduction',
    'Nature des droits concédés||Droit de représentation',
    'Nature des droits concédés||Droit de distribution',
    'Nature des droits concédés||Mise à disposition / Streaming',
    'Exploitation numérique et plateformes||Plateformes DSP (Spotify, Apple Music...)',
    'Exploitation numérique et plateformes||YouTube Content ID',
    'Exploitation numérique et plateformes||TikTok',
    'Exploitation numérique et plateformes||Meta (Instagram, Facebook Reels)',
    'Données, métadonnées et collecte||Gestion des identifiants (ISRC, ISWC, UPC)',
    'Données, métadonnées et collecte||Reporting plateforme',
    'Données, métadonnées et collecte||Collecte SACEM / droits voisins',
    'Obligations de l\'exploitant||Obligation de distribution',
    'Obligations de l\'exploitant||Obligation d\'exploitation de bonne foi',
    'Garanties et propriété intellectuelle||Garantie de titularité des droits',
    'Garanties et propriété intellectuelle||Garantie d\'originalité',
    'Garanties et propriété intellectuelle||Absence de sample non autorisé',
    'Droits moraux||Droit au crédit (mention obligatoire)',
    'Confidentialité||Périmètre de la confidentialité',
    'Force majeure||Événements couverts',
    'Résiliation||Résiliation pour inexécution',
    'Clauses générales||Divisibilité des clauses',
    'Clauses générales||Intégralité du contrat',
    'Clauses générales||Modification écrite obligatoire',
  ],
};

// ═══════════════════════════════════════════════════════════════════════════════
// PERFORMANCE — contrat de représentation / restitution d'œuvre musicale (live)
// ═══════════════════════════════════════════════════════════════════════════════

const PERFORMANCE_CONFIG: ContractTypeConfig = {
  type: 'performance',
  label: 'Contrat de représentation',
  firstPartyBadge: 'Contractant 1 — Artiste / Producteur du spectacle',
  rolePlaceholder: 'ex : Artiste, Producteur, Organisateur…',
  keyBrackets: ["[l'Évènement]"],
  keyInfoHint: "Pour activer le pré-remplissage, renseignez le nom des deux parties et le nom de l'évènement.",
  quickStartDescription: "Pré-remplissez les clauses essentielles d'un contrat de concert à partir de vos champs automatiques.",
  guideNote: "Ces modèles suivent les usages du spectacle vivant (contrat de cession / prestation entre entrepreneurs indépendants). Ils ne remplacent pas un contrat d'engagement d'artiste salarié : en cas de doute, consultez un avocat ou le GUSO.",

  introSections: [
    {
      title: "L'évènement",
      icon: 'bi-calendar-event',
      fields: [
        { id: 'eventName', label: "Nom de l'évènement", placeholder: 'ex : Festival Les Nuits Électriques', inputType: 'text', bracket: "[l'Évènement]", wide: true },
        { id: 'eventDate', label: "Date de l'évènement", placeholder: 'ex : 21/06/2026', inputType: 'text', bracket: '[date de l\'évènement]' },
        { id: 'venue', label: 'Lieu (salle / site)', placeholder: 'ex : Le Trabendo', inputType: 'text', bracket: '[lieu]' },
        { id: 'venueAddress', label: 'Adresse du lieu', placeholder: 'ex : 211 avenue Jean Jaurès, 75019 Paris', inputType: 'text', bracket: '[adresse du lieu]', wide: true },
        { id: 'jauge', label: 'Jauge (capacité)', placeholder: 'ex : 700', inputType: 'number', bracket: '[jauge]', min: 0 },
      ],
    },
    {
      title: 'La prestation',
      icon: 'bi-music-note-beamed',
      fields: [
        { id: 'setDuration', label: 'Durée de la prestation', placeholder: 'ex : 90 minutes', inputType: 'text', bracket: '[durée de la prestation]' },
        { id: 'stageTime', label: 'Heure de passage', placeholder: 'ex : 21h30', inputType: 'text', bracket: '[heure de passage]' },
        { id: 'soundcheckTime', label: 'Heure des balances', placeholder: 'ex : 17h00', inputType: 'text', bracket: '[heure de balance]' },
      ],
    },
    {
      title: 'Clés financières',
      icon: 'bi-cash-coin',
      fields: [
        { id: 'cachet', label: 'Cachet / prix de cession (€ HT)', placeholder: 'ex : 1500', inputType: 'number', bracket: '[cachet]', suffix: ' €', min: 0 },
        { id: 'acompte', label: 'Acompte (€)', placeholder: 'ex : 500', inputType: 'number', bracket: '[acompte]', suffix: ' €', min: 0 },
        { id: 'pctRecettes', label: '% partage billetterie', placeholder: 'ex : 65', inputType: 'number', bracket: '[% de partage]', suffix: '%', min: 0, max: 100 },
        { id: 'perDiem', label: 'Per diem (€/jour/personne)', placeholder: 'ex : 25', inputType: 'number', bracket: '[per diem]', suffix: ' €', min: 0 },
      ],
    },
  ],

  legalWarning: {
    title: 'Représentation ≠ contrat de travail',
    text: "Ce module génère un contrat entre entrepreneurs indépendants : l'artiste (ou son producteur) vend un spectacle « clé en main » à un organisateur. "
        + "Si l'artiste est une personne physique sans structure (société, association, entrepreneur de spectacles déclaré), la loi le présume SALARIÉ de l'organisateur "
        + "(art. L7121-3 du Code du travail) : il faut alors un contrat d'engagement avec bulletin de paie — via le GUSO pour les organisateurs occasionnels — et non ce contrat.",
  },

  salariatWatch: {
    keys: [
      'Rémunération||Montant du cachet / prix de cession (€ HT)',
      'Rémunération||Formule de rémunération',
    ],
    message: "Votre Contractant 1 est une personne physique et une rémunération est prévue : vérifiez qu'il exerce bien comme entrepreneur indépendant "
           + "(micro-entreprise, société, récépissé d'entrepreneur de spectacles). À défaut, la relation relève du salariat du spectacle "
           + "(présomption de l'art. L7121-3 C. trav.) et ce contrat n'est pas adapté — utilisez un contrat d'engagement (GUSO).",
  },

  presets: [
    {
      id: 'concert-classique',
      icon: 'bi-mic',
      label: 'Concert classique',
      description: 'Artiste ↔ Organisateur : cachet fixe, technique fournie par la salle.',
      meta: 'Cachet fixe · Salle équipée · Cession de spectacle',
      badge: 'Débutant',
      level: 'easy',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Objet du contrat', clause: 'Type d\'évènement', value: { selected: 'Concert' } },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Contrat de cession du droit d\'exploitation d\'un spectacle' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'Prestation artistique', clause: 'Horaire de passage' },
        { group: 'Prestation artistique', clause: 'Balances / Soundcheck' },
        { group: 'Prestation artistique', clause: 'Effectif et line-up' },
        { group: 'Prestation artistique', clause: 'Interdiction de se faire remplacer' },
        { group: 'Rémunération', clause: 'Formule de rémunération', value: { selected: 'Cachet fixe' } },
        { group: 'Rémunération', clause: 'Montant du cachet / prix de cession (€ HT)' },
        { group: 'Rémunération', clause: 'Acompte' },
        { group: 'Rémunération', clause: 'Modalités et délai de paiement' },
        { group: 'Défraiements et hospitalité', clause: 'Repas / catering' },
        { group: 'Conditions techniques', clause: 'Fiche technique annexée' },
        { group: 'Conditions techniques', clause: 'Sonorisation et éclairage fournis par', value: { selected: 'L\'Organisateur' } },
        { group: 'Conditions techniques', clause: 'Loges' },
        { group: 'Captation, image et promotion', clause: 'Utilisation promotionnelle du nom et de l\'image' },
        { group: 'Obligations de l\'organisateur', clause: 'Déclaration et paiement SACEM' },
        { group: 'Obligations de l\'organisateur', clause: 'Sécurité du public et service d\'ordre' },
        { group: 'Obligations de l\'organisateur', clause: 'Autorisations administratives' },
        { group: 'Obligations de l\'organisateur', clause: 'Assurance responsabilité civile organisateur' },
        { group: 'Obligations de l\'artiste', clause: 'Ponctualité et présence' },
        { group: 'Obligations de l\'artiste', clause: 'Prestation conforme' },
        { group: 'Annulation et report', clause: 'Modèle d\'annulation', value: { selected: 'Acompte conservé par la partie victime' } },
        { group: 'Annulation et report', clause: 'Report d\'un commun accord' },
        { group: 'Force majeure', clause: 'Événements couverts' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Résolution sans indemnité (acompte restitué)' } },
        { group: 'Résiliation', clause: 'Résiliation pour inexécution' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Droit applicable' },
        { group: 'Notifications', clause: 'Email de contact de l\'organisateur' },
        { group: 'Notifications', clause: 'Email de contact de l\'artiste / production' },
        { group: 'Clauses générales', clause: 'Intégralité de l\'accord' },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
        { group: 'Annexes', clause: 'Liste des annexes' },
      ],
    },
    {
      id: 'dj-set',
      icon: 'bi-vinyl',
      label: 'Prestation DJ',
      description: 'DJ set en club ou soirée : matériel de régie précisé, clauses musiciens retirées, SPRE incluse.',
      meta: 'Cachet fixe · Régie DJ · Musique enregistrée (SPRE)',
      badge: 'Débutant',
      level: 'easy',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Objet du contrat', clause: 'Type d\'évènement', value: { selected: 'DJ Set' } },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Contrat de prestation de service artistique' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'Prestation artistique', clause: 'Horaire de passage' },
        { group: 'Prestation artistique', clause: 'Interdiction de se faire remplacer' },
        { group: 'Rémunération', clause: 'Formule de rémunération', value: { selected: 'Cachet fixe' } },
        { group: 'Rémunération', clause: 'Montant du cachet / prix de cession (€ HT)' },
        { group: 'Rémunération', clause: 'Acompte' },
        { group: 'Rémunération', clause: 'Modalités et délai de paiement' },
        { group: 'Rémunération', clause: 'Régime de TVA', value: { selected: 'TVA 20 % (prestation de service)' } },
        { group: 'Défraiements et hospitalité', clause: 'Transport' },
        { group: 'Conditions techniques', clause: 'Matériel DJ / régie' },
        { group: 'Conditions techniques', clause: 'Sonorisation et éclairage fournis par', value: { selected: 'L\'Organisateur' } },
        { group: 'Conditions techniques', clause: 'Gardiennage du matériel' },
        { group: 'Captation, image et promotion', clause: 'Utilisation promotionnelle du nom et de l\'image' },
        { group: 'Obligations de l\'organisateur', clause: 'Déclaration et paiement SACEM' },
        { group: 'Obligations de l\'organisateur', clause: 'Rémunération équitable SPRE' },
        { group: 'Obligations de l\'organisateur', clause: 'Sécurité du public et service d\'ordre' },
        { group: 'Obligations de l\'organisateur', clause: 'Assurance responsabilité civile organisateur' },
        { group: 'Obligations de l\'artiste', clause: 'Ponctualité et présence' },
        { group: 'Obligations de l\'artiste', clause: 'Prestation conforme' },
        { group: 'Obligations de l\'artiste', clause: 'Matériel personnel et consommables' },
        { group: 'Annulation et report', clause: 'Modèle d\'annulation', value: { selected: 'Acompte conservé par la partie victime' } },
        { group: 'Force majeure', clause: 'Événements couverts' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Résolution sans indemnité (acompte restitué)' } },
        { group: 'Résiliation', clause: 'Résiliation pour inexécution' },
        { group: 'Notifications', clause: 'Email de contact de l\'organisateur' },
        { group: 'Notifications', clause: 'Email de contact de l\'artiste / production' },
        { group: 'Clauses générales', clause: 'Intégralité de l\'accord' },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
      ],
    },
    {
      id: 'festival',
      icon: 'bi-flag',
      label: 'Festival',
      description: 'Horaires stricts, accréditations, loges, plein air, clause de rayon.',
      meta: 'Multi-artistes · Accréditations · Clause de rayon',
      badge: 'Intermédiaire',
      level: 'medium',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Préambule', clause: 'Qualité d\'entrepreneur de spectacles des parties' },
        { group: 'Objet du contrat', clause: 'Type d\'évènement', value: { selected: 'Festival' } },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Contrat de cession du droit d\'exploitation d\'un spectacle' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'L\'évènement', clause: 'Jauge du lieu' },
        { group: 'L\'évènement', clause: 'Représentation en plein air' },
        { group: 'L\'évènement', clause: 'Accès, parking et logistique du site' },
        { group: 'Prestation artistique', clause: 'Horaire de passage' },
        { group: 'Prestation artistique', clause: 'Balances / Soundcheck' },
        { group: 'Prestation artistique', clause: 'Effectif et line-up' },
        { group: 'Prestation artistique', clause: 'Première partie / autres artistes' },
        { group: 'Prestation artistique', clause: 'Interdiction de se faire remplacer' },
        { group: 'Rémunération', clause: 'Formule de rémunération', value: { selected: 'Cachet fixe' } },
        { group: 'Rémunération', clause: 'Montant du cachet / prix de cession (€ HT)' },
        { group: 'Rémunération', clause: 'Acompte' },
        { group: 'Rémunération', clause: 'Modalités et délai de paiement' },
        { group: 'Rémunération', clause: 'Régime de TVA', value: { selected: 'TVA 5,5 % (cession de spectacle vivant)' } },
        { group: 'Défraiements et hospitalité', clause: 'Transport' },
        { group: 'Défraiements et hospitalité', clause: 'Hébergement' },
        { group: 'Défraiements et hospitalité', clause: 'Repas / catering' },
        { group: 'Défraiements et hospitalité', clause: 'Per diem' },
        { group: 'Conditions techniques', clause: 'Fiche technique annexée' },
        { group: 'Conditions techniques', clause: 'Sonorisation et éclairage fournis par', value: { selected: 'L\'Organisateur' } },
        { group: 'Conditions techniques', clause: 'Backline fourni' },
        { group: 'Conditions techniques', clause: 'Personnel technique du lieu' },
        { group: 'Conditions techniques', clause: 'Loges' },
        { group: 'Conditions techniques', clause: 'Accréditations / badges / pass' },
        { group: 'Conditions techniques', clause: 'Gardiennage du matériel' },
        { group: 'Captation, image et promotion', clause: 'Autorisation de captation' },
        { group: 'Captation, image et promotion', clause: 'Photographies' },
        { group: 'Captation, image et promotion', clause: 'Diffusion sur les réseaux sociaux' },
        { group: 'Captation, image et promotion', clause: 'Utilisation promotionnelle du nom et de l\'image' },
        { group: 'Merchandising', clause: 'Vente de merchandising autorisée' },
        { group: 'Merchandising', clause: 'Commission du lieu sur les ventes (%)' },
        { group: 'Obligations de l\'organisateur', clause: 'Déclaration et paiement SACEM' },
        { group: 'Obligations de l\'organisateur', clause: 'Rémunération équitable SPRE' },
        { group: 'Obligations de l\'organisateur', clause: 'Sécurité du public et service d\'ordre' },
        { group: 'Obligations de l\'organisateur', clause: 'Autorisations administratives' },
        { group: 'Obligations de l\'organisateur', clause: 'Assurance responsabilité civile organisateur' },
        { group: 'Obligations de l\'organisateur', clause: 'Limitation sonore et réglementation locale' },
        { group: 'Obligations de l\'artiste', clause: 'Ponctualité et présence' },
        { group: 'Obligations de l\'artiste', clause: 'Prestation conforme' },
        { group: 'Obligations de l\'artiste', clause: 'Assurance de l\'artiste' },
        { group: 'Obligations de l\'artiste', clause: 'Promotion de l\'évènement par l\'artiste' },
        { group: 'Annulation et report', clause: 'Modèle d\'annulation', value: { selected: 'Barème progressif selon la date d\'annulation' } },
        { group: 'Annulation et report', clause: 'Précisions sur l\'indemnité d\'annulation' },
        { group: 'Annulation et report', clause: 'Intempéries (plein air)' },
        { group: 'Force majeure', clause: 'Événements couverts' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Report à une date convenue' } },
        { group: 'Exclusivité territoriale (clause de rayon)', clause: 'Clause de rayon' },
        { group: 'Résiliation', clause: 'Résiliation pour inexécution' },
        { group: 'Résiliation', clause: 'Effets de la résiliation' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Droit applicable' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Médiation préalable obligatoire' },
        { group: 'Notifications', clause: 'Email de contact de l\'organisateur' },
        { group: 'Notifications', clause: 'Email de contact de l\'artiste / production' },
        { group: 'Notifications', clause: 'Modalités de notification' },
        { group: 'Clauses générales', clause: 'Intégralité de l\'accord' },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Divisibilité' },
        { group: 'Clauses générales', clause: 'Clause de non-renonciation' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
        { group: 'Annexes', clause: 'Liste des annexes' },
      ],
    },
    {
      id: 'showcase-promo',
      icon: 'bi-camera-video',
      label: 'Showcase promotionnel',
      description: 'Prestation courte à visée promo : captation, diffusion réseaux sociaux encadrée.',
      meta: 'Captation · Réseaux sociaux · Usage promotionnel',
      badge: 'Intermédiaire',
      level: 'medium',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Objet du contrat', clause: 'Type d\'évènement', value: { selected: 'Showcase promotionnel' } },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Contrat de prestation de service artistique' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'Prestation artistique', clause: 'Horaire de passage' },
        { group: 'Prestation artistique', clause: 'Balances / Soundcheck' },
        { group: 'Rémunération', clause: 'Formule de rémunération', value: { selected: 'Cachet fixe' } },
        { group: 'Rémunération', clause: 'Montant du cachet / prix de cession (€ HT)' },
        { group: 'Rémunération', clause: 'Modalités et délai de paiement' },
        { group: 'Conditions techniques', clause: 'Sonorisation et éclairage fournis par', value: { selected: 'L\'Organisateur' } },
        { group: 'Captation, image et promotion', clause: 'Autorisation de captation' },
        { group: 'Captation, image et promotion', clause: 'Photographies' },
        { group: 'Captation, image et promotion', clause: 'Diffusion sur les réseaux sociaux' },
        { group: 'Captation, image et promotion', clause: 'Utilisation promotionnelle du nom et de l\'image' },
        { group: 'Captation, image et promotion', clause: 'Mention et crédit obligatoires' },
        { group: 'Obligations de l\'organisateur', clause: 'Déclaration et paiement SACEM' },
        { group: 'Obligations de l\'organisateur', clause: 'Sécurité du public et service d\'ordre' },
        { group: 'Obligations de l\'organisateur', clause: 'Assurance responsabilité civile organisateur' },
        { group: 'Obligations de l\'artiste', clause: 'Ponctualité et présence' },
        { group: 'Obligations de l\'artiste', clause: 'Prestation conforme' },
        { group: 'Obligations de l\'artiste', clause: 'Promotion de l\'évènement par l\'artiste' },
        { group: 'Annulation et report', clause: 'Modèle d\'annulation', value: { selected: 'Annulation simple (restitution de l\'acompte, pas d\'indemnité)' } },
        { group: 'Force majeure', clause: 'Événements couverts' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Résolution sans indemnité (acompte restitué)' } },
        { group: 'Notifications', clause: 'Email de contact de l\'organisateur' },
        { group: 'Notifications', clause: 'Email de contact de l\'artiste / production' },
        { group: 'Clauses générales', clause: 'Intégralité de l\'accord' },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
      ],
    },
    {
      id: 'evenement-prive',
      icon: 'bi-incognito',
      label: 'Évènement privé',
      description: 'Mariage, soirée privée ou d\'entreprise : confidentialité, droit à l\'image des invités.',
      meta: 'Confidentialité · Droit à l\'image · Diffusion restreinte',
      badge: 'Intermédiaire',
      level: 'medium',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Objet du contrat', clause: 'Type d\'évènement', value: { selected: 'Évènement privé' } },
        { group: 'Objet du contrat', clause: 'Nature juridique', value: { selected: 'Contrat de prestation de service artistique' } },
        { group: 'Objet du contrat', clause: 'Finalité et description' },
        { group: 'L\'évènement', clause: 'Accès, parking et logistique du site' },
        { group: 'Prestation artistique', clause: 'Horaire de passage' },
        { group: 'Prestation artistique', clause: 'Interdiction de se faire remplacer' },
        { group: 'Rémunération', clause: 'Formule de rémunération', value: { selected: 'Cachet fixe' } },
        { group: 'Rémunération', clause: 'Montant du cachet / prix de cession (€ HT)' },
        { group: 'Rémunération', clause: 'Acompte' },
        { group: 'Rémunération', clause: 'Modalités et délai de paiement' },
        { group: 'Rémunération', clause: 'Régime de TVA', value: { selected: 'TVA 20 % (prestation de service)' } },
        { group: 'Défraiements et hospitalité', clause: 'Transport' },
        { group: 'Défraiements et hospitalité', clause: 'Repas / catering' },
        { group: 'Conditions techniques', clause: 'Sonorisation et éclairage fournis par', value: { selected: 'L\'Artiste' } },
        { group: 'Conditions techniques', clause: 'Gardiennage du matériel' },
        { group: 'Captation, image et promotion', clause: 'Droit à l\'image des invités (évènement privé)' },
        { group: 'Confidentialité', clause: 'Confidentialité des conditions financières' },
        { group: 'Confidentialité', clause: 'Confidentialité de l\'évènement (évènement privé)' },
        { group: 'Obligations de l\'organisateur', clause: 'Déclaration et paiement SACEM' },
        { group: 'Obligations de l\'organisateur', clause: 'Assurance responsabilité civile organisateur' },
        { group: 'Obligations de l\'artiste', clause: 'Ponctualité et présence' },
        { group: 'Obligations de l\'artiste', clause: 'Prestation conforme' },
        { group: 'Obligations de l\'artiste', clause: 'Sobriété et comportement' },
        { group: 'Obligations de l\'artiste', clause: 'Assurance de l\'artiste' },
        { group: 'Annulation et report', clause: 'Modèle d\'annulation', value: { selected: 'Acompte conservé par la partie victime' } },
        { group: 'Force majeure', clause: 'Événements couverts' },
        { group: 'Force majeure', clause: 'Effets de la force majeure', value: { selected: 'Résolution sans indemnité (acompte restitué)' } },
        { group: 'Résiliation', clause: 'Résiliation pour inexécution' },
        { group: 'Notifications', clause: 'Email de contact de l\'organisateur' },
        { group: 'Notifications', clause: 'Email de contact de l\'artiste / production' },
        { group: 'Clauses générales', clause: 'Intégralité de l\'accord' },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
      ],
    },
  ],

  quickStartClauses: [
    {
      group: 'Préambule', clause: 'Contexte et volonté des parties', field: 'text',
      value:
        "[Contractant 2], en qualité de [Rôle 2], ci-après dénommé(e) « l'Organisateur », organise " +
        "l'évènement [l'Évènement] le [date de l'évènement] au [lieu]. " +
        "[Contractant 1], en qualité de [Rôle 1], ci-après dénommé(e) « l'Artiste », dispose du répertoire " +
        "et des moyens artistiques nécessaires à la représentation objet du présent contrat. " +
        "Les parties, agissant chacune en qualité d'entrepreneur indépendant, ont convenu de formaliser " +
        "les conditions de la représentation publique dans les stipulations qui suivent, dont elles " +
        "déclarent accepter les termes sans réserve.",
    },
    {
      group: 'Objet du contrat', clause: 'Finalité et description', field: 'text',
      value:
        "Le présent contrat a pour objet de définir les conditions dans lesquelles [Contractant 1], en qualité de " +
        "[Rôle 1], s'engage à assurer la représentation publique de sa prestation musicale dans le cadre de " +
        "[l'Évènement], organisé par [Contractant 2] le [date de l'évènement] au [lieu], [adresse du lieu]. " +
        "La prestation, d'une durée d'environ [durée de la prestation], sera exécutée dans les conditions " +
        "artistiques, techniques et financières définies aux articles suivants.",
    },
    {
      group: 'Prestation artistique', clause: 'Balances / Soundcheck', field: 'details',
      value:
        "L'Organisateur garantit à [Contractant 1] un accès au plateau pour les balances le [date de l'évènement] " +
        "à [heure de balance], pour une durée minimale d'une heure en présence du régisseur son et lumière du lieu. " +
        "Le système de diffusion sera opérationnel et conforme à la fiche technique annexée.",
    },
    {
      group: 'Rémunération', clause: 'Modalités et délai de paiement', field: 'text',
      value:
        "Le règlement du cachet de [cachet] interviendra par virement bancaire sur le compte de [Contractant 1] " +
        "au plus tard le jour de la Représentation, sur présentation d'une facture conforme. Tout retard de paiement " +
        "entraînera de plein droit l'application de pénalités au taux de trois fois le taux d'intérêt légal, ainsi que " +
        "l'indemnité forfaitaire de recouvrement de 40 € prévue à l'article D441-5 du Code de commerce.",
    },
    {
      group: 'Captation, image et promotion', clause: 'Utilisation promotionnelle du nom et de l\'image', field: 'details',
      value:
        "[Contractant 1] autorise l'Organisateur à utiliser son nom de scène, son image et sa biographie aux seules " +
        "fins d'annonce et de promotion de [l'Évènement], sur tous supports, jusqu'à la date de la Représentation. " +
        "L'Organisateur s'engage à utiliser exclusivement les visuels et éléments fournis par [Contractant 1].",
    },
    {
      group: 'Annulation et report', clause: 'Précisions sur l\'indemnité d\'annulation', field: 'text',
      value:
        "En cas d'annulation du fait de l'Organisateur : plus de 60 jours avant la Représentation, l'acompte de [acompte] " +
        "reste acquis à [Contractant 1] ; entre 60 et 30 jours, 50 % du cachet est dû ; moins de 30 jours avant la date, " +
        "le cachet de [cachet] est intégralement dû. En cas d'annulation du fait de [Contractant 1] hors force majeure, " +
        "celui-ci/celle-ci restituera l'acompte perçu et remboursera à l'Organisateur les frais engagés, " +
        "sur présentation de justificatifs.",
    },
    {
      group: 'Force majeure', clause: 'Événements couverts', field: 'text',
      value:
        "Constituent notamment des cas de force majeure, sous réserve des conditions de l'article 1218 du Code civil : " +
        "catastrophe naturelle, incendie du lieu, interdiction administrative de l'évènement, deuil national, épidémie " +
        "entraînant des restrictions de rassemblement, grève générale des transports rendant l'accès impossible. " +
        "Ne constituent pas des cas de force majeure : l'insuffisance des ventes, les difficultés financières d'une " +
        "partie, ou les intempéries pour un évènement en plein air.",
    },
  ],

  quickStartToggles: [
    'Préambule||Contexte et volonté des parties',
    'Prestation artistique||Interdiction de se faire remplacer',
    'Conditions techniques||Fiche technique annexée',
    'Obligations de l\'organisateur||Déclaration et paiement SACEM',
    'Obligations de l\'organisateur||Sécurité du public et service d\'ordre',
    'Obligations de l\'organisateur||Autorisations administratives',
    'Obligations de l\'organisateur||Assurance responsabilité civile organisateur',
    'Obligations de l\'artiste||Ponctualité et présence',
    'Obligations de l\'artiste||Prestation conforme',
    'Résiliation||Résiliation pour inexécution',
    'Clauses générales||Intégralité de l\'accord',
    'Clauses générales||Modification écrite',
    'Clauses générales||Indépendance des parties',
  ],
};

// ═══════════════════════════════════════════════════════════════════════════════
// MANAGEMENT — mandat de management artistique (add-on optionnel sur un lien roster)
// ═══════════════════════════════════════════════════════════════════════════════

const MANAGEMENT_CONFIG: ContractTypeConfig = {
  type: 'management',
  label: 'Contrat de management',
  firstPartyBadge: 'Contractant 1 — Manager / Producteur',
  rolePlaceholder: 'ex : Manager, Artiste, Structure de management…',
  keyBrackets: ['[début du mandat]'],
  keyInfoHint: 'Pour activer le pré-remplissage, renseignez le nom des deux parties et la date de début du mandat.',
  quickStartDescription: "Pré-remplissez les clauses essentielles d'un mandat de management à partir de vos champs automatiques.",
  guideNote: "Ce module génère un mandat de management (conseil, stratégie, mise en réseau) entre entrepreneurs indépendants, régi par le droit commun du mandat (art. 1984 et s. du Code civil). Il ne remplace pas un contrat d'agent artistique, activité réglementée nécessitant une licence : en cas de doute sur votre activité réelle, consultez un avocat spécialisé.",

  introSections: [
    {
      title: 'Le mandat',
      icon: 'bi-briefcase',
      fields: [
        { id: 'mandateStart', label: 'Début du mandat', placeholder: 'ex : 01/09/2026', inputType: 'text', bracket: '[début du mandat]', wide: true },
        { id: 'mandateDuration', label: 'Durée initiale', placeholder: 'ex : 12 mois', inputType: 'text', bracket: '[durée du mandat]' },
        { id: 'mandateScope', label: 'Nature du mandat', inputType: 'select', options: ['Mandat non-exclusif', 'Mandat exclusif'], bracket: '[nature du mandat]' },
      ],
    },
    {
      title: 'Clés financières',
      icon: 'bi-percent',
      fields: [
        { id: 'commissionRate', label: 'Taux de commission (%)', placeholder: 'ex : 15', inputType: 'number', bracket: '[taux de commission]', suffix: '%', min: 0, max: 50 },
      ],
    },
  ],

  legalWarning: {
    title: 'Management ≠ agent artistique',
    text: "Ce module produit un mandat de conseil et de développement de carrière entre entrepreneurs indépendants (art. 1984 et s. du Code civil). "
        + "Si votre rôle consiste, à titre habituel et contre rémunération, à négocier et conclure des contrats d'engagement de spectacles pour le compte de l'Artiste, "
        + "vous exercez une activité d'AGENT ARTISTIQUE réglementée, qui nécessite une licence spécifique et dont la commission est plafonnée par la réglementation "
        + "(art. L.7121-9 et s. du Code du travail, régime issu de la loi n° 2011-893 du 26 juillet 2011). Ce générateur n'est pas adapté à cette activité — consultez un avocat spécialisé.",
  },

  presets: [
    {
      id: 'mandat-simple',
      icon: 'bi-handshake',
      label: 'Mandat simple non-exclusif',
      description: 'Conseil et mise en réseau, sans exclusivité, pour tester la collaboration.',
      meta: '6 mois · Non-exclusif · Commission 15 %',
      badge: 'Débutant',
      level: 'easy',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Objet du mandat', clause: 'Nature du mandat', value: { selected: 'Mandat non-exclusif' } },
        { group: 'Objet du mandat', clause: 'Périmètre du mandat', value: { selected: ['Conseil et stratégie de carrière', 'Mise en réseau (labels, médias, partenaires)'] } },
        { group: 'Objet du mandat', clause: "Limite de l'activité d'agent artistique" },
        { group: 'Objet du mandat', clause: 'Finalité et description' },
        { group: 'Durée et renouvellement', clause: 'Durée initiale', value: { amount: 6, unit: 'mois' } },
        { group: 'Durée et renouvellement', clause: 'Date de prise d\'effet' },
        { group: 'Commission', clause: 'Taux de commission (%)', value: { number: 15 } },
        { group: 'Commission', clause: 'Assiette de la commission', value: { selected: 'Revenus nets (après frais de production/promotion)' } },
        { group: 'Commission', clause: 'Modalités de reversement' },
        { group: 'Obligations du Manager', clause: 'Compte-rendu périodique', value: { selected: 'Mensuel' } },
        { group: 'Obligations du Manager', clause: 'Transparence sur les opportunités reçues' },
        { group: "Obligations de l'Artiste", clause: 'Disponibilité et bonne foi' },
        { group: 'Révocation et résiliation', clause: 'Résiliation pour inexécution' },
        { group: 'Confidentialité', clause: 'Clause de confidentialité' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Droit applicable' },
        { group: 'Notifications', clause: 'Email de contact du Manager' },
        { group: 'Notifications', clause: "Email de contact de l'Artiste" },
        { group: 'Clauses générales', clause: "Intégralité de l'accord" },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
        { group: 'Annexes', clause: 'Liste des annexes' },
      ],
    },
    {
      id: 'mandat-exclusif',
      icon: 'bi-shield-check',
      label: 'Mandat exclusif structuré',
      description: 'Exclusivité, commission structurée, clause de survie et non-sollicitation.',
      meta: '12 mois · Exclusif France · Commission 20 %',
      badge: 'Intermédiaire',
      level: 'medium',
      clauses: [
        { group: 'Préambule', clause: 'Contexte et volonté des parties' },
        { group: 'Préambule', clause: "Qualité d'indépendant des parties" },
        { group: 'Objet du mandat', clause: 'Nature du mandat', value: { selected: 'Mandat exclusif' } },
        { group: 'Objet du mandat', clause: 'Périmètre du mandat', value: { selected: ['Conseil et stratégie de carrière', 'Développement artistique', 'Mise en réseau (labels, médias, partenaires)', 'Coordination administrative', 'Supervision de la promotion et de la communication'] } },
        { group: 'Objet du mandat', clause: "Limite de l'activité d'agent artistique" },
        { group: 'Objet du mandat', clause: 'Finalité et description' },
        { group: 'Durée et renouvellement', clause: 'Durée initiale', value: { amount: 12, unit: 'mois' } },
        { group: 'Durée et renouvellement', clause: 'Date de prise d\'effet' },
        { group: 'Durée et renouvellement', clause: 'Renouvellement tacite' },
        { group: 'Durée et renouvellement', clause: 'Préavis de non-reconduction' },
        { group: 'Commission', clause: 'Taux de commission (%)', value: { number: 20 } },
        { group: 'Commission', clause: 'Assiette de la commission', value: { selected: 'Revenus nets de commissions tierces (label, distributeur, agent booking)' } },
        { group: 'Commission', clause: 'Revenus inclus dans l\'assiette', value: { selected: ['Cachets de concert', 'Royalties d\'exploitation (streaming, ventes)', 'Synchronisations', 'Partenariats et sponsoring'] } },
        { group: 'Commission', clause: 'Modalités de reversement' },
        { group: 'Commission', clause: 'Facturation de la commission' },
        { group: 'Exclusivité territoriale', clause: 'Territoire du mandat', value: { territory: 'France' } },
        { group: 'Exclusivité territoriale', clause: "Exceptions à l'exclusivité" },
        { group: 'Obligations du Manager', clause: 'Compte-rendu périodique', value: { selected: 'Trimestriel' } },
        { group: 'Obligations du Manager', clause: 'Transparence sur les opportunités reçues' },
        { group: "Obligations de l'Artiste", clause: 'Disponibilité et bonne foi' },
        { group: "Obligations de l'Artiste", clause: 'Communication des opportunités reçues directement' },
        { group: "Obligations de l'Artiste", clause: "Respect de l'exclusivité" },
        { group: 'Révocation et résiliation', clause: 'Résiliation pour inexécution' },
        { group: 'Révocation et résiliation', clause: 'Révocation ad nutum du mandat' },
        { group: 'Révocation et résiliation', clause: 'Clause de survie post-résiliation (affaires en cours)' },
        { group: 'Révocation et résiliation', clause: 'Clause de non-sollicitation' },
        { group: 'Confidentialité', clause: 'Clause de confidentialité' },
        { group: 'Confidentialité', clause: 'Durée de confidentialité post-résiliation (années)' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Droit applicable' },
        { group: 'Droit applicable et juridiction compétente', clause: 'Médiation préalable obligatoire' },
        { group: 'Notifications', clause: 'Email de contact du Manager' },
        { group: 'Notifications', clause: "Email de contact de l'Artiste" },
        { group: 'Clauses générales', clause: "Intégralité de l'accord" },
        { group: 'Clauses générales', clause: 'Modification écrite' },
        { group: 'Clauses générales', clause: 'Divisibilité' },
        { group: 'Clauses générales', clause: 'Indépendance des parties' },
        { group: 'Annexes', clause: 'Liste des annexes' },
      ],
    },
  ],

  quickStartClauses: [
    {
      group: 'Préambule', clause: 'Contexte et volonté des parties', field: 'text',
      value:
        "[Contractant 1], ci-après dénommé(e) « le Manager », et [Contractant 2], ci-après dénommé(e) " +
        "« l'Artiste », collaborent depuis [début du mandat] au développement du projet artistique de " +
        "l'Artiste. Les parties, agissant chacune en qualité d'entrepreneur indépendant, ont convenu de " +
        "formaliser les conditions de cette collaboration dans les stipulations qui suivent, dont elles " +
        "déclarent accepter les termes sans réserve.",
    },
    {
      group: 'Objet du mandat', clause: 'Finalité et description', field: 'text',
      value:
        "Le présent contrat a pour objet de définir les conditions dans lesquelles [Contractant 2] confie à " +
        "[Contractant 1] un [nature du mandat] de management, en vue du développement de sa carrière " +
        "artistique, à compter du [début du mandat] et pour une durée initiale de [durée du mandat].",
    },
    {
      group: 'Objet du mandat', clause: "Limite de l'activité d'agent artistique", field: 'details',
      value:
        "Les parties reconnaissent expressément que le présent mandat porte sur des missions de conseil, de " +
        "stratégie de carrière, de développement artistique et de coordination, à l'exclusion de toute " +
        "activité de mise en rapport habituelle et rémunérée de l'Artiste avec des entrepreneurs de " +
        "spectacles vivants en vue de la conclusion de contrats d'engagement, laquelle relève du régime " +
        "réglementé de l'agent artistique (art. L.7121-9 et s. du Code du travail) et suppose une licence " +
        "que le Manager ne détient pas dans le cadre du présent contrat.",
    },
    {
      group: 'Commission', clause: 'Modalités de reversement', field: 'text',
      value:
        "[Contractant 2] encaisse directement l'ensemble des revenus visés à l'article « Revenus inclus dans " +
        "l'assiette » et reverse à [Contractant 1] la commission de [taux de commission] due dans un délai de " +
        "[nombre] jours suivant leur encaissement effectif, accompagnée d'un relevé détaillant l'origine de " +
        "chaque somme.",
    },
    {
      group: 'Révocation et résiliation', clause: 'Clause de survie post-résiliation (affaires en cours)', field: 'details',
      value:
        "Pour les affaires dont les négociations ont été engagées par [Contractant 1] avant la date de fin du " +
        "présent mandat et qui aboutissent dans les [nombre] mois suivant cette date, la commission prévue à " +
        "l'article « Commission » reste due à [Contractant 1] dans les conditions habituelles.",
    },
  ],

  quickStartToggles: [
    'Préambule||Contexte et volonté des parties',
    "Objet du mandat||Limite de l'activité d'agent artistique",
    'Confidentialité||Clause de confidentialité',
    'Clauses générales||Intégralité de l\'accord',
    'Clauses générales||Modification écrite',
    'Clauses générales||Indépendance des parties',
  ],
};

// ── Export ────────────────────────────────────────────────────────────────────

export const CONTRACT_TYPE_CONFIGS: Record<ContractType, ContractTypeConfig> = {
  exploitation: EXPLOITATION_CONFIG,
  performance:  PERFORMANCE_CONFIG,
  management:   MANAGEMENT_CONFIG,
};
