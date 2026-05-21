import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import {
  ContractBuilderService,
  ClauseGroupDTO, ClauseDTO, ContractParty, ContractValue,
  ContractDetail, ContractStatus,
} from '../../../services/contract-builder.service';
import { ToastService } from '../../../services/toast.service';
import { AuthService } from '../../../services/auth.service';
import { PremiumLockComponent } from '../../../components/premium-lock/premium-lock.component';

interface LocalValue {
  is_enabled: boolean;
  value: any;
}

interface PresetClauseSpec {
  group: string;
  clause: string;
  value?: any;
}

interface Preset {
  id: string;
  icon: string;
  label: string;
  description: string;
  meta: string;
  badge: string;
  level: 'easy' | 'medium' | 'expert';
  clauses: PresetClauseSpec[];
}

interface QuickStartSpec {
  group:  string;
  clause: string;
  field:  string;
  value:  string;
}

@Component({
  selector: 'app-builder-form',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, PremiumLockComponent],
  templateUrl: './builder-form.component.html',
  styleUrl: './builder-form.component.scss',
})
export class BuilderFormComponent implements OnInit {

  private auth   = inject(AuthService);
  readonly isPro = this.auth.isPro;

  // ── State ──────────────────────────────────────────────────────────────────
  loading    = signal(true);
  saving     = signal(false);
  generating = signal(false);

  contractId = signal(0);
  title      = signal('');
  status     = signal<ContractStatus>('draft');
  pdfFile    = signal<string | null>(null);

  groups  = signal<ClauseGroupDTO[]>([]);
  parties = signal<ContractParty[]>([]);

  // Map clause_id → LocalValue
  valuesMap = signal<Record<number, LocalValue>>({});

  activeGroup      = signal<number | null>(null);
  expandedTooltip  = signal<number | null>(null);
  expandedExample  = signal<number | null>(null);

  // ── Computed ────────────────────────────────────────────────────────────────
  activeGroupData = computed(() =>
    this.groups().find(g => g.id === this.activeGroup()) ?? null
  );

  isFinal      = computed(() => this.status() === 'final');
  hasPdf       = computed(() => !!this.pdfFile());
  showPreview   = signal(false);
  downloading   = signal(false);
  confirmReset  = signal(false);

  // ── Intro tab ──────────────────────────────────────────────────────────────
  showIntroTab   = signal(true);
  oeuvreTitle    = signal('');
  oeuvreIsrc     = signal('');
  oeuvreType     = signal<'chanson' | 'album' | 'instrumental' | 'autre'>('chanson');
  pctArtiste        = signal<number | null>(null);
  pctEditeur        = signal<number | null>(null);
  pctProducteur     = signal<number | null>(null);
  anneeCreation     = signal<number | null>(null);
  dureeOeuvre       = signal('');
  debutExploitation = signal('');
  finExploitation   = signal('');

  introVarMap = computed<Record<string, string>>(() => {
    const p  = this.parties();
    const p1 = p[0];
    const p2 = p[1];
    const nom = (party: ContractParty | undefined): string => {
      if (!party) return '';
      return party.party_type === 'physical'
        ? `${party.first_name ?? ''} ${party.last_name ?? ''}`.trim()
        : (party.company_name ?? '');
    };
    return {
      '[Contractant 1]':  nom(p1),
      '[Rôle 1]':         p1?.role ?? '',
      '[Contractant 2]':  nom(p2),
      '[Rôle 2]':         p2?.role ?? '',
      "[l'Œuvre]":        this.oeuvreTitle(),
      '[ISRC]':           this.oeuvreIsrc(),
      '[% Artiste]':              this.pctArtiste()       !== null ? `${this.pctArtiste()}%`    : '',
      '[% Éditeur]':              this.pctEditeur()       !== null ? `${this.pctEditeur()}%`    : '',
      '[% Producteur]':           this.pctProducteur()    !== null ? `${this.pctProducteur()}%` : '',
      '[année de création]':      this.anneeCreation()    !== null ? `${this.anneeCreation()}`  : '',
      "[durée de l'œuvre]":       this.dureeOeuvre(),
      "[début d'exploitation]":   this.debutExploitation(),
      "[fin d'exploitation]":     this.finExploitation(),
    };
  });

