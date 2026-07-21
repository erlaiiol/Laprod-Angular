import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

// ── Types ─────────────────────────────────────────────────────────────────────

export type ClauseType =
  | 'text' | 'textarea' | 'number' | 'percentage'
  | 'toggle' | 'toggle_with_details'
  | 'select' | 'date' | 'date_range'
  | 'territory' | 'duration' | 'multi_toggle';

export type PartyType = 'physical' | 'company';
export type ContractStatus = 'draft' | 'final';
export type ContractType = 'exploitation' | 'performance' | 'management';

// ── DTOs ──────────────────────────────────────────────────────────────────────

export interface ClauseDTO {
  id:                    number;
  group_id:              number;
  name:                  string;
  description:           string | null;
  tooltip_short:         string | null;
  tooltip_long:          string | null;
  clause_type:           ClauseType;
  options:               string[] | null;
  default_value:         any;
  is_required:           boolean;
  is_enabled_by_default: boolean;
  sort_order:            number;
  is_active:             boolean;
  legal_reference:       string | null;
  example_text:          string | null;
  tooltip_plain:         string | null;
}

export interface ClauseGroupDTO {
  id:            number;
  name:          string;
  contract_type?: ContractType;
  description: string | null;
  tooltip:     string | null;
  sort_order:  number;
  is_active:   boolean;
  clauses:     ClauseDTO[];
}

export interface ContractParty {
  id?:              number;
  party_type:       PartyType;
  sort_order:       number;
  role:             string;
  // Personne physique
  first_name?:      string | null;
  last_name?:       string | null;
  date_of_birth?:   string | null;
  nationality?:     string | null;
  pseudonym?:       string | null;
  tax_id?:          string | null;
  // Personne morale
  company_name?:    string | null;
  legal_form?:      string | null;
  capital?:         string | null;
  siren?:           string | null;
  siret?:           string | null;
  rcs?:             string | null;
  legal_rep?:       string | null;
  signatory_title?: string | null;
  // Commun
  address?:         string | null;
  email?:           string | null;
  // Lien optionnel vers un compte LaProd réel (contrat de management généré
  // depuis un lien roster). Toujours null pour les contrats exploitation/performance.
  linked_user_id?:  number | null;
}

export interface ContractValue {
  clause_id:  number;
  is_enabled: boolean;
  value:      any;
}

export interface ContractSummary {
  id:            number;
  title:         string;
  contract_type: ContractType;
  status:        ContractStatus;
  created_at:    string;
  updated_at:    string | null;
}

export interface ContractDetail extends ContractSummary {
  pdf_file:  string | null;
  parties:   ContractParty[];
  values:    ContractValue[];
  can_edit?: boolean;
}

export interface UpdateContractPayload {
  title?:   string;
  parties?: ContractParty[];
  values?:  ContractValue[];
}

type ApiResponse<T = unknown> = {
  success:  boolean;
  feedback: { level: string; message: string };
  data?:    T;
};

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class ContractBuilderService {

  private base      = `${environment.apiUrl}/api/contract-builder`;
  private adminBase = `${environment.apiUrl}/api/admin/contract-builder`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  // ── Utilisateur ───────────────────────────────────────────────────────────

  getTemplate(type: ContractType = 'exploitation'): Observable<ApiResponse<{ groups: ClauseGroupDTO[] }>> {
    // Endpoint public (aucune donnée utilisateur) : pas de header requis pour les invités.
    const token = this.auth.getToken();
    const headers = token ? this.headers : undefined;
    return this.http.get<any>(`${this.base}/template`, { headers, params: { type } });
  }

  listContracts(): Observable<ApiResponse<{ contracts: ContractSummary[] }>> {
    return this.http.get<any>(`${this.base}/contracts`, { headers: this.headers });
  }

  getContract(id: number): Observable<ApiResponse<{ contract: ContractDetail }>> {
    return this.http.get<any>(`${this.base}/contracts/${id}`, { headers: this.headers });
  }

  createContract(title: string, type: ContractType = 'exploitation'): Observable<ApiResponse<{ contract: ContractSummary }>> {
    return this.http.post<any>(`${this.base}/contracts`, { title, contract_type: type }, { headers: this.headers });
  }

  updateContract(id: number, payload: UpdateContractPayload): Observable<ApiResponse<{ contract: ContractDetail }>> {
    return this.http.put<any>(`${this.base}/contracts/${id}`, payload, { headers: this.headers });
  }

  generatePdf(id: number): Observable<ApiResponse<{ pdf_url: string }>> {
    return this.http.post<any>(`${this.base}/contracts/${id}/generate`, {}, { headers: this.headers });
  }

  downloadPdf(id: number): Observable<Blob> {
    return this.http.get(`${this.base}/contracts/${id}/download`, {
      headers: this.headers,
      responseType: 'blob',
    });
  }

  // ── Admin — Groupes ───────────────────────────────────────────────────────

  adminGetGroups(type?: ContractType): Observable<ApiResponse<{ groups: ClauseGroupDTO[] }>> {
    const params: Record<string, string> = type ? { type } : {};
    return this.http.get<any>(`${this.adminBase}/groups`, { headers: this.headers, params });
  }

  adminCreateGroup(payload: Partial<ClauseGroupDTO>): Observable<ApiResponse<{ group: ClauseGroupDTO }>> {
    return this.http.post<any>(`${this.adminBase}/groups`, payload, { headers: this.headers });
  }

  adminUpdateGroup(id: number, payload: Partial<ClauseGroupDTO>): Observable<ApiResponse<{ group: ClauseGroupDTO }>> {
    return this.http.put<any>(`${this.adminBase}/groups/${id}`, payload, { headers: this.headers });
  }

  adminDeleteGroup(id: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.adminBase}/groups/${id}`, { headers: this.headers });
  }

  adminReorderGroups(items: { id: number; sort_order: number }[]): Observable<ApiResponse> {
    return this.http.post<any>(`${this.adminBase}/groups/reorder`, items, { headers: this.headers });
  }

  adminGetClauses(groupId: number): Observable<ApiResponse<{ clauses: ClauseDTO[] }>> {
    return this.http.get<any>(`${this.adminBase}/groups/${groupId}/clauses`, { headers: this.headers });
  }

  adminCreateClause(groupId: number, payload: Partial<ClauseDTO>): Observable<ApiResponse<{ clause: ClauseDTO }>> {
    return this.http.post<any>(`${this.adminBase}/groups/${groupId}/clauses`, payload, { headers: this.headers });
  }

  adminUpdateClause(id: number, payload: Partial<ClauseDTO>): Observable<ApiResponse<{ clause: ClauseDTO }>> {
    return this.http.put<any>(`${this.adminBase}/clauses/${id}`, payload, { headers: this.headers });
  }

  adminDeleteClause(id: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.adminBase}/clauses/${id}`, { headers: this.headers });
  }

  adminReorderClauses(items: { id: number; sort_order: number }[]): Observable<ApiResponse> {
    return this.http.post<any>(`${this.adminBase}/clauses/reorder`, items, { headers: this.headers });
  }
}
