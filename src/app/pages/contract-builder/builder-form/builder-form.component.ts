import { Component, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import {
  ContractBuilderService,
  ClauseGroupDTO, ClauseDTO, ContractParty, ContractValue,
  ContractDetail, ContractStatus,
} from '../../../services/contract-builder.service';
import { ToastService } from '../../../services/toast.service';

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

@Component({
  selector: 'app-builder-form',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './builder-form.component.html',
  styleUrl: './builder-form.component.scss',
})
export class BuilderFormComponent implements OnInit {

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
  showPreview  = signal(false);
  downloading  = signal(false);

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
      if (this.groups().length) this.activeGroup.set(this.groups()[0].id);
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
    this.activeGroup.set(id);
    this.expandedTooltip.set(null);
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
    let newValue = { ...current.value };
    if (clause.clause_type === 'text' || clause.clause_type === 'textarea') {
      newValue = { text: clause.example_text };
    } else if (clause.clause_type === 'toggle_with_details') {
      newValue = { details: clause.example_text };
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

  back(): void {
    this.router.navigate(['/contract-builder']);
  }
}