  introVarEntries  = computed(() =>
    Object.entries(this.introVarMap()).map(([key, value]) => ({ key, value }))
  );
  definedIntroVars = computed(() => this.introVarEntries().filter(e => !!e.value));
  hasAnyIntroVar   = computed(() => this.definedIntroVars().length > 0);

  // True when the 3 "essential" variables (both party names + title) are set
  hasKeyInfo = computed(() => {
    const m = this.introVarMap();
    return !!(m['[Contractant 1]'] && m['[Contractant 2]'] && m["[l'Œuvre]"]);
  });

  // True when at least one enabled clause carries text or details content
  hasAnyClauseText = computed(() =>
    Object.values(this.valuesMap()).some(lv => lv.is_enabled && !!(lv.value?.text || lv.value?.details))
  );

  activeGroupSummaries = computed(() =>
    this.groups()
      .filter(g => this.articleNumbers()[g.id] !== undefined)
      .map(g => ({ group: g, artNum: this.articleNumbers()[g.id] }))
  );

  // Article number per group — only groups with ≥1 enabled clause count
  articleNumbers = computed<Record<number, number>>(() => {
    const map: Record<number, number> = {};
    let n = 0;
    const vm = this.valuesMap();
    for (const group of this.groups()) {
      const active = group.clauses.some(c => {
        const lv = vm[c.id];
        return lv ? lv.is_enabled : c.is_enabled_by_default;
      });
      if (active) map[group.id] = ++n;
    }
    return map;
  });

  // Sub-paragraph number per clause — "artNum.subNum" for enabled/required clauses
  clauseNumbers = computed<Record<number, string>>(() => {
    const result: Record<number, string> = {};
    const artNums = this.articleNumbers();
    const vm = this.valuesMap();
    for (const group of this.groups()) {
      const artNum = artNums[group.id];
      if (!artNum) continue;
      let subN = 0;
      for (const clause of group.clauses) {
        const lv = vm[clause.id];
        const isEnabled = lv ? lv.is_enabled : clause.is_enabled_by_default;
        if (isEnabled || clause.is_required) {
          result[clause.id] = `${artNum}.${++subN}`;
        }
      }
    }
    return result;
  });

  // ── Presets ────────────────────────────────────────────────────────────────
  readonly presets: Preset[] = [
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
  ];

