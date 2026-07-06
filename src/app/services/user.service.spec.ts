import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { UserService } from './user.service';
import { AuthService } from './auth.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/main`;

describe('UserService', () => {
  let service: UserService;
  let httpMock: HttpTestingController;

  const authStub = { getToken: () => 'test-token' };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        UserService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authStub },
      ],
    });
    service  = TestBed.inject(UserService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('getProfile() GETs /api/main/users/:username', () => {
    service.getProfile('johndoe').subscribe();
    const req = httpMock.expectOne(`${BASE}/users/johndoe`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { user: {} } });
  });

  it('getProfile() envoie le header Authorization', () => {
    service.getProfile('johndoe').subscribe();
    const req = httpMock.expectOne(`${BASE}/users/johndoe`);
    expect(req.request.headers.get('Authorization')).toBe('Bearer test-token');
    req.flush({ success: true, data: { user: {} } });
  });

  it('updateProfile() PUTs à /api/main/users/edit-profile', () => {
    service.updateProfile(new FormData()).subscribe();
    const req = httpMock.expectOne(`${BASE}/users/edit-profile`);
    expect(req.request.method).toBe('PUT');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  it('updateSecurity() PUTs à /api/main/users/edit-profile/security', () => {
    service.updateSecurity({ new_username: 'nouveau' }).subscribe();
    const req = httpMock.expectOne(`${BASE}/users/edit-profile/security`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body.new_username).toBe('nouveau');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  it('sendContact() POSTs à /api/main/contact', () => {
    service.sendContact('Sujet', 'Mon message').subscribe();
    const req = httpMock.expectOne(`${BASE}/contact`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.subject).toBe('Sujet');
    expect(req.request.body.message).toBe('Mon message');
    req.flush({ success: true, feedback: { level: 'success', message: 'Envoyé' } });
  });
});
