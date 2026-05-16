import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { timeout } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

export interface ContractSection {
  title:            string;
  excerpt:          string;
  risk:             'ok' | 'attention' | 'risque' | 'critique';
  explanation:      string;
  legal_reference:  string | null;
  negotiation_tip:  string | null;
}

export interface MissingClause {
  name:        string;
  importance:  'Essentielle' | 'Importante' | 'Recommandée';
  explanation: string;
}

export interface ContractAnalysis {
  contract_type:        string;
  overall_score:        number;
  risk_level:           string;
  summary:              string;
  detected_parties:     { role: string; name: string }[];
  sections:             ContractSection[];
  missing_clauses:      MissingClause[];
  positive_points:      string[];
  career_advice:        string;
  negotiation_checklist: string[];
}

type ApiResponse<T = unknown> = {
  success:  boolean;
  feedback: { level: string; message: string };
  data?:    T;
};

@Injectable({ providedIn: 'root' })
export class ContractAnalyzerService {

  private base = `${environment.apiUrl}/api/contract-analyzer`;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  analyzeContract(file: File): Observable<ApiResponse<{ analysis: ContractAnalysis }>> {
    const fd = new FormData();
    fd.append('contract_pdf', file);
    return this.http
      .post<any>(`${this.base}/analyze`, fd, { headers: this.headers })
      .pipe(timeout(120_000));
  }
}