  constructor(
    private route:  ActivatedRoute,
    private router: Router,
    private svc:    ContractBuilderService,
    private toast:  ToastService,
  ) {}

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.contractId.set(id);
    this.loadAll(id);
  }

  // ── Load ───────────────────────────────────────────────────────────────────

  loadAll(id: number): void {
    this.loading.set(true);
    let templateDone = false;
    let contractDone = false;

    const tryFinish = () => {
      if (!templateDone || !contractDone) return;
      this.loading.set(false);
      this.activeGroup.set(0);
      this.showIntroTab.set(true);
    };

    this.svc.getTemplate().subscribe({
      next: res => {
        if (res.success && res.data) this.groups.set(res.data.groups);
        templateDone = true; tryFinish();
      },
      error: () => { templateDone = true; tryFinish(); },
    });

    this.svc.getContract(id).subscribe({
      next: res => {
        if (res.success && res.data) this.applyContract(res.data.contract);
        contractDone = true; tryFinish();
      },
      error: () => {
        contractDone = true; tryFinish();
        this.toast.showToast({ level: 'error', message: 'Contrat introuvable.' });
        this.router.navigate(['/contract-builder']);
      },
    });
  }

  applyContract(c: ContractDetail): void {
    this.title.set(c.title);
    this.status.set(c.status);
    this.pdfFile.set(c.pdf_file);
    this.parties.set(c.parties.length ? c.parties : []);
    const map: Record<number, LocalValue> = {};
    for (const v of c.values) {
      map[v.clause_id] = { is_enabled: v.is_enabled, value: v.value ?? null };
    }
    this.valuesMap.set(map);
  }

  // ── Value helpers ──────────────────────────────────────────────────────────

  getValue(clauseId: number, clause: ClauseDTO): LocalValue {
    const map = this.valuesMap();
    if (map[clauseId]) return map[clauseId];
    return {
      is_enabled: clause.is_enabled_by_default,
      value: clause.default_value ?? this.defaultForType(clause.clause_type),
    };
  }

  defaultForType(type: string): any {
    switch (type) {
      case 'toggle':              return null;
      case 'toggle_with_details': return { details: '' };
      case 'text':
      case 'textarea':            return { text: '' };
      case 'number':
      case 'percentage':          return { number: null };
      case 'select':              return { selected: '' };
      case 'date':                return { date: '' };
      case 'date_range':          return { start: '', end: '' };
      case 'territory':           return { territory: 'France' };
      case 'duration':            return { amount: null, unit: 'ans' };
      case 'multi_toggle':        return { selected: [] };
      default:                    return null;
    }
  }

  setEnabled(clauseId: number, clause: ClauseDTO, enabled: boolean): void {
    const current = this.getValue(clauseId, clause);
    this.patchValue(clauseId, { ...current, is_enabled: enabled });
  }

  patchValue(clauseId: number, lv: LocalValue): void {
    this.valuesMap.update(m => ({ ...m, [clauseId]: lv }));
  }

  patchField(clauseId: number, clause: ClauseDTO, field: string, val: any): void {
    const current = this.getValue(clauseId, clause);
    const newValue = { ...(current.value ?? {}), [field]: val };
    this.patchValue(clauseId, { ...current, value: newValue });
  }

  toggleMulti(clauseId: number, clause: ClauseDTO, option: string): void {
    const current = this.getValue(clauseId, clause);
    const selected: string[] = [...(current.value?.selected ?? [])];
    const idx = selected.indexOf(option);
    if (idx >= 0) selected.splice(idx, 1); else selected.push(option);
    this.patchValue(clauseId, { ...current, value: { selected } });
  }

  isMultiSelected(clauseId: number, clause: ClauseDTO, option: string): boolean {
    return (this.getValue(clauseId, clause).value?.selected ?? []).includes(option);
  }

  // ── Parties ────────────────────────────────────────────────────────────────

  addParty(type: 'physical' | 'company'): void {
    const newParty: ContractParty = {
      party_type: type,
      sort_order: this.parties().length,
      role: '',
    };
    this.parties.update(p => [...p, newParty]);
  }

  removeParty(index: number): void {
    this.parties.update(p => p.filter((_, i) => i !== index).map((p2, i) => ({ ...p2, sort_order: i })));
  }

  updatePartyField(index: number, field: keyof ContractParty, val: any): void {
    this.parties.update(list =>
      list.map((p, i) => i === index ? { ...p, [field]: val } : p)
    );
  }

  // ── Navigation ─────────────────────────────────────────────────────────────

  setGroup(id: number): void {
    this.showIntroTab.set(false);
    this.activeGroup.set(id);
    this.expandedTooltip.set(null);
  }

  goToIntro(): void {
    this.showIntroTab.set(true);
  }

  goToParties(): void {
    this.showIntroTab.set(false);
    this.activeGroup.set(0);
    this.expandedTooltip.set(null);
  }

  partyDisplayName(p: ContractParty): string {
    return p.party_type === 'physical'
      ? `${p.first_name ?? ''} ${p.last_name ?? ''}`.trim()
      : (p.company_name ?? '');
  }

  getValueText(clauseId: number, clause: ClauseDTO): string {
    return this.getValue(clauseId, clause).value?.text ?? '';
  }

  detectBrackets(text: string): string[] {
    const matches = text.match(/\[[^\]]+\]/g) ?? [];
    return [...new Set(matches)];
  }

  hasBrackets(clauseId: number, clause: ClauseDTO): boolean {
    return this.detectBrackets(this.getValueText(clauseId, clause)).length > 0;
  }

  resolveVariable(bracket: string): string {
    return this.introVarMap()[bracket] ?? '';
  }

  resolveOneBracket(clauseId: number, clause: ClauseDTO, bracket: string): void {
    const value = this.resolveVariable(bracket);
    if (!value) return;
    const text = this.getValueText(clauseId, clause);
    const resolved = text.replaceAll(bracket, value);
    this.patchField(clauseId, clause, 'text', resolved);
  }

  resolveAllBrackets(clauseId: number, clause: ClauseDTO): void {
    let text = this.getValueText(clauseId, clause);
    for (const [bracket, value] of Object.entries(this.introVarMap())) {
      if (value) text = text.replaceAll(bracket, value);
    }
    this.patchField(clauseId, clause, 'text', text);
  }

  insertValue(clauseId: number, clause: ClauseDTO, textToInsert: string): void {
    const el = document.getElementById('bf-ta-' + clauseId) as HTMLTextAreaElement | HTMLInputElement | null;
    const start = el?.selectionStart ?? null;
    const end   = el?.selectionEnd   ?? null;
    const current = this.getValueText(clauseId, clause);
    const pos = start !== null ? start : current.length;
    const endPos = end !== null ? end : pos;
    const resolved = this.introVarMap()[textToInsert] ?? textToInsert;
    const newText = current.slice(0, pos) + resolved + current.slice(endPos);
    this.patchField(clauseId, clause, 'text', newText);
    if (el) {
      setTimeout(() => {
        const newPos = pos + resolved.length;
        el.selectionStart = newPos;
        el.selectionEnd   = newPos;
        el.focus();
      }, 0);
    }
  }

  toggleTooltip(clauseId: number): void {
    this.expandedTooltip.update(id => id === clauseId ? null : clauseId);
    if (this.expandedExample() === clauseId) this.expandedExample.set(null);
  }

  toggleExample(clauseId: number): void {
    this.expandedExample.update(id => id === clauseId ? null : clauseId);
    if (this.expandedTooltip() === clauseId) this.expandedTooltip.set(null);
  }

  useExample(clauseId: number, clause: ClauseDTO): void {
    if (!clause.example_text) return;
    const current = this.getValue(clauseId, clause);
    // Auto-resolve intro variables present in the example text
    let text = clause.example_text;
    for (const [bracket, value] of Object.entries(this.introVarMap())) {
      if (value) text = text.replaceAll(bracket, value);
    }
    let newValue = { ...current.value };
    if (clause.clause_type === 'text' || clause.clause_type === 'textarea') {
      newValue = { text };
    } else if (clause.clause_type === 'toggle_with_details') {
      newValue = { details: text };
    }
    this.patchValue(clauseId, { ...current, value: newValue });
  }

  // ── Save / Generate ────────────────────────────────────────────────────────

  buildPayload() {
    const values: ContractValue[] = [];
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        const lv = this.getValue(clause.id, clause);
        values.push({ clause_id: clause.id, is_enabled: lv.is_enabled, value: lv.value });
      }
    }
    return { title: this.title(), parties: this.parties(), values };
  }

  save(): void {
    if (this.isFinal()) return;
    this.saving.set(true);
    this.svc.updateContract(this.contractId(), this.buildPayload()).subscribe({
      next: res => {
        this.saving.set(false);
        if (res.success) {
          this.toast.showToast({ level: 'info', message: 'Brouillon enregistré.' });
        } else {
          this.toast.showToast({ level: 'error', message: res.feedback?.message ?? 'Erreur.' });
        }
      },
      error: err => {
        this.saving.set(false);
        this.toast.showToast({ level: 'error', message: err?.error?.feedback?.message ?? 'Erreur.' });
      },
    });
  }

  generate(): void {
    if (this.isFinal()) return;
    if (!confirm('Générer le PDF ? Le contrat sera finalisé et ne pourra plus être modifié.')) return;
    this.saving.set(true);
    this.svc.updateContract(this.contractId(), this.buildPayload()).subscribe({
      next: saveRes => {
        if (!saveRes.success) {
          this.saving.set(false);
          this.toast.showToast({ level: 'error', message: saveRes.feedback?.message ?? 'Erreur sauvegarde.' });
          return;
        }
        this.generating.set(true);
        this.svc.generatePdf(this.contractId()).subscribe({
          next: genRes => {
            this.saving.set(false);
            this.generating.set(false);
            if (genRes.success) {
              this.status.set('final');
              this.pdfFile.set(genRes.data?.pdf_url ?? '');
              this.toast.showToast({ level: 'info', message: 'PDF généré avec succès !' });
            } else {
              this.toast.showToast({ level: 'error', message: genRes.feedback?.message ?? 'Erreur génération.' });
            }
          },
          error: err => {
            this.saving.set(false);
            this.generating.set(false);
            this.toast.showToast({ level: 'error', message: err?.error?.feedback?.message ?? 'Erreur génération.' });
          },
        });
      },
      error: err => {
        this.saving.set(false);
        this.toast.showToast({ level: 'error', message: err?.error?.feedback?.message ?? 'Erreur.' });
      },
    });
  }

  download(): void {
    if (this.downloading()) return;
    this.downloading.set(true);
    this.svc.downloadPdf(this.contractId()).subscribe({
      next: blob => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${(this.title() || 'contrat').replace(/[^a-z0-9]/gi, '_')}.pdf`;
        a.click();
        URL.revokeObjectURL(url);
        this.downloading.set(false);
      },
      error: () => {
        this.downloading.set(false);
        this.toast.showToast({ level: 'error', message: 'Erreur lors du téléchargement.' });
      },
    });
  }

  togglePreview(): void {
    this.showPreview.update(v => !v);
  }

  applyPreset(presetId: string): void {
    const preset = this.presets.find(p => p.id === presetId);
    if (!preset) return;

    const lookup: Record<string, { id: number; clause: ClauseDTO }> = {};
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        lookup[`${group.name}||${clause.name}`] = { id: clause.id, clause };
      }
    }

    const newMap: Record<number, LocalValue> = {};
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        if (!clause.is_required) {
          const existing = this.getValue(clause.id, clause);
          newMap[clause.id] = { is_enabled: false, value: existing.value };
        }
      }
    }

    for (const spec of preset.clauses) {
      const found = lookup[`${spec.group}||${spec.clause}`];
      if (!found) continue;
      const existing = newMap[found.id] ?? this.getValue(found.id, found.clause);
      newMap[found.id] = {
        is_enabled: true,
        value: spec.value !== undefined ? spec.value : existing.value,
      };
    }

    this.valuesMap.set(newMap);
    if (this.groups().length) this.setGroup(this.groups()[0].id);
    this.toast.showToast({ level: 'info', message: `Modèle "${preset.label}" appliqué. Affinez les clauses selon votre situation.` });
  }

  // Returns a human-readable summary of a clause value for the preview.
  formatValue(clause: ClauseDTO, lv: { is_enabled: boolean; value: any }): string {
    if (!lv.is_enabled && !clause.is_required) return '';
    const v = lv.value;
    if (!v) return '';
    switch (clause.clause_type) {
      case 'toggle':             return '✓ Activé';
      case 'toggle_with_details': return v.details ? v.details : '✓ Activé';
      case 'text':
      case 'textarea':           return v.text ?? '';
      case 'number':             return v.number != null ? String(v.number) : '';
      case 'percentage':         return v.number != null ? `${v.number} %` : '';
      case 'select':             return v.selected ?? '';
      case 'date':               return v.date ?? '';
      case 'date_range':         return v.start && v.end ? `Du ${v.start} au ${v.end}` : '';
      case 'territory':          return v.territory ?? '';
      case 'duration':           return v.amount != null ? `${v.amount} ${v.unit}` : '';
      case 'multi_toggle':       return (v.selected as string[] ?? []).join(', ');
      default:                   return '';
    }
  }

  // ── Quick Start ────────────────────────────────────────────────────────────

  readonly quickStartClauses: QuickStartSpec[] = [
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
  ];

  readonly quickStartToggles: string[] = [
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
    'Obligations de l\'auteur / artiste||Obligation de bonne foi',
    'Garanties et propriété intellectuelle||Garantie de titularité',
    'Garanties et propriété intellectuelle||Garantie d\'originalité',
    'Garanties et propriété intellectuelle||Absence d\'échantillons non autorisés',
    'Communication et image||Droit au crédit',
    'Confidentialité||Périmètre de la confidentialité',
    'Force majeure||Événements couverts',
    'Résiliation||Résiliation pour inexécution',
    'Clauses générales||Divisibilité',
    'Clauses générales||Intégralité de l\'accord',
    'Clauses générales||Modification écrite',
  ];

  applyQuickStart(): void {
    if (!this.hasKeyInfo()) {
      this.toast.showToast({
        level: 'error',
        message: 'Merci de remplir les informations clés : nom des deux parties et titre de l\'œuvre.',
      });
      return;
    }

    const lookup: Record<string, { id: number; clause: ClauseDTO }> = {};
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        lookup[`${group.name}||${clause.name}`] = { id: clause.id, clause };
      }
    }

    for (const key of this.quickStartToggles) {
      const found = lookup[key];
      if (!found) continue;
      const current = this.getValue(found.id, found.clause);
      this.patchValue(found.id, { ...current, is_enabled: true });
    }

    for (const spec of this.quickStartClauses) {
      const found = lookup[`${spec.group}||${spec.clause}`];
      if (!found) continue;
      const current = this.getValue(found.id, found.clause);
      const newValue = { ...(current.value ?? {}), [spec.field]: spec.value };
      this.patchValue(found.id, { is_enabled: true, value: newValue });
    }

    if (this.groups().length) this.setGroup(this.groups()[0].id);
    this.toast.showToast({
      level: 'info',
      message: 'Clauses pré-remplies ! Utilisez « Tout résoudre » dans chaque clause pour personnaliser.',
    });
  }

  resetContract(): void {
    if (!this.confirmReset()) {
      this.confirmReset.set(true);
      setTimeout(() => this.confirmReset.set(false), 5000);
      return;
    }
    this.confirmReset.set(false);
    this.valuesMap.set({});
    this.toast.showToast({ level: 'info', message: 'Clauses réinitialisées.' });
  }

  cancelReset(): void {
    this.confirmReset.set(false);
  }

  isClauseFilled(clauseId: number, clause: ClauseDTO): boolean {
    const lv = this.getValue(clauseId, clause);
    if (!lv.is_enabled && !clause.is_required) return false;
    if (clause.clause_type === 'toggle') return true;
    const v = lv.value;
    if (!v) return false;
    const clean = (s: string) => !!s && !/\[[^\]]+\]/.test(s);
    switch (clause.clause_type) {
      case 'toggle_with_details': return clean(v.details ?? '');
      case 'text':
      case 'textarea':            return clean(v.text ?? '');
      case 'number':
      case 'percentage':          return v.number != null;
      case 'select':              return !!v.selected;
      case 'multi_toggle':        return Array.isArray(v.selected) && v.selected.length > 0;
      case 'date':                return !!v.date;
      case 'date_range':          return !!(v.start && v.end);
      case 'territory':           return !!v.territory;
      case 'duration':            return v.amount != null;
      default:                    return false;
    }
  }

  // Returns 'complete' | 'incomplete' | 'none' for each group
  groupCompletionMap = computed<Record<number, 'complete' | 'incomplete' | 'none'>>(() => {
    const result: Record<number, 'complete' | 'incomplete' | 'none'> = {};
    const artNums = this.articleNumbers();
    const vm = this.valuesMap();

    for (const group of this.groups()) {
      if (artNums[group.id] === undefined) {
        result[group.id] = 'none';
        continue;
      }
      let hasEmpty = false;
      for (const clause of group.clauses) {
        const lv = vm[clause.id];
        const enabled = lv ? lv.is_enabled : clause.is_enabled_by_default;
        if (!enabled && !clause.is_required) continue;
        if (!this.isClauseFilled(clause.id, clause)) { hasEmpty = true; break; }
      }
      result[group.id] = hasEmpty ? 'incomplete' : 'complete';
    }
    return result;
  });

  back(): void {
    this.router.navigate(['/contract-builder']);
  }
}
