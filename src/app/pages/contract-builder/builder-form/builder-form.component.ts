import { ChangeDetectionStrategy, Component, HostListener, OnDestroy, OnInit, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import {
  ContractBuilderService,
  ClauseGroupDTO, ClauseDTO, ContractParty, ContractValue,
  ContractDetail, ContractStatus, ContractType,
} from '../../../services/contract-builder.service';
import { ToastService } from '../../../services/toast.service';
import {
  CONTRACT_TYPE_CONFIGS, ContractTypeConfig, IntroFieldDef,
} from '../contract-type-configs';
import { TourAnchorDirective } from '../../../directives/tour-anchor.directive';
import { TourService } from '../../../services/tour.service';

interface LocalValue {
  is_enabled: boolean;
  value: any;
}

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-builder-form',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, TourAnchorDirective],
  templateUrl: './builder-form.component.html',
  styleUrl: './builder-form.component.scss',
})
export class BuilderFormComponent implements OnInit, OnDestroy {

  // ── State ──────────────────────────────────────────────────────────────────
  loading    = signal(true);
  saving     = signal(false);
  generating = signal(false);

  contractId = signal(0);
  title      = signal('');
  status     = signal<ContractStatus>('draft');
  pdfFile    = signal<string | null>(null);

  // ── Autorisation ───────────────────────────────────────────────────────────
  // Vérité serveur : can_edit renvoyé par GET /contracts/:id (recalculé côté back
  // à chaque appel de mutation). En mode démo, toujours false.
  isDemo   = signal(false);
  canEdit  = signal(true);
  locked   = computed(() => !this.canEdit());
  readOnly = computed(() => this.isFinal() || this.locked());

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

  // ── Type de contrat / configuration ────────────────────────────────────────
  contractType = signal<ContractType>('exploitation');
  config = computed<ContractTypeConfig>(() => CONTRACT_TYPE_CONFIGS[this.contractType()]);

  // ── Intro tab ──────────────────────────────────────────────────────────────
  showIntroTab = signal(true);

  // Valeurs des champs d'introduction, indexées par IntroFieldDef.id
  introValues = signal<Record<string, string>>({});

  introValue(id: string): string {
    return this.introValues()[id] ?? '';
  }

