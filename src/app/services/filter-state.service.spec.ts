import { TestBed } from '@angular/core/testing';
import { FilterStateService } from './filter-state.service';

describe('FilterStateService', () => {
  let service: FilterStateService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    service = TestBed.inject(FilterStateService);
  });

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('filters() démarre avec des valeurs vides', () => {
    const f = service.filters();
    expect(f.search).toBe('');
    expect(f.tags).toEqual([]);
    expect(f.bpmMin).toBeNull();
  });

  it('apply() met à jour les filtres et incrémente applied', () => {
    const before = service.applied();
    service.apply({ search: 'trap', bpmMin: 120, bpmMax: 140, keys: [], styles: [], tags: [], similarArtists: [] });
    expect(service.filters().search).toBe('trap');
    expect(service.filters().bpmMin).toBe(120);
    expect(service.applied()).toBe(before + 1);
  });

  it('apply() remet savedPage à 1', () => {
    service['savedPage'].set(3);
    service.apply({ search: '', bpmMin: null, bpmMax: null, keys: [], styles: [], tags: [], similarArtists: [] });
    expect(service.savedPage()).toBe(1);
  });

  it('reset() efface tous les filtres et incrémente applied', () => {
    service.apply({ search: 'test', bpmMin: 100, bpmMax: 200, keys: ['Am'], styles: ['Trap'], tags: ['dark'], similarArtists: ['Drake'] });
    const before = service.applied();
    service.reset();
    const f = service.filters();
    expect(f.search).toBe('');
    expect(f.tags).toEqual([]);
    expect(service.applied()).toBe(before + 1);
  });

  it('addTag() ajoute un tag absent et retourne true', () => {
    const result = service.addTag('dark');
    expect(result).toBe(true);
    expect(service.filters().tags).toContain('dark');
  });

  it('addTag() retourne false si le tag est déjà présent', () => {
    service.addTag('dark');
    const result = service.addTag('dark');
    expect(result).toBe(false);
    expect(service.filters().tags.filter(t => t === 'dark').length).toBe(1);
  });

  it('addStyle() ajoute un style absent et retourne true', () => {
    const result = service.addStyle('Trap');
    expect(result).toBe(true);
    expect(service.filters().styles).toContain('Trap');
  });

  it('addSimilarArtist() ajoute un artiste absent et retourne true', () => {
    const result = service.addSimilarArtist('Drake');
    expect(result).toBe(true);
    expect(service.filters().similarArtists).toContain('Drake');
  });

  it('addSimilarArtist() retourne false si déjà présent', () => {
    service.addSimilarArtist('Drake');
    expect(service.addSimilarArtist('Drake')).toBe(false);
  });
});
