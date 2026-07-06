import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { SimilarArtistsService } from './similar-artists.service';
import { environment } from '../../environments/environment';

const URL = `${environment.apiUrl}/api/filters/similar-artists`;

describe('SimilarArtistsService', () => {
  let service: SimilarArtistsService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [SimilarArtistsService, provideHttpClient(), provideHttpClientTesting()],
    });
    service  = TestBed.inject(SimilarArtistsService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getSimilarArtists() GETs /api/filters/similar-artists', () => {
    service.getSimilarArtists().subscribe();
    const req = httpMock.expectOne(URL);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { scenes: [] } });
  });

  it('getSimilarArtists() retourne les scènes', () => {
    let result: any;
    service.getSimilarArtists().subscribe(res => result = res.data);
    httpMock.expectOne(URL).flush({
      success: true,
      data: {
        scenes: [{ name: 'UK Drill', artists: [{ id: 1, name: 'Central Cee', scene: 'UK Drill' }] }],
      },
    });
    expect(result.scenes.length).toBe(1);
    expect(result.scenes[0].name).toBe('UK Drill');
  });
});
