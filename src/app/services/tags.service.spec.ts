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
    service.loadTags().subscribe();
    httpMock.expectOne(URL).flush(mockResponse);

    expect(service.tags().length).toBe(3);
    expect(service.keys()).toEqual(['Am', 'Gm', 'Cm']);
    expect(service.styles()).toContain('Trap');
  });

  it('categories() déduplique les catégories par nom', () => {
    service.loadTags().subscribe();
    httpMock.expectOne(URL).flush(mockResponse);

    const cats = service.categories();
    expect(cats.length).toBe(2);
    expect(cats.map(c => c.name)).toContain('Ambiance');
    expect(cats.map(c => c.name)).toContain('Énergie');
  });

  it('ensureLoaded() partage une seule requête HTTP entre plusieurs abonnés', () => {
    service.ensureLoaded().subscribe();
    service.ensureLoaded().subscribe();
    service.loadTags().subscribe();

    // expectOne échoue s'il y a plus d'une requête vers URL.
    httpMock.expectOne(URL).flush(mockResponse);
    expect(service.tags().length).toBe(3);
  });

  it('un abonné tardif est servi depuis le cache sans nouvelle requête', () => {
    service.ensureLoaded().subscribe();
    httpMock.expectOne(URL).flush(mockResponse);

    let replayed = false;
    service.ensureLoaded().subscribe(res => { replayed = res.success; });
    httpMock.expectNone(URL);
    expect(replayed).toBe(true);
  });

  it('invalidate() force une nouvelle requête au prochain ensureLoaded()', () => {
    service.ensureLoaded().subscribe();
    httpMock.expectOne(URL).flush(mockResponse);

    service.invalidate();
    service.ensureLoaded().subscribe();
    httpMock.expectOne(URL).flush(mockResponse);
  });

  it('une erreur HTTP ne reste pas en cache : le prochain appel re-fetche', () => {
    service.ensureLoaded().subscribe({ error: () => {} });
    httpMock.expectOne(URL).error(new ProgressEvent('network error'));

    service.ensureLoaded().subscribe();
    httpMock.expectOne(URL).flush(mockResponse);
    expect(service.tags().length).toBe(3);
  });
});
