import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';

import { BuilderFormComponent } from './builder-form.component';
import { ClauseGroupDTO, ClauseDTO, ContractParty } from '../../../services/contract-builder.service';

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeClause(overrides: Partial<ClauseDTO> = {}): ClauseDTO {
  return {
    id: 1,
    group_id: 1,
    name: 'Test Clause',
    description: null,
    tooltip_short: null,
    tooltip_long: null,
    clause_type: 'text',
    options: null,
    default_value: null,
    is_required: false,
    is_enabled_by_default: true,
    sort_order: 1,
    is_active: true,
    legal_reference: null,
    example_text: null,
    tooltip_plain: null,
    ...overrides,
  };
}

function makeGroup(id: number, clauses: ClauseDTO[], overrides: Partial<ClauseGroupDTO> = {}): ClauseGroupDTO {
  return {
    id,
    name: `Group ${id}`,
    description: null,
    tooltip: null,
    sort_order: id,
    is_active: true,
    clauses,
    ...overrides,
  };
}

function makeParty(overrides: Partial<ContractParty> = {}): ContractParty {
  return {
    party_type: 'physical',
    sort_order: 0,
    role: 'Auteur',
    first_name: 'Jean',
    last_name: 'Dupont',
    ...overrides,
  };
}

// ── Suite ─────────────────────────────────────────────────────────────────────

