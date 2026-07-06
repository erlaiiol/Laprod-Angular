import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { NotificationService, AppNotification } from './notification.service';
import { AuthService } from './auth.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/main`;

const mockNotifs: AppNotification[] = [
  { id: 1, type: 'info', title: 'Bienvenue', message: 'Bienvenue sur LaProd', link: null, is_read: false, created_at: '2026-01-01' },
  { id: 2, type: 'info', title: 'Achat',     message: 'Beat acheté',          link: '/track/1', is_read: true, created_at: '2026-01-02' },
];

describe('NotificationService', () => {
  let service: NotificationService;
  let httpMock: HttpTestingController;

  const authStub = { getToken: () => 'token-test' };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        NotificationService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authStub },
      ],
    });
    service  = TestBed.inject(NotificationService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('load() GETs /api/main/notifications', () => {
    service.load().subscribe();
    const req = httpMock.expectOne(`${BASE}/notifications`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { notifications: [] } });
  });

  it('load() peuple le signal notifications', () => {
    service.load().subscribe();
    httpMock.expectOne(`${BASE}/notifications`).flush({ success: true, data: { notifications: mockNotifs } });
    expect(service.notifications().length).toBe(2);
  });

  it('load() calcule unreadCount correctement', () => {
    service.load().subscribe();
    httpMock.expectOne(`${BASE}/notifications`).flush({ success: true, data: { notifications: mockNotifs } });
    expect(service.unreadCount()).toBe(1); // seul le premier est non lu
  });

  it('markAsRead() POSTs à /api/main/notifications/:id/read', () => {
    service.markAsRead(1).subscribe();
    const req = httpMock.expectOne(`${BASE}/notifications/1/read`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  it('markAsRead() met à jour is_read dans le signal', () => {
    service.load().subscribe();
    httpMock.expectOne(`${BASE}/notifications`).flush({ success: true, data: { notifications: mockNotifs } });

    service.markAsRead(1).subscribe();
    httpMock.expectOne(`${BASE}/notifications/1/read`).flush({ success: true, feedback: { level: 'success', message: '' } });

    const n = service.notifications().find(x => x.id === 1);
    expect(n?.is_read).toBe(true);
    expect(service.unreadCount()).toBe(0);
  });

  it('markAllAsRead() POSTs à /api/main/notifications/mark-all-read', () => {
    service.markAllAsRead().subscribe();
    const req = httpMock.expectOne(`${BASE}/notifications/mark-all-read`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  it('markAllAsRead() met unreadCount à 0', () => {
    service.load().subscribe();
    httpMock.expectOne(`${BASE}/notifications`).flush({ success: true, data: { notifications: mockNotifs } });

    service.markAllAsRead().subscribe();
    httpMock.expectOne(`${BASE}/notifications/mark-all-read`).flush({ success: true, feedback: { level: 'success', message: '' } });

    expect(service.unreadCount()).toBe(0);
  });
});
