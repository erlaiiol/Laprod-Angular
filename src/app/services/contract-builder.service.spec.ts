import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { ContractBuilderService, ClauseDTO, ClauseGroupDTO } from './contract-builder.service';
import { environment } from '../../environments/environment';

const BASE_URL = `${environment.apiUrl}/api/contract-builder`;

const mockClause: ClauseDTO = {
  id: 1,
  group_id: 1,
  name: 'Nature juridique',
  description: null,
  tooltip_short: 'Licence ou cession',
  tooltip_long: null,
  clause_type: 'toggle',
  options: null,
  default_value: true,
  is_required: true,
  is_enabled_by_default: true,
  sort_order: 1,
  is_active: true,
  legal_reference: null,
  example_text: null,
  tooltip_plain: 'Vous choisissez ici si vous obtenez un droit temporaire ou définitif.',
};

const mockGroup: ClauseGroupDTO = {
  id: 1,
  name: 'Dispositions générales',
  description: null,
  tooltip: null,
  sort_order: 1,
  is_active: true,
  clauses: [mockClause],
};

describe('ContractBuilderService', () => {
  let service: ContractBuilderService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        ContractBuilderService,
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });

    service = TestBed.inject(ContractBuilderService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  // -- getTemplate() --

  it('getTemplate() GETs /api/contract-builder/template', () => {
    service.getTemplate().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/template`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { groups: [mockGroup] } });
  });

  it('getTemplate() returns groups with clauses including tooltip_plain', () => {
    let groups: ClauseGroupDTO[] | undefined;
    service.getTemplate().subscribe((res) => {
      groups = res.data?.groups;
    });

    httpMock.expectOne(`${BASE_URL}/template`).flush({
      success: true,
      data: { groups: [mockGroup] },
    });

    expect(groups).toHaveLength(1);
    expect(groups![0].clauses[0].tooltip_plain).toBeTruthy();
  });

  // -- listContracts() --

  it('listContracts() GETs /api/contract-builder/contracts', () => {
    service.listContracts().subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/contracts`);
    expect(req.request.method).toBe('GET');
    req.flush({ success: true, data: { contracts: [] } });
  });

  // -- createContract() --

  it('createContract() POSTs title to /api/contract-builder/contracts', () => {
    service.createContract('Mon contrat test').subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/contracts`);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ title: 'Mon contrat test' });
    req.flush({ success: true, data: { contract: { id: 42, title: 'Mon contrat test' } } });
  });

  // -- updateContract() --

  it('updateContract() PUTs payload to /api/contract-builder/contracts/:id', () => {
    const payload = { parties: [], values: [] };
    service.updateContract(42, payload as any).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/contracts/42`);
    expect(req.request.method).toBe('PUT');
    req.flush({ success: true, data: { contract: { id: 42 } } });
  });

  // -- generatePdf() --

  it('generatePdf() POSTs to contracts/:id/generate', () => {
    service.generatePdf(42).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/contracts/42/generate`);
    expect(req.request.method).toBe('POST');
    req.flush({ success: true, data: { pdf_url: '/contracts/42.pdf' } });
  });

  // -- downloadPdf() --

  it('downloadPdf() GETs contracts/:id/download as blob', () => {
    service.downloadPdf(42).subscribe();

    const req = httpMock.expectOne(`${BASE_URL}/contracts/42/download`);
    expect(req.request.method).toBe('GET');
    expect(req.request.responseType).toBe('blob');
    req.flush(new Blob(['%PDF-1.4'], { type: 'application/pdf' }));
  });
});
