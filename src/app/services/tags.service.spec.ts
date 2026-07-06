import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { TagsService } from './tags.service';
import { environment } from '../../environments/environment';

const URL = `${environment.apiUrl}/api/filters/tags/all`;

const mockResponse = {
  success: true,
  data: {
    tags: [
      { id: 1, name: 'dark',     category: { name: 'Ambiance', color: '#333', description: null } },
      { id: 2, name: 'melodic',  category: { name: 'Ambiance', color: '#333', description: null } },
      { id: 3, name: 'energetic',category: { name: 'Énergie',  color: '#f00', description: null } },
    ],
    keys:   ['Am', 'Gm', 'Cm'],
    styles: ['Trap', 'Drill'],
  },
};

describe('TagsService', () => {
  let service: TagsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [TagsService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(TagsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getTags() GETs /api/filters/tags/all', () => {
    service.getTags().subscribe();
    const req = httpMock.expectOne(URL);
    expect(req.request.method).toBe('GET');
    req.flush(mockResponse);
  });

  it('loadTags() peuple les signals tags, keys et styles', () => {
    service.loadTags(); // le service souscrit en interne — ne pas re-souscrire
    httpMock.expectOne(URL).flush(mockResponse);

    expect(service.tags().length).toBe(3);
    expect(service.keys()).toEqual(['Am', 'Gm', 'Cm']);
    expect(service.styles()).toContain('Trap');
  });

  it('categories() déduplique les catégories par nom', () => {
    service.loadTags();
    httpMock.expectOne(URL).flush(mockResponse);

    const cats = service.categories();
    expect(cats.length).toBe(2);
    expect(cats.map(c => c.name)).toContain('Ambiance');
    expect(cats.map(c => c.name)).toContain('Énergie');
  });
});
