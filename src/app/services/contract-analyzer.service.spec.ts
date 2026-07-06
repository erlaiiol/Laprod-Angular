import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';

import { ContractAnalyzerService } from './contract-analyzer.service';
import { AuthService } from './auth.service';
import { environment } from '../../environments/environment';

const BASE = `${environment.apiUrl}/api/contract-analyzer`;

const mockAnalysis = {
  contract_type: 'Label',
  overall_score: 72,
  risk_level: 'Moyen',
  summary: 'Contrat équilibré',
  detected_parties: [],
  critical_articles: [],
  sections: [],
  missing_clauses: [],
  positive_points: [],
  career_advice: 'OK',
  negotiation_checklist: [],
};

describe('ContractAnalyzerService', () => {
  let service: ContractAnalyzerService;
  let httpMock: HttpTestingController;

  const authStub = { getToken: () => 'admin-token' };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ContractAnalyzerService,
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: AuthService, useValue: authStub },
      ],
    });
    service  = TestBed.inject(ContractAnalyzerService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => expect(service).toBeTruthy());

  it('analyzeContract() POSTs à /api/contract-analyzer/analyze', () => {
    const file = new File(['%PDF'], 'contrat.pdf', { type: 'application/pdf' });
    service.analyzeContract(file).subscribe();
    const req = httpMock.expectOne(`${BASE}/analyze`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' }, data: { analysis: mockAnalysis } });
  });

  it('analyzeContract() envoie le fichier dans un FormData sous la clé contract_pdf', () => {
    const file = new File(['%PDF'], 'contrat.pdf', { type: 'application/pdf' });
    service.analyzeContract(file).subscribe();
    const req = httpMock.expectOne(`${BASE}/analyze`);
    const fd: FormData = req.request.body;
    expect(fd.get('contract_pdf')).toBeTruthy();
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' }, data: { analysis: mockAnalysis } });
  });

  it('analyzeContract() envoie le header Authorization', () => {
    const file = new File(['%PDF'], 'contrat.pdf', { type: 'application/pdf' });
    service.analyzeContract(file).subscribe();
    const req = httpMock.expectOne(`${BASE}/analyze`);
    expect(req.request.headers.get('Authorization')).toBe('Bearer admin-token');
    req.flush({ success: true, feedback: { level: 'success', message: 'OK' }, data: { analysis: mockAnalysis } });
  });
});
