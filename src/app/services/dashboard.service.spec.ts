import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { DashboardService } from './dashboard.service';
import { environment } from '../../environments/environment';

const BASE_URL = `${environment.apiUrl}/api/dashboard`;

describe('DashboardService', () => {
  let service: DashboardService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        DashboardService,
        provideHttpClient(),
        provideHttpClientTesting(),
      ],
    });
    service = TestBed.inject(DashboardService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  it('getBeatmakerDashboard() GETs /api/dashboard/beatmaker', () => {
    service.getBeatmakerDashboard().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/beatmaker`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: {} });
  });

  it('getArtistDashboard() GETs /api/dashboard/artist', () => {
    service.getArtistDashboard().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/artist`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: {} });
  });

  it('getMixEngineerDashboard() GETs /api/dashboard/mix-engineer', () => {
    service.getMixEngineerDashboard().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/mix-engineer`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: {} });
  });
});
