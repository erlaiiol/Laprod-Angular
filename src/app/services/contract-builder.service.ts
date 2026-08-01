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
export type PartyInviteStatus = 'none' | 'pending' | 'signed' | 'declined';
export type ContractSignatureStatus = 'not_sent' | 'pending' | 'declined' | 'signed';
export type ViewerRole = 'owner' | 'recipient';

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
  // depuis un lien roster, ou résolu à l'envoi d'une invitation à signer).
  linked_user_id?:  number | null;
  // Signature en ligne — jamais renvoyés en écriture, uniquement en lecture.
  invite_status?:   PartyInviteStatus;
  invited_at?:      string | null;
  signed_at?:       string | null;
  signature_name?:  string | null;
  declined_at?:     string | null;
}

export interface ContractValue {
  clause_id:  number;
  is_enabled: boolean;
  value:      any;
}

export interface ContractSummary {
  id:                number;
  title:             string;
  contract_type:     ContractType;
  status:            ContractStatus;
  signature_status:  ContractSignatureStatus;
  created_at:        string;
  updated_at:        string | null;
}

export interface ContractDetail extends ContractSummary {
  pdf_file:     string | null;
  parties:      ContractParty[];
  values:       ContractValue[];
  can_edit?:    boolean;
  viewer_role?: ViewerRole;
  my_party_id?: number | null;
}

/** Ligne d'inbox/outbox de signature — voir serializers.contract_share() côté backend. */
export interface ContractShareEntry {
  id:                number;
  title:             string;
  contract_type:     ContractType;
  signature_status:  ContractSignatureStatus;
  role:              'sender' | 'recipient';
  created_at:        string;
  updated_at:        string | null;
  // role === 'sender'
  invited_count?:    number;
  pending_count?:    number;
  signed_count?:     number;
  declined_count?:   number;
  // role === 'recipient'
  counterpart?:      { id: number; username: string; profile_image: string | null };
  my_party_role?:    string;
  my_invite_status?: PartyInviteStatus;
  my_signed_at?:     string | null;
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

  /** Brouillons uniquement — un contrat finalisé (PDF déjà généré) refuse côté serveur. */
  deleteContract(id: number): Observable<ApiResponse> {
    return this.http.delete<any>(`${this.base}/contracts/${id}`, { headers: this.headers });
  }

  // ── Signature en ligne ────────────────────────────────────────────────────

  /** `identifier` : pseudo ou email. Si aucun compte ne correspond mais que
   * c'est un email valide, le backend envoie une invitation par email à un
   * futur inscrit plutôt que de renvoyer une erreur 404. */
  invitePartyToSign(contractId: number, partyId: number, identifier: string): Observable<ApiResponse<{ party: ContractParty; signature_status: ContractSignatureStatus }>> {
    return this.http.post<any>(
      `${this.base}/contracts/${contractId}/parties/${partyId}/invite`,
      { identifier },
      { headers: this.headers },
    );
  }

  cancelPartyInvite(contractId: number, partyId: number): Observable<ApiResponse<{ party: ContractParty; signature_status: ContractSignatureStatus }>> {
    return this.http.post<any>(
      `${this.base}/contracts/${contractId}/parties/${partyId}/cancel-invite`,
      {},
      { headers: this.headers },
    );
  }

  getInbox(): Observable<ApiResponse<{ sent: ContractShareEntry[]; received: ContractShareEntry[] }>> {
    return this.http.get<any>(`${this.base}/inbox`, { headers: this.headers });
  }

  signContract(contractId: number, signatureName: string, consent: boolean): Observable<ApiResponse<{ contract: ContractDetail }>> {
    return this.http.post<any>(
      `${this.base}/contracts/${contractId}/sign`,
      { signature_name: signatureName, consent },
      { headers: this.headers },
    );
  }

  declineContract(contractId: number): Observable<ApiResponse<{ contract: ContractDetail }>> {
    return this.http.post<any>(`${this.base}/contracts/${contractId}/decline`, {}, { headers: this.headers });
  }

  /** Public — aperçu d'une invitation email avant connexion/inscription. */
  getInvitePreview(token: string): Observable<ApiResponse<{ title: string; inviter_username: string; email: string }>> {
    return this.http.get<any>(`${this.base}/invite/preview`, { params: { token } });
  }

  /** Rattache le compte connecté à l'invitation portée par le token (lien email). */
  resolveInvite(token: string): Observable<ApiResponse<{ contract_id: number }>> {
    return this.http.post<any>(`${this.base}/invite/resolve`, { token }, { headers: this.headers });
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
