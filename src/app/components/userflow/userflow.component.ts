import { ChangeDetectorRef, Component, HostListener, OnDestroy, inject } from '@angular/core';
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
  private cdr = inject(ChangeDetectorRef);

  isOpen        = false;
  hasEverOpened = localStorage.getItem(LS_KEY) === '1';
  openIndex: number | null = null;

  open(): void {
    this.isOpen = true;
    if (!this.hasEverOpened) {
      this.hasEverOpened = true;
      localStorage.setItem(LS_KEY, '1');
    }
    document.body.style.overflow = 'hidden';
    this.cdr.detectChanges();
  }

  close(): void {
    this.isOpen = false;
    document.body.style.overflow = '';
    this.cdr.detectChanges();
  }

  onBackdropClick(event: MouseEvent): void {
    if (event.target === event.currentTarget) {
      this.close();
    }
  }

  toggle(i: number): void {
    this.openIndex = this.openIndex === i ? null : i;
    this.cdr.detectChanges();
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.isOpen) this.close();
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
        { text: 'Parcourez les ingénieurs disponibles, écoutez leurs previews et comparez les profils.' },
        { text: 'Sélectionnez les services (mixage, mastering, arrangement) et personnalisez la commande.' },
        { text: 'Payez en ligne — les fonds sont bloqués jusqu\'à la livraison et validation.' },
        { text: 'Envoyez ses fichiers séparés (stems / pistes). Validez ou demandez des retouches depuis son espace.' },
      ],
      cta: { label: 'Voir les ingénieurs', link: '/mixmaster/engineers' },
    },
    {
      icon: 'bi-sliders2',
      color: 'orange',
      title: 'Vendre ses services Mix / Master',
      tagline: 'Monétisez votre expertise audio. Recevez des commandes, livrez, encaissez.',
      steps: [
        { text: 'Activez le rôle « Mix / Master Engineer » et soumettez un exemple pour être certifié depuis ', link: '/edit-profile', linkLabel: 'Modifier le profil' },
        { text: 'Définissez votre prix de référence et votre prix minimum (négociation automatique avec les clients).' },
        { text: 'Recevez des commandes, traitez les fichiers dans votre DAW, et livrez depuis le dashboard.' },
        { text: 'LaProd+ Pro débloque le mastering certifié et un badge doré visible par les clients.', link: '/premium', linkLabel: 'LaProd+ Pro' },
      ],
      cta: { label: 'Devenir ingénieur', link: '/edit-profile' },
    },
    {
      icon: 'bi-file-earmark-text-fill',
      color: 'pink',
      title: 'Contrats pro — protégez tout le monde',
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
      tagline: 'Autotune en ligne, gratuit, sans logiciel à installer.',
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
      title: 'Recommandations sur-mesure',
      tagline: 'Plus vous utilisez LaProd, plus les suggestions vous ressemblent.',
      steps: [
        { text: 'LaProd apprend de vos habitudes — écoutes, achats, toplines — pour affiner continuellement ce qu\'il vous propose.' },
        { text: 'Les suggestions vont bien au-delà du genre musical : chaque interaction contribue à un profil unique qui évolue avec vous.' },
        { text: 'Dès votre inscription, vos rôles et préférences servent de point de départ. Pas besoin d\'historique pour commencer à découvrir.' },
        { text: 'Les beatmakers émergents ont autant de chances d\'être mis en avant que les plus populaires — la pertinence prime sur la notoriété.' },
      ],
      cta: { label: 'Explorer la bibliothèque', link: '/' },
    },
  ];
}
