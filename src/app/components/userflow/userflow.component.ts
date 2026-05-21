import { Component, HostListener, OnDestroy, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

interface FlowStep {
  text: string;
  link?: string;
  linkLabel?: string;
}

interface Flow {
  icon: string;
  color: 'violet' | 'green' | 'cyan' | 'orange' | 'pink' | 'indigo' | 'teal';
  title: string;
  tagline: string;
  steps: FlowStep[];
  cta: { label: string; link: string };
}

const LS_KEY = 'laprod_guide_opened';

@Component({
  selector: 'app-userflow',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './userflow.component.html',
  styleUrl: './userflow.component.scss',
})
export class UserflowComponent implements OnDestroy {

  isOpen         = signal(false);
  hasEverOpened  = signal(localStorage.getItem(LS_KEY) === '1');
  openIndex      = signal<number | null>(null);

  open(): void {
    this.isOpen.set(true);
    if (!this.hasEverOpened()) {
      this.hasEverOpened.set(true);
      localStorage.setItem(LS_KEY, '1');
    }
    document.body.style.overflow = 'hidden';
  }

  close(): void {
    this.isOpen.set(false);
    document.body.style.overflow = '';
  }

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.close();
    }
  }

  toggle(i: number): void {
    this.openIndex.update(cur => (cur === i ? null : i));
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.isOpen()) this.close();
  }

  ngOnDestroy(): void {
    document.body.style.overflow = '';
  }

  readonly flows: Flow[] = [
    {
      icon: 'bi-person-badge-fill',
      color: 'violet',
      title: 'Créer son profil & choisir ses rôles',
      tagline: 'Artiste, beatmaker ou ingénieur — définissez qui vous êtes et débloquez vos espaces.',
      steps: [
        { text: 'Compléter son profil (bio, photo, réseaux) depuis ', link: '/edit-profile', linkLabel: 'Modifier le profil' },
        { text: 'Activer les rôles qui vous correspondent — chaque rôle débloque un tableau de bord dédié.' },
        { text: 'Les tokens d\'upload et de topline s\'accumulent chaque jour et semaine. Multipliez-les avec ', link: '/premium', linkLabel: 'LaProd+' },
        { text: 'Les ingénieurs peuvent évoluer : certifications Mix, Producteur/Arrangeur et Master Engineer.' },
      ],
      cta: { label: 'Configurer mon profil', link: '/edit-profile' },
    },
    {
      icon: 'bi-cloud-arrow-up-fill',
      color: 'green',
      title: 'Uploader des tracks & les vendre',
      tagline: 'Mettez vos beats en ligne en quelques clics — contrats de licence générés automatiquement.',
      steps: [
        { text: 'Uploader une track avec ses métadonnées (BPM, gamme, tags) depuis ', link: '/upload-track', linkLabel: 'Upload' },
        { text: 'Définir les prix MP3 / WAV / Stems — un contrat de licence est créé automatiquement pour chaque format.' },
        { text: 'Les artistes parcourent la bibliothèque, écoutent via le player et achètent en 1 clic.' },
        { text: 'Modifier les informations ou les prix à tout moment depuis la gestion de vos tracks.' },
      ],
      cta: { label: 'Uploader une track', link: '/upload-track' },
    },
    {
      icon: 'bi-headphones',
      color: 'cyan',
      title: 'Acheter un service Mix / Master',
      tagline: 'Confiez votre son à des ingénieurs certifiés par LaProd.',
      steps: [
        { text: 'Parcourir les ingénieurs disponibles, écouter leurs previews et comparer les profils.' },
        { text: 'Sélectionner les services (mixage, mastering, arrangement) et personnaliser la commande.' },
        { text: 'Payer en ligne — les fonds sont bloqués en escrow jusqu\'à la livraison et validation.' },
        { text: 'Envoyer ses fichiers séparés (stems / pistes). Valider ou demander des retouches depuis son espace.' },
      ],
      cta: { label: 'Voir les ingénieurs', link: '/mixmaster/engineers' },
    },
    {
      icon: 'bi-sliders2',
      color: 'orange',
      title: 'Vendre ses services Mix / Master',
      tagline: 'Monétisez votre expertise audio. Recevez des commandes, livrez, encaissez.',
      steps: [
        { text: 'Activer le rôle « Mix / Master Engineer » et soumettre un exemple pour être certifié depuis ', link: '/edit-profile', linkLabel: 'Modifier le profil' },
        { text: 'Définir son prix de référence et son prix minimum (négociation automatique avec les clients).' },
        { text: 'Recevoir des commandes, traiter les fichiers dans son DAW, et livrer depuis son dashboard.' },
        { text: 'LaProd+ Pro débloque le mastering certifié et un badge doré visible par les clients.', link: '/premium', linkLabel: 'LaProd+ Pro' },
      ],
      cta: { label: 'Devenir ingénieur', link: '/edit-profile' },
    },
    {
      icon: 'bi-file-earmark-text-fill',
      color: 'pink',
      title: 'Contrats pro — protéger tout le monde',
      tagline: 'Créez ou analysez des contrats clairs pour éviter les arnaques et les litiges.',
      steps: [
        { text: 'Le Contract Builder génère un contrat complet : parties, droits cédés, royalties, exclusivité.', link: '/contract-builder', linkLabel: '' },
        { text: 'Le PDF est exportable et signable — disponible avec un abonnement LaProd+ Pro.' },
        { text: 'Reçu un contrat d\'un label ou d\'un beatmaker ? Collez-le dans le ', link: '/contract-analyzer', linkLabel: 'Contract Analyzer' },
        { text: 'L\'IA identifie les clauses abusives, les droits cédés et vous explique chaque article — disponible en Amateur+.' },
      ],
      cta: { label: 'Contract Builder', link: '/contract-builder' },
    },
    {
      icon: 'bi-mic-fill',
      color: 'indigo',
      title: 'Toplines — Écrire & chanter sur des beats',
      tagline: 'La killer feature : autotune en ligne, gratuit, sans logiciel à installer.',
      steps: [
        { text: 'Choisir un beat dans la bibliothèque — il se lance directement dans le player.' },
        { text: 'Ouvrir l\'éditeur Topline : enregistrez votre voix par-dessus le beat en temps réel.' },
        { text: 'Activer l\'autotune intégré — choisissez la gamme et le niveau de correction. Totalement gratuit.' },
        { text: 'Télécharger votre topline ou la partager. Les tokens se rechargent chaque semaine, davantage avec ', link: '/premium', linkLabel: 'LaProd+' },
      ],
      cta: { label: 'Explorer les beats', link: '/tracks' },
    },
    {
      icon: 'bi-stars',
      color: 'teal',
      title: 'Recommandations sur-mesure — pas des « artistes similaires »',
      tagline: 'L\'algorithme analyse vos goûts musicaux précis, pas juste votre genre préféré.',
      steps: [
        { text: 'Chaque écoute, achat et topline affine votre profil : BPM préférés, gammes, styles, densité rythmique, énergie — des paramètres que les autres plateformes ignorent.' },
        { text: 'L\'algorithme ne cherche pas « des artistes similaires à X » mais des morceaux dont les caractéristiques musicales objectives correspondent à ce que vous aimez vraiment.' },
        { text: 'Plus vous utilisez LaProd — écoutes, achats, toplines — plus les suggestions deviennent précises. Le cold start est minimal : vos rôles et tags configurés au profil servent de point de départ.' },
        { text: 'Les beatmakers sont mis en avant auprès des artistes dont le style colle à leur catalogue, et non selon leur popularité générale — chaque track a sa chance d\'être découverte.' },
      ],
      cta: { label: 'Découvrir mes recommandations', link: '/tracks' },
    },
  ];
}
