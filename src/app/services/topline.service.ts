import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { PublishedTopline } from './track.service';

@Injectable({ providedIn: 'root' })
export class ToplineService {

  private http = inject(HttpClient);
  private apiUrl = `${environment.apiUrl}/toplines`;

  getTrackToplines(trackId: number): Observable<{ success: boolean; data: { toplines: PublishedTopline[] } }> {
    return this.http.get<any>(`${this.apiUrl}/track/${trackId}`);
  }

  getMyToplines(trackId: number): Observable<{ success: boolean; data: { toplines: PublishedTopline[] } }> {
    return this.http.get<any>(`${this.apiUrl}/my/${trackId}`);
  }

  uploadTopline(formData: FormData): Observable<{
    success: boolean;
    data?: { topline: PublishedTopline & { merged_file: string } };
    feedback?: { level: string; message: string };
  }> {
    return this.http.post<any>(`${this.apiUrl}/upload`, formData);
  }

  publishTopline(id: number): Observable<{ success: boolean; feedback?: { level: string; message: string }; data?: { topline: PublishedTopline } }> {
    return this.http.post<any>(`${this.apiUrl}/${id}/publish`, {});
  }

  deleteTopline(id: number): Observable<{ success: boolean; feedback?: { level: string; message: string } }> {
    return this.http.delete<any>(`${this.apiUrl}/${id}`);
  }

}