  setIntroValue(id: string, val: string): void {
    this.introValues.update(m => ({ ...m, [id]: val }));
  }

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
    const map: Record<string, string> = {
      '[Contractant 1]':  nom(p1),
      '[Rôle 1]':         p1?.role ?? '',
      '[Contractant 2]':  nom(p2),
      '[Rôle 2]':         p2?.role ?? '',
    };
    const values = this.introValues();
    for (const section of this.config().introSections) {
      for (const field of section.fields) {
        if (!field.bracket) continue;
        const raw = (values[field.id] ?? '').trim();
        map[field.bracket] = raw ? `${raw}${field.suffix ?? ''}` : '';
      }
    }
    return map;
  });

  introVarEntries  = computed(() =>
    Object.entries(this.introVarMap()).map(([key, value]) => ({ key, value }))
  );
  definedIntroVars = computed(() => this.introVarEntries().filter(e => !!e.value));
  hasAnyIntroVar   = computed(() => this.definedIntroVars().length > 0);

  // Compteur « n / m champs auto renseignés » affiché dans le récapitulatif.
  autoFieldsDone  = computed(() => this.definedIntroVars().length);
  autoFieldsTotal = computed(() => this.introVarEntries().length);

  // Le récapitulatif des champs auto est replié tant que l'utilisateur ne le
  // déplie pas — il occupait un tiers de la hauteur de l'onglet Introduction.
  autoFieldsOpen = signal(false);

  toggleAutoFields(): void {
    this.autoFieldsOpen.update(v => !v);
  }

  // True when the essential variables (both party names + type-specific keys) are set
  hasKeyInfo = computed(() => {
    const m = this.introVarMap();
    if (!m['[Contractant 1]'] || !m['[Contractant 2]']) return false;
    return this.config().keyBrackets.every(k => !!m[k]);
  });

  // Avertissement salariat du spectacle (contrats de représentation) :
  // Contractant 1 personne physique + clause de rémunération surveillée activée.
  salariatRisk = computed(() => {
    const watch = this.config().salariatWatch;
    if (!watch) return false;
    const first = this.parties()[0];
    if (!first || first.party_type !== 'physical') return false;
    const vm = this.valuesMap();
    const watched = new Set(watch.keys);
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        if (!watched.has(`${group.name}||${clause.name}`)) continue;
        const lv = vm[clause.id];
        const enabled = lv ? lv.is_enabled : clause.is_enabled_by_default;
        if (enabled || clause.is_required) return true;
      }
    }
    return false;
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

  // ── Presets / Quick Start (fournis par la config du type de contrat) ──────
  get presets() { return this.config().presets; }

  constructor(
    private route:  ActivatedRoute,
    private router: Router,
    private svc:    ContractBuilderService,
    private toast:  ToastService,
    private tour:   TourService,
  ) {}

  // Les ancres du builder ne sont dans le DOM qu'une fois `loading` retombé à false :
  // on ne peut donc pas lancer la visite depuis ngOnInit.
  private maybeStartTour(): void {
    setTimeout(() => this.tour.maybeAutoStart('contract-builder'), 700);
  }

  ngOnInit(): void {
    if (this.route.snapshot.data['demo']) {
      this.isDemo.set(true);
      this.canEdit.set(false);
      this.loadDemo();
      return;
    }
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.contractId.set(id);
    this.loadAll(id);
  }

  // ── Démo publique (invités et utilisateurs non-Pro) ─────────────────────────
  // Charge un contrat d'exemple pour laisser découvrir l'intérieur du générateur
  // sans compte ni contrat réel. Utilise le vrai template de clauses (public),
  // avec des parties et valeurs fictives pour donner un aperçu concret.

  loadDemo(): void {
    this.loading.set(true);
    this.title.set('Exemple — Cession de droits musicaux');
    this.contractType.set('exploitation');
    this.status.set('draft');
    this.pdfFile.set(null);
    this.parties.set([
      {
        party_type: 'physical', sort_order: 0, role: 'Auteur-compositeur',
        first_name: 'Jean', last_name: 'Dupont', pseudonym: 'JD Prod',
        address: '12 rue de la Musique, 75011 Paris', email: 'jean.dupont@example.com',
      },
      {
        party_type: 'company', sort_order: 1, role: 'Éditeur',
        company_name: 'Label Music SAS', legal_form: 'SAS', siren: '123 456 789',
        address: '8 avenue des Studios, 75010 Paris', email: 'contact@labelmusic.example',
      },
    ]);
    this.svc.getTemplate('exploitation').subscribe({
      next: res => {
        if (res.success && res.data) {
          this.groups.set(res.data.groups);
          this.populateDemoValues();
        }
        this.loading.set(false);
        this.activeGroup.set(0);
        this.showIntroTab.set(true);
        this.maybeStartTour();
      },
      error: () => this.loading.set(false),
    });
  }

  private populateDemoValues(): void {
    const demoVars: Record<string, string> = {
      '[Contractant 1]': 'Jean Dupont',
      '[Rôle 1]':        'Auteur-compositeur',
      '[Contractant 2]': 'Label Music SAS',
      '[Rôle 2]':        'Éditeur',
    };
    const map: Record<number, LocalValue> = {};
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        if (clause.example_text && ['text', 'textarea', 'toggle_with_details'].includes(clause.clause_type)) {
          let text = clause.example_text;
          for (const [bracket, value] of Object.entries(demoVars)) text = text.replaceAll(bracket, value);
          const value = clause.clause_type === 'toggle_with_details' ? { details: text } : { text };
          map[clause.id] = { is_enabled: true, value };
        } else if (clause.is_enabled_by_default || clause.is_required) {
          map[clause.id] = { is_enabled: true, value: clause.default_value ?? this.defaultForType(clause.clause_type) };
        }
      }
    }
    this.valuesMap.set(map);
  }

  goToPremium(): void {
    this.router.navigate(['/premium']);
  }

  // ── Load ───────────────────────────────────────────────────────────────────

  loadAll(id: number): void {
    this.loading.set(true);

    const finish = () => {
      this.loading.set(false);
      this.activeGroup.set(0);
      this.showIntroTab.set(true);
      this.maybeStartTour();
    };

    // Le contrat d'abord (il porte son type), puis le template correspondant.
    this.svc.getContract(id).subscribe({
      next: res => {
        if (res.success && res.data) this.applyContract(res.data.contract);
        this.svc.getTemplate(this.contractType()).subscribe({
          next: tRes => {
            if (tRes.success && tRes.data) this.groups.set(tRes.data.groups);
            finish();
          },
          error: () => finish(),
        });
      },
      error: () => {
        finish();
        this.toast.showToast({ level: 'error', message: 'Contrat introuvable.' });
        this.router.navigate(['/contract-builder']);
      },
    });
  }

  applyContract(c: ContractDetail): void {
    this.title.set(c.title);
    this.contractType.set(c.contract_type ?? 'exploitation');
    this.status.set(c.status);
    this.pdfFile.set(c.pdf_file);
    this.canEdit.set(c.can_edit ?? true);
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

  fillAllExamples(): void {
    const introVars = this.introVarMap();
    let filled = 0;
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        if (!clause.example_text) continue;
        if (!['text', 'textarea', 'toggle_with_details'].includes(clause.clause_type)) continue;
        const lv = this.getValue(clause.id, clause);
        if (!lv.is_enabled && !clause.is_required) continue;
        let text = clause.example_text;
        for (const [bracket, value] of Object.entries(introVars)) {
          if (value) text = text.replaceAll(bracket, value);
        }
        let newValue = { ...lv.value };
        if (clause.clause_type === 'text' || clause.clause_type === 'textarea') {
          newValue = { text };
        } else if (clause.clause_type === 'toggle_with_details') {
          newValue = { details: text };
        }
        this.patchValue(clause.id, { ...lv, value: newValue });
        filled++;
      }
    }
    if (filled === 0) {
      this.toast.showToast({ level: 'warning', message: 'Aucune clause activée ne dispose d\'une rédaction type.' });
    } else {
      this.toast.showToast({ level: 'info', message: `${filled} clause(s) rédigées. Ajustez le texte uniquement si votre situation le demande.` });
    }
  }

  fillableCount = computed(() => {
    let count = 0;
    for (const group of this.groups()) {
      for (const clause of group.clauses) {
        if (!clause.example_text) continue;
        if (!['text', 'textarea', 'toggle_with_details'].includes(clause.clause_type)) continue;
        const lv = this.getValue(clause.id, clause);
        if (lv.is_enabled || clause.is_required) count++;
      }
    }
    return count;
  });

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
    if (this.readOnly()) return;
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
    if (this.readOnly()) return;
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
    this.showPreview() ? this.closePreview() : this.openPreview();
  }

  openPreview(): void {
    this.showPreview.set(true);
    document.body.style.overflow = 'hidden';
  }

  closePreview(): void {
    this.showPreview.set(false);
    document.body.style.overflow = '';
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.showPreview()) this.closePreview();
  }

  ngOnDestroy(): void {
    document.body.style.overflow = '';
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

  // ── Quick Start (fourni par la config du type de contrat) ─────────────────

  get quickStartClauses() { return this.config().quickStartClauses; }
  get quickStartToggles() { return this.config().quickStartToggles; }

  applyQuickStart(): void {
    if (!this.hasKeyInfo()) {
      this.toast.showToast({
        level: 'error',
        message: this.config().keyInfoHint,
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
      message: 'Clauses pré-remplies ! Utilisez « Tout remplir » dans chaque clause pour personnaliser.',
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

  // ── Progression ────────────────────────────────────────────────────────────
  // Ne comptent que les clauses réellement retenues (activées ou obligatoires)
  // dans un article actif : le dénominateur suit donc les choix de l'utilisateur.
  progress = computed<{ done: number; total: number; pct: number }>(() => {
    const artNums = this.articleNumbers();
    let done = 0;
    let total = 0;
    for (const group of this.groups()) {
      if (artNums[group.id] === undefined) continue;
      for (const clause of group.clauses) {
        const lv = this.getValue(clause.id, clause);
        if (!lv.is_enabled && !clause.is_required) continue;
        total++;
        if (this.isClauseFilled(clause.id, clause)) done++;
      }
    }
    return { done, total, pct: total ? Math.round((done / total) * 100) : 0 };
  });

  // Circonférence du cercle de progression (r=14) — utilisée pour le stroke-dasharray.
  readonly ringCircumference = 2 * Math.PI * 14;

  ringOffset = computed(() =>
    this.ringCircumference * (1 - this.progress().pct / 100)
  );

  // ── Étape suivante ─────────────────────────────────────────────────────────
  // Ordre de navigation : Introduction → Parties → articles, dans l'ordre des groupes.

  nextStep = computed<{ label: string; groupId: number | null } | null>(() => {
    if (this.showIntroTab()) {
      return { label: 'Parties au contrat', groupId: 0 };
    }
    const groups = this.groups();
    if (this.activeGroup() === 0) {
      const first = groups[0];
      return first ? { label: first.name, groupId: first.id } : null;
    }
    const idx = groups.findIndex(g => g.id === this.activeGroup());
    const next = idx >= 0 ? groups[idx + 1] : undefined;
    return next ? { label: next.name, groupId: next.id } : null;
  });

  goToNextStep(): void {
    const step = this.nextStep();
    if (!step) return;
    if (step.groupId === 0) this.goToParties();
    else if (step.groupId !== null) this.setGroup(step.groupId);
    document.querySelector('.bf-content')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  back(): void {
    this.router.navigate(['/contract-builder']);
  }
}