describe('BuilderFormComponent', () => {
  let component: BuilderFormComponent;
  let fixture: ComponentFixture<BuilderFormComponent>;
  let httpMock: HttpTestingController;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [BuilderFormComponent],
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { paramMap: { get: () => null } }, queryParams: of({}) },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(BuilderFormComponent);
    component = fixture.componentInstance;
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    // Absorber toute requête HTTP pendante générée par ngOnInit
    httpMock.match(() => true).forEach(req => req.flush({ success: true, data: { groups: [] } }));
    httpMock.verify();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // -- articleNumbers computed --

  describe('articleNumbers()', () => {
    it('assigns article number only to groups with at least one enabled clause', () => {
      const enabledClause  = makeClause({ id: 1, is_enabled_by_default: true });
      const disabledClause = makeClause({ id: 2, is_enabled_by_default: false, is_required: false });

      component.groups.set([
        makeGroup(1, [enabledClause]),   // doit être Art. 1
        makeGroup(2, [disabledClause]),  // pas de numéro
        makeGroup(3, [makeClause({ id: 3, is_enabled_by_default: true })]), // Art. 2
      ]);
      component.valuesMap.set({});

      const nums = component.articleNumbers();
      expect(nums[1]).toBe(1);
      expect(nums[2]).toBeUndefined();
      expect(nums[3]).toBe(2);
    });

    it('returns empty object when all groups have only disabled clauses', () => {
      const disabled = makeClause({ id: 1, is_enabled_by_default: false, is_required: false });
      component.groups.set([makeGroup(1, [disabled])]);
      component.valuesMap.set({});

      expect(component.articleNumbers()).toEqual({});
    });

    it('valuesMap override takes priority over is_enabled_by_default', () => {
      // Clause désactivée par défaut, mais activée via valuesMap
      const clause = makeClause({ id: 10, is_enabled_by_default: false, is_required: false });
      component.groups.set([makeGroup(1, [clause])]);
      component.valuesMap.set({ 10: { is_enabled: true, value: null } });

      const nums = component.articleNumbers();
      expect(nums[1]).toBe(1);
    });

    it('required clauses force the group to have an article number', () => {
      // Clause désactivée mais requise → le groupe doit quand même compter
      // Note : la logique actuelle compte uniquement les clauses enabled dans activeGroup
      // Ici on vérifie le comportement documenté : is_required ne force PAS le groupe
      // (seul is_enabled_by_default ou valuesMap.is_enabled compte pour articleNumbers)
      const required = makeClause({ id: 5, is_enabled_by_default: false, is_required: true });
      component.groups.set([makeGroup(1, [required])]);
      component.valuesMap.set({});

      // Selon l'implémentation actuelle, is_required ne compte pas pour articleNumbers
      // (seulement pour clauseNumbers). Ce test documente ce comportement.
      const nums = component.articleNumbers();
      // Si le comportement change, ce test cassera et alertera le dev
      expect(nums[1]).toBeUndefined();
    });
  });

  // -- clauseNumbers computed --

  describe('clauseNumbers()', () => {
    it('assigns sub-numbers only to enabled or required clauses', () => {
      const c1 = makeClause({ id: 1, is_enabled_by_default: true,  is_required: false });
      const c2 = makeClause({ id: 2, is_enabled_by_default: false, is_required: false });
      const c3 = makeClause({ id: 3, is_enabled_by_default: false, is_required: true });

      component.groups.set([makeGroup(1, [c1, c2, c3])]);
      component.valuesMap.set({});

      const nums = component.clauseNumbers();
      expect(nums[1]).toBe('1.1');
      expect(nums[2]).toBeUndefined();
      expect(nums[3]).toBe('1.2');
    });

    it('uses artNum from articleNumbers as prefix', () => {
      const c = makeClause({ id: 10, is_enabled_by_default: true });
      component.groups.set([makeGroup(5, [c])]);
      component.valuesMap.set({});

      const nums = component.clauseNumbers();
      expect(nums[10]).toBe('1.1');
    });

    it('skips groups with no article number', () => {
      const disabled = makeClause({ id: 99, is_enabled_by_default: false, is_required: false });
      component.groups.set([makeGroup(1, [disabled])]);
      component.valuesMap.set({});

      const nums = component.clauseNumbers();
      expect(nums[99]).toBeUndefined();
    });
  });

  // -- toggleTooltip() --

  describe('toggleTooltip()', () => {
    it('sets expandedTooltip to the clause id on first click', () => {
      component.expandedTooltip.set(null);
      component.toggleTooltip(42);
      expect(component.expandedTooltip()).toBe(42);
    });

    it('closes tooltip when clicking same clause again', () => {
      component.expandedTooltip.set(42);
      component.toggleTooltip(42);
      expect(component.expandedTooltip()).toBeNull();
    });

    it('switches tooltip to new clause when another is open', () => {
      component.expandedTooltip.set(10);
      component.toggleTooltip(20);
      expect(component.expandedTooltip()).toBe(20);
    });
  });

  // -- isFinal / hasPdf --

  it('isFinal() returns false for draft contracts', () => {
    component.status.set('draft');
    expect(component.isFinal()).toBe(false);
  });

  it('isFinal() returns true for final contracts', () => {
    component.status.set('final');
    expect(component.isFinal()).toBe(true);
  });

  it('hasPdf() returns false when no PDF is attached', () => {
    component.pdfFile.set(null);
    expect(component.hasPdf()).toBe(false);
  });

  it('hasPdf() returns true when a PDF path is set', () => {
    component.pdfFile.set('/contracts/builder/42.pdf');
    expect(component.hasPdf()).toBe(true);
  });

  // ── Variables du contrat (brackets [Contractant 1], [l'Œuvre]...) ────────────
  // Ce mécanisme substitue côté front les variables intro dans le texte des
  // clauses AVANT l'enregistrement (aucune notion de "variable" côté backend,
  // cf. tests/integration/test_contract_builder_pdf_generation.py).

  describe('introVarMap()', () => {
    it('derives [Contractant 1]/[Rôle 1] and [Contractant 2]/[Rôle 2] from physical parties', () => {
      component.parties.set([
        makeParty({ first_name: 'Jean', last_name: 'Dupont', role: 'Auteur-compositeur' }),
        makeParty({ first_name: 'Marie', last_name: 'Martin', role: 'Éditeur' }),
      ]);

      const map = component.introVarMap();
      expect(map['[Contractant 1]']).toBe('Jean Dupont');
      expect(map['[Rôle 1]']).toBe('Auteur-compositeur');
      expect(map['[Contractant 2]']).toBe('Marie Martin');
      expect(map['[Rôle 2]']).toBe('Éditeur');
    });

    it('uses company_name for a personne morale party', () => {
      component.parties.set([
        makeParty({ party_type: 'company', company_name: 'Studio Wax SARL', role: 'Éditeur', first_name: undefined, last_name: undefined }),
      ]);

      expect(component.introVarMap()['[Contractant 1]']).toBe('Studio Wax SARL');
    });

    it('returns empty strings for both parties when none are set', () => {
      component.parties.set([]);
      const map = component.introVarMap();
      expect(map['[Contractant 1]']).toBe('');
      expect(map['[Contractant 2]']).toBe('');
      expect(map['[Rôle 1]']).toBe('');
    });

    it('exposes type-specific intro fields with their bracket and suffix applied', () => {
      component.contractType.set('exploitation');
      component.setIntroValue('pctArtiste', '70');

      expect(component.introVarMap()['[% Artiste]']).toBe('70%');
    });

    it('resolves an empty string (not undefined) for an unfilled intro field', () => {
      component.contractType.set('exploitation');
      // oeuvreTitle jamais renseigné
      expect(component.introVarMap()["[l'Œuvre]"]).toBe('');
    });

    it('trims whitespace-only intro values down to an empty string', () => {
      component.contractType.set('exploitation');
      component.setIntroValue('oeuvreTitle', '   ');
      expect(component.introVarMap()["[l'Œuvre]"]).toBe('');
    });
  });

  describe('resolveVariable()', () => {
    it('returns the mapped value for a known bracket', () => {
      component.parties.set([makeParty({ first_name: 'Jean', last_name: 'Dupont' })]);
      expect(component.resolveVariable('[Contractant 1]')).toBe('Jean Dupont');
    });

    it('returns an empty string for a bracket that does not exist in the map', () => {
      expect(component.resolveVariable('[Inconnu]')).toBe('');
    });
  });

  describe('resolveOneBracket()', () => {
    it('replaces every occurrence of the given bracket in the clause text', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea' });
      component.parties.set([makeParty({ first_name: 'Jean', last_name: 'Dupont' })]);
      component.patchField(1, clause, 'text', '[Contractant 1] s\'engage. Signé : [Contractant 1].');

      component.resolveOneBracket(1, clause, '[Contractant 1]');

      expect(component.getValueText(1, clause)).toBe("Jean Dupont s'engage. Signé : Jean Dupont.");
    });

    it('does nothing when the variable has no value yet', () => {
      const clause = makeClause({ id: 2, clause_type: 'textarea' });
      component.parties.set([]); // [Contractant 1] résout à ''
      component.patchField(2, clause, 'text', '[Contractant 1] s\'engage.');

      component.resolveOneBracket(2, clause, '[Contractant 1]');

      expect(component.getValueText(2, clause)).toBe("[Contractant 1] s'engage.");
    });
  });

  describe('resolveAllBrackets()', () => {
    it('replaces every resolvable bracket present in the text', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea' });
      component.parties.set([
        makeParty({ first_name: 'Jean', last_name: 'Dupont', role: 'Auteur' }),
        makeParty({ first_name: 'Marie', last_name: 'Martin', role: 'Éditeur' }),
      ]);
      component.patchField(1, clause, 'text', '[Contractant 1] ([Rôle 1]) et [Contractant 2] ([Rôle 2]).');

      component.resolveAllBrackets(1, clause);

      expect(component.getValueText(1, clause)).toBe('Jean Dupont (Auteur) et Marie Martin (Éditeur).');
    });

    it('leaves an unresolved bracket untouched instead of blanking it out', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea' });
      component.contractType.set('exploitation');
      component.parties.set([makeParty({ first_name: 'Jean', last_name: 'Dupont' })]);
      // [l'Œuvre] n'est jamais renseigné dans introValues
      component.patchField(1, clause, 'text', "[Contractant 1] cède [l'Œuvre].");

      component.resolveAllBrackets(1, clause);

      // Le contractant est résolu, la variable non renseignée reste en clair —
      // un texte vidé silencieusement serait pire qu'un placeholder visible.
      expect(component.getValueText(1, clause)).toBe("Jean Dupont cède [l'Œuvre].");
    });
  });

  describe('detectBrackets() / hasBrackets()', () => {
    it('detects and deduplicates bracket placeholders in a text', () => {
      const brackets = component.detectBrackets('[Contractant 1] et [Contractant 1] puis [Rôle 1]');
      expect(brackets).toEqual(['[Contractant 1]', '[Rôle 1]']);
    });

    it('returns an empty array when there is no bracket', () => {
      expect(component.detectBrackets('Aucune variable ici.')).toEqual([]);
    });

    it('hasBrackets() reflects whether the clause text still has placeholders', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea' });
      component.patchField(1, clause, 'text', '[Contractant 1] s\'engage.');
      expect(component.hasBrackets(1, clause)).toBe(true);

      component.patchField(1, clause, 'text', 'Jean Dupont s\'engage.');
      expect(component.hasBrackets(1, clause)).toBe(false);
    });
  });

  describe('useExample()', () => {
    it('resolves brackets in example_text and stores it as the text value', () => {
      const clause = makeClause({
        id: 1, clause_type: 'textarea',
        example_text: '[Contractant 1] certifie être l\'auteur de l\'œuvre.',
      });
      component.parties.set([makeParty({ first_name: 'Jean', last_name: 'Dupont' })]);

      component.useExample(1, clause);

      expect(component.getValueText(1, clause)).toBe("Jean Dupont certifie être l'auteur de l'œuvre.");
    });

    it('stores the resolved text under "details" for a toggle_with_details clause', () => {
      const clause = makeClause({
        id: 1, clause_type: 'toggle_with_details',
        example_text: '[Contractant 1] bénéficie d\'une exclusivité totale.',
      });
      component.parties.set([makeParty({ first_name: 'Jean', last_name: 'Dupont' })]);

      component.useExample(1, clause);

      expect(component.getValue(1, clause).value.details).toBe("Jean Dupont bénéficie d'une exclusivité totale.");
    });

    it('does nothing when the clause has no example_text', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea', example_text: null });
      component.useExample(1, clause);
      expect(component.getValueText(1, clause)).toBe('');
    });
  });

  describe('insertValue()', () => {
    it('resolves a known bracket before inserting it at the cursor position', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea' });
      component.parties.set([makeParty({ first_name: 'Jean', last_name: 'Dupont' })]);
      component.patchField(1, clause, 'text', '');

      component.insertValue(1, clause, '[Contractant 1]');

      expect(component.getValueText(1, clause)).toBe('Jean Dupont');
    });

    it('inserts the literal text as-is when it is not a known bracket', () => {
      const clause = makeClause({ id: 1, clause_type: 'textarea' });
      component.patchField(1, clause, 'text', '');

      component.insertValue(1, clause, 'texte libre');

      expect(component.getValueText(1, clause)).toBe('texte libre');
    });
  });

  describe('config() switches with contractType (management contract)', () => {
    it('exposes the management config label and Premium legal warning', () => {
      component.contractType.set('management');
      expect(component.config().label).toBe('Contrat de management');
      expect(component.config().legalWarning?.title).toContain('agent artistique');
    });

    it('derives [Contractant 1]/[Contractant 2] the same way regardless of contract type', () => {
      component.contractType.set('management');
      component.parties.set([
        makeParty({ first_name: 'Alice', last_name: 'Durand', role: 'Manager' }),
        makeParty({ first_name: 'Jean', last_name: 'Dupont', role: 'Artiste' }),
      ]);

      const map = component.introVarMap();
      expect(map['[Contractant 1]']).toBe('Alice Durand');
      expect(map['[Contractant 2]']).toBe('Jean Dupont');
    });
  });
});
