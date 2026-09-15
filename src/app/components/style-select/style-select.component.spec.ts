/**
 * Tests unitaires — StyleSelectComponent
 *
 * Comportements vérifiés :
 *  - le brouillon (draft) suit la valeur externe (`value`) tant que rien n'est
 *    explicitement sélectionné ;
 *  - le filtrage des options et la détection de match exact sont insensibles
 *    à la casse ;
 *  - l'option "ajouter" n'apparaît que sans match exact ;
 *  - sélectionner une option existante émet sa casse canonique, jamais la
 *    saisie brute de l'utilisateur (c'est ce qui évite les doublons "trap" /
 *    "Trap" côté client, en complément de la normalisation serveur) ;
 *  - Escape referme le menu et annule une saisie non validée ;
 *  - Enter valide le match exact s'il existe, sinon ajoute le nouveau style.
 */

import { TestBed } from '@angular/core/testing';
import { StyleSelectComponent } from './style-select.component';

function makeComp(value: string, options: string[]): StyleSelectComponent {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({ imports: [StyleSelectComponent] });
  const fixture = TestBed.createComponent(StyleSelectComponent);
  fixture.componentRef.setInput('value', value);
  fixture.componentRef.setInput('options', options);
  fixture.detectChanges();
  return fixture.componentInstance;
}

describe('StyleSelectComponent', () => {

  afterEach(() => TestBed.resetTestingModule());

  it('synchronise le brouillon sur la valeur externe', () => {
    const c = makeComp('Trap', ['Trap', 'Drill']);
    expect(c.draft()).toBe('Trap');
  });

  it('filtre les options de façon insensible à la casse', () => {
    const c = makeComp('', ['Trap', 'Drill', 'Afro House']);
    c.onInput('tra');
    expect(c.filteredOptions()).toEqual(['Trap']);
  });

  it('détecte un match exact insensible à la casse', () => {
    const c = makeComp('', ['Trap']);
    c.onInput('trap');
    expect(c.exactMatch()).toBe('Trap');
    expect(c.showAddOption()).toBe(false);
  });

  it("propose d'ajouter un nouveau style quand aucun match exact n'existe", () => {
    const c = makeComp('', ['Trap']);
    c.onInput('Reggae');
    expect(c.exactMatch()).toBeNull();
    expect(c.showAddOption()).toBe(true);
  });

  it('selectExisting émet la casse canonique existante, pas la saisie utilisateur', () => {
    const c = makeComp('', ['Trap']);
    const emitted: string[] = [];
    c.valueChange.subscribe(v => emitted.push(v));
    c.onInput('trap');
    c.selectExisting('Trap');
    expect(emitted).toEqual(['Trap']);
    expect(c.draft()).toBe('Trap');
    expect(c.isOpen()).toBe(false);
  });

  it('selectNew émet le texte saisi (trimmé) tel quel', () => {
    const c = makeComp('', []);
    const emitted: string[] = [];
    c.valueChange.subscribe(v => emitted.push(v));
    c.onInput('  Reggae  ');
    c.selectNew();
    expect(emitted).toEqual(['Reggae']);
  });

  it('selectNew ne fait rien si le brouillon est vide', () => {
    const c = makeComp('', []);
    const emitted: string[] = [];
    c.valueChange.subscribe(v => emitted.push(v));
    c.onInput('   ');
    c.selectNew();
    expect(emitted).toEqual([]);
  });

  it('Escape referme le menu et annule une saisie non validée', () => {
    const c = makeComp('Trap', ['Trap']);
    c.onInput('nouveau texte non validé');
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(c.isOpen()).toBe(false);
    expect(c.draft()).toBe('Trap');
  });

  it('Enter sélectionne le match exact existant', () => {
    const c = makeComp('', ['Trap']);
    const emitted: string[] = [];
    c.valueChange.subscribe(v => emitted.push(v));
    c.onInput('TRAP');
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(emitted).toEqual(['Trap']);
  });

  it("Enter ajoute un nouveau style s'il n'y a pas de match exact", () => {
    const c = makeComp('', ['Trap']);
    const emitted: string[] = [];
    c.valueChange.subscribe(v => emitted.push(v));
    c.onInput('Reggae');
    c.onKeydown(new KeyboardEvent('keydown', { key: 'Enter' }));
    expect(emitted).toEqual(['Reggae']);
  });
});
