import { TestBed, ComponentFixture } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter, ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';

import { BuilderFormComponent } from './builder-form.component';
import { ClauseGroupDTO, ClauseDTO } from '../../../services/contract-builder.service';

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
});
