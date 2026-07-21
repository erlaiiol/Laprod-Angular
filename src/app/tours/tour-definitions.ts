/**
 * Contenu des visites guidées. Purement déclaratif : aucune logique ici.
 *
 * `anchor` doit correspondre à un `lpTourAnchor="…"` posé dans le template de la page.
 * Une étape dont l'ancre n'est pas présente à l'écran est automatiquement ignorée
 * (voir TourService.start) — on peut donc décrire des étapes qui ne concernent
 * qu'un rôle, un état premium ou une largeur d'écran donnés.
 */

export type TourId = 'home' | 'upload-track' | 'contract-builder' | 'planning';

export type TourPlacement = 'top' | 'bottom' | 'left' | 'right';

export interface TourStep {
  /** Identifiant de l'élément ciblé, posé via [lpTourAnchor]. */
  anchor: string;
  title: string;
  text: string;
  /** Côté préféré pour la bulle. L'overlay bascule tout seul s'il manque de place. */
  placement?: TourPlacement;
}

export interface TourDef {
  id: TourId;
  /** Titre affiché dans la bulle d'accueil et dans le panneau Guide. */
  label: string;
  steps: TourStep[];
}

export const TOURS: Record<TourId, TourDef> = {

  // ── Accueil : comprendre les menus, le profil et les rôles ──────────────────
  home: {
    id: 'home',
    label: "Découvrir LaProd",
    steps: [
      {
        anchor: 'home-filters',
        title: 'Trouvez le bon son',
        text: "Filtrez le catalogue par style, BPM ou tonalité. C'est le point de départ : tout le reste de LaProd part d'un morceau.",
        placement: 'bottom',
      },
      {
        anchor: 'home-layout',
        title: "Trois façons d'afficher",
        text: "Liste, galerie ou vue compacte. La vue compacte est pensée pour le mobile — changez-en à tout moment, votre choix est mémorisé.",
        placement: 'bottom',
      },
      {
        anchor: 'nav-menu',
        title: 'Vos espaces',
        text: "Beats, Mix & Master et Contrats : chaque menu ouvre un espace complet. Ce que vous y voyez dépend des rôles activés sur votre profil.",
        placement: 'bottom',
      },
      {
        anchor: 'nav-profile',
        title: 'Profil et rôles',
        text: "C'est ici que vous vous déclarez artiste, beatmaker ou ingénieur. Chaque rôle activé débloque son propre tableau de bord et ses fonctionnalités.",
        placement: 'bottom',
      },
      {
        anchor: 'fab-guide',
        title: 'Le guide reste à portée',
        text: "Ce bouton rouvre le guide complet à tout moment, et vous pouvez y relancer n'importe quelle visite guidée.",
        placement: 'left',
      },
    ],
  },

  // ── Upload : mettre un beat en vente ───────────────────────────────────────
  'upload-track': {
    id: 'upload-track',
    label: 'Mettre un beat en vente',
    steps: [
      {
        anchor: 'upload-infos',
        title: 'Les métadonnées comptent',
        text: "Titre, BPM, tonalité, style : ce sont ces champs que l'algorithme utilise pour proposer votre beat aux bons artistes. Plus ils sont précis, plus vous êtes visible.",
        placement: 'bottom',
      },
      {
        anchor: 'upload-prices',
        title: 'Vos prix, vos droits',
        text: "Vous fixez un prix par format — MP3, WAV, Stems. Chaque format correspond à un niveau de droits différent, et génère automatiquement son contrat de licence.",
        placement: 'top',
      },
      {
        anchor: 'upload-preview',
        title: "Ce que voit l'acheteur",
        text: "Un aperçu en direct de votre fiche telle qu'elle apparaîtra dans le catalogue. Utile pour vérifier avant de publier.",
        placement: 'left',
      },
      {
        anchor: 'upload-files',
        title: 'Les fichiers audio',
        text: "Déposez le MP3, le WAV ou l'archive de stems. La preview diffusée publiquement est protégée : le fichier original n'est jamais exposé.",
        placement: 'top',
      },
      {
        anchor: 'upload-legal',
        title: 'Les attestations',
        text: "Vous certifiez que le beat est bien le vôtre. C'est ce qui protège votre vente et sécurise l'acheteur en cas de litige.",
        placement: 'top',
      },
    ],
  },

  // ── Contract builder : fabriquer un contrat sans être juriste ──────────────
  'contract-builder': {
    id: 'contract-builder',
    label: 'Fabriquer un contrat',
    steps: [
      {
        anchor: 'cb-intro',
        title: 'Commencez par vos infos',
        text: "Renseignez ici les parties et les informations clés — une seule fois. C'est la seule étape vraiment obligatoire avant de générer un contrat.",
        placement: 'bottom',
      },
      {
        anchor: 'cb-autofields',
        title: 'Les champs automatiques',
        text: "Tout ce que vous saisissez ci-dessus devient un champ réutilisable. Quand une clause contient [Contractant 1], votre nom s'y recopie tout seul : vous ne le tapez jamais deux fois.",
        placement: 'top',
      },
      {
        anchor: 'cb-quickstart',
        title: "Vous n'écrivez pas le juridique",
        text: "Le pré-remplissage active les clauses essentielles, et la rédaction type y insère le texte juridique standard. Vous partez d'un contrat complet, pas d'une page blanche.",
        placement: 'left',
      },
      {
        anchor: 'cb-progress',
        title: 'Suivez votre avancement',
        text: "L'anneau indique la part de clauses réellement complétées. Chaque article passe au vert une fois rempli — vous savez toujours ce qu'il reste à faire.",
        placement: 'right',
      },
      {
        anchor: 'cb-preview',
        title: 'Relisez avant de signer',
        text: "La prévisualisation affiche le contrat tel qu'il sera généré. Une fois le PDF produit, le contrat est finalisé et ne peut plus être modifié.",
        placement: 'bottom',
      },
    ],
  },

  // ── Rétroplanning : agenda partagé producteur ↔ artiste ────────────────────
  planning: {
    id: 'planning',
    label: 'Le planning partagé',
    steps: [
      {
        anchor: 'planning-toolbar',
        title: 'Un planning à deux',
        text: "Chaque événement est rattaché à l'un de tes liens roster — producteur ou artiste, peu importe qui l'a créé. Les deux côtés voient exactement la même chose.",
        placement: 'bottom',
      },
      {
        anchor: 'planning-ical',
        title: 'Dans ton agenda, pas seulement ici',
        text: "Abonne ton Apple ou Google Calendar à ce flux : les événements confirmés apparaissent directement dans ton agenda perso, sans revenir sur LaProd.",
        placement: 'bottom',
      },
      {
        anchor: 'planning-agenda',
        title: 'Proposé, puis confirmé',
        text: "Un événement créé par l'autre partie reste \"proposé\" tant que tu ne l'as pas confirmé. Rien ne s'impose sans l'accord des deux côtés du lien.",
        placement: 'top',
      },
    ],
  },
};
