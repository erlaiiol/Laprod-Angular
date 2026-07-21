import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { AdminService } from './admin.service';
import { AuthService } from './auth.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/admin`;

describe('AdminService', () => {
  let service: AdminService;
  let httpMock: HttpTestingController;

  const authStub = { getToken: () => 'admin-jwt' };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        AdminService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authStub },
      ],
    });
    service  = TestBed.inject(AdminService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  // ── Lecture ────────────────────────────────────────────────────────────────

  it('getStats() GETs /api/admin/stats avec Authorization', () => {
    service.getStats().subscribe();
    const req = httpMock.expectOne(`${BASE}/stats`);
    expect(req.request.method).toBe('GET');
    expect(req.request.headers.get('Authorization')).toBe('Bearer admin-jwt');
    req.flush({ success: true, data: {} });
  });

  it('getTracks() GETs /api/admin/tracks avec param status', () => {
    service.getTracks('approved').subscribe();
    const req = httpMock.expectOne(r => r.url === `${BASE}/tracks`);
    expect(req.request.params.get('status')).toBe('approved');
    req.flush({ success: true, data: { tracks: [], pending_count: 0, approved_count: 0, exclusive_count: 0 } });
  });

  it('getUsers() GETs /api/admin/users avec param user_type', () => {
    service.getUsers('beatmakers').subscribe();
    const req = httpMock.expectOne(r => r.url === `${BASE}/users`);
    expect(req.request.params.get('user_type')).toBe('beatmakers');
    req.flush({ success: true, data: { users: [], counts: {} } });
  });

  it('getEngineers() GETs /api/admin/engineers', () => {
    service.getEngineers().subscribe();
    const req = httpMock.expectOne(`${BASE}/engineers`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: {} });
  });

  it('getContracts() GETs /api/admin/contracts', () => {
    service.getContracts().subscribe();
    const req = httpMock.expectOne(`${BASE}/contracts`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: {} });
  });

  it('getCategories() GETs /api/admin/categories', () => {
    service.getCategories().subscribe();
    const req = httpMock.expectOne(`${BASE}/categories`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { categories: [] } });
  });

  // ── Tracks CUD ─────────────────────────────────────────────────────────────

  it('approveTrack() POSTs à /api/admin/tracks/:id/approve', () => {
    service.approveTrack(5).subscribe();
    const req = httpMock.expectOne(`${BASE}/tracks/5/approve`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  it('rejectTrack() DELETE à /api/admin/tracks/:id', () => {
    service.rejectTrack(5).subscribe();
    const req = httpMock.expectOne(`${BASE}/tracks/5`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  it('editTrack() PUT à /api/admin/tracks/:id', () => {
    service.editTrack(5, { title: 'Nouveau Titre' }).subscribe();
    const req = httpMock.expectOne(`${BASE}/tracks/5`);
    expect(req.request.method).toBe('PUT');
    expect(req.request.body.title).toBe('Nouveau Titre');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' } });
  });

  // ── Users CUD ──────────────────────────────────────────────────────────────

  it('toggleUserStatus() POSTs à /api/admin/users/:id/toggle-status', () => {
    service.toggleUserStatus(3).subscribe();
    const req = httpMock.expectOne(`${BASE}/users/3/toggle-status`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' }, data: { account_status: 'active' } });
  });

  it('addTrackTokens() POSTs le bon nombre de tokens', () => {
    service.addTrackTokens(3, 5).subscribe();
    const req = httpMock.expectOne(`${BASE}/users/3/add-track-tokens`);
    expect(req.request.body.tokens).toBe(5);
    req.flush({ success: true, feedback: { level: 'success', message: '' }, data: { upload_track_tokens: 5 } });
  });

  it('togglePremium() POSTs à /api/admin/users/:id/toggle-premium', () => {
    service.togglePremium(3).subscribe();
    const req = httpMock.expectOne(`${BASE}/users/3/toggle-premium`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: '' }, data: { is_premium: true } });
  });

  it('setPlan() POSTs le palier au bon endpoint', () => {
    service.setPlan(3, 'pro_structure').subscribe();
    const req = httpMock.expectOne(`${BASE}/users/3/set-plan`);
    expect(req.request.body.plan).toBe('pro_structure');
    req.flush({ success: true, feedback: { level: 'success', message: '' }, data: { is_premium: true, subscription_plan: 'pro_structure', premium_expires_at: null } });
  });

  it('deleteUser() DELETE à /api/admin/users/:id', () => {
    service.deleteUser(3).subscribe();
    const req = httpMock.expectOne(`${BASE}/users/3`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  // ── Engineers CUD ──────────────────────────────────────────────────────────

  it('certifyEngineer() POSTs à /api/admin/engineers/:id/certify', () => {
    service.certifyEngineer(7).subscribe();
    const req = httpMock.expectOne(`${BASE}/engineers/7/certify`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  it('revokeEngineer() POSTs à /api/admin/engineers/:id/revoke', () => {
    service.revokeEngineer(7).subscribe();
    const req = httpMock.expectOne(`${BASE}/engineers/7/revoke`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  // ── Search ─────────────────────────────────────────────────────────────────

  it('searchUsers() GETs /api/admin/users/search avec q', () => {
    service.searchUsers('john').subscribe();
    const req = httpMock.expectOne(r => r.url === `${BASE}/users/search`);
    expect(req.request.params.get('q')).toBe('john');
    req.flush({ success: true, feedback: { level: 'info', message: '' }, data: { users: [] } });
  });

  it('searchTracks() GETs /api/admin/tracks/search avec q', () => {
    service.searchTracks('trap').subscribe();
    const req = httpMock.expectOne(r => r.url === `${BASE}/tracks/search`);
    expect(req.request.params.get('q')).toBe('trap');
    req.flush({ success: true, feedback: { level: 'info', message: '' }, data: { tracks: [] } });
  });

  // ── Toplines ────────────────────────────────────────────────────────────────

  it('getToplines() GETs /api/admin/toplines avec pagination', () => {
    service.getToplines(2, 'published').subscribe();
    const req = httpMock.expectOne(r => r.url === `${BASE}/toplines`);
    expect(req.request.params.get('page')).toBe('2');
    expect(req.request.params.get('published')).toBe('published');
    req.flush({ success: true, feedback: { level: 'info', message: '' }, data: { toplines: [], total: 0, pages: 0, page: 2 } });
  });

  it('deleteTopline() DELETE à /api/admin/toplines/:id', () => {
    service.deleteTopline(11).subscribe();
    const req = httpMock.expectOne(`${BASE}/toplines/11`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  // ── Support email ───────────────────────────────────────────────────────────

  it('sendSupportEmail() POSTs à /api/admin/send-support-email', () => {
    const payload = { email: 'a@b.com', name: 'Alice', subject: 'Aide', body: 'Bonjour' };
    service.sendSupportEmail(payload).subscribe();
    const req = httpMock.expectOne(`${BASE}/send-support-email`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body.email).toBe('a@b.com');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  // ── Categories & Tags ───────────────────────────────────────────────────────

  it('createCategory() POSTs à /api/admin/categories', () => {
    service.createCategory('Ambiance', '#ff0000').subscribe();
    const req = httpMock.expectOne(`${BASE}/categories`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ name: 'Ambiance', color: '#ff0000' });
    req.flush({ success: true, feedback: { level: 'success', message: '' }, data: { category: { id: 1, name: 'Ambiance', color: '#ff0000', description: null, tags: [] } } });
  });

  it('deleteCategory() DELETE à /api/admin/categories/:id', () => {
    service.deleteCategory(2).subscribe();
    const req = httpMock.expectOne(`${BASE}/categories/2`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  it('createTag() POSTs à /api/admin/tags', () => {
    service.createTag('trap', 1).subscribe();
    const req = httpMock.expectOne(`${BASE}/tags`);
    expect(req.request.body).toEqual({ name: 'trap', category_id: 1 });
    req.flush({ success: true, feedback: { level: 'success', message: '' }, data: { tag: { id: 5, name: 'trap' } } });
  });

  it('deleteTag() DELETE à /api/admin/tags/:id', () => {
    service.deleteTag(5).subscribe();
    const req = httpMock.expectOne(`${BASE}/tags/5`);
    expect(req.request.method).toBe('DELETE');
    req.flush({ success: true, feedback: { level: 'success', message: '' } });
  });

  // ── URL builder ─────────────────────────────────────────────────────────────

  it('getAdminInvoiceUrl() retourne l\'URL correcte pour un achat', () => {
    expect(service.getAdminInvoiceUrl('purchase', 3)).toBe('/api/admin/invoices/purchase/3');
  });

  it('getAdminInvoiceUrl() retourne l\'URL correcte pour un statement', () => {
    expect(service.getAdminInvoiceUrl('purchase-statement', 3)).toBe('/api/admin/invoices/purchase/3/statement');
  });

  it('getAdminInvoiceUrl() retourne l\'URL correcte pour un mixmaster', () => {
    expect(service.getAdminInvoiceUrl('mixmaster', 7)).toBe('/api/admin/invoices/mixmaster/7');
  });
});
