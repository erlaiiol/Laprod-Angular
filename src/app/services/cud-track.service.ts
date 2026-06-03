import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Tag } from './tags.service';

export interface TrackData {
  title: string;
  bpm: number;
  key: string;
  style: string;
  price_mp3: number;
  price_wav: number;
  price_stems: number;
  sacem_percentage_composer?: number;
  tag_ids?: string;
  playlist_ids?: string;
  file_mp3?: File;
  file_wav?: File;
  file_image?: File;
  file_stems?: File;
  contract_price_exclusive?:       number | null;
  contract_price_duration_3y?:     number | null;
  contract_price_duration_5y?:     number | null;
  contract_price_duration_10y?:    number | null;
  contract_price_lifetime?:        number | null;
  contract_price_mechanical?:      number | null;
  contract_price_public_show?:     number | null;
  contract_price_arrangement?:     number | null;
  contract_price_territory_eu?:    number | null;
  contract_price_territory_world?: number | null;
}

export interface UploadResponse {
  success:   boolean;
  feedback?: { level: string; message: string };
  data?:     { job_id: string, title: string, image_url: string | null };
}

export interface EditResponse {
  success: boolean;
  message?: string;
  error?: string;
  data?: {job_id : string};
}



@Injectable({
  providedIn: 'root'
})
export class CudTrackService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  /**
   * Upload un nouveau track
   */
  postTrack(trackData: TrackData): Observable<UploadResponse> {
    const formData = new FormData();

    // Ajouter les champs texte
    formData.append('title', trackData.title);
    formData.append('bpm', trackData.bpm.toString());
    formData.append('key', trackData.key);
    formData.append('style', trackData.style);
    formData.append('price_mp3', trackData.price_mp3.toString());
    formData.append('price_wav', trackData.price_wav.toString());
    formData.append('price_stems', trackData.price_stems.toString());
    formData.append('sacem_percentage_composer', trackData.sacem_percentage_composer?.toString() || '0');

    if (trackData.tag_ids) {
      formData.append('tag_ids', trackData.tag_ids);
    }

    if (trackData.playlist_ids) {
      formData.append('playlist_ids', trackData.playlist_ids);
    }

    const contractFields: (keyof TrackData)[] = [
      'contract_price_exclusive', 'contract_price_duration_3y', 'contract_price_duration_5y',
      'contract_price_duration_10y', 'contract_price_lifetime', 'contract_price_mechanical',
      'contract_price_public_show', 'contract_price_arrangement',
      'contract_price_territory_eu', 'contract_price_territory_world',
    ];
    for (const field of contractFields) {
      const val = trackData[field];
      if (val !== null && val !== undefined) {
        formData.append(field, val.toString());
      }
    }

    // Ajouter les fichiers
    if (trackData.file_mp3) {
    formData.append('file_mp3', trackData.file_mp3);
    }

    if (trackData.file_wav) {
      formData.append('file_wav', trackData.file_wav);
    }

    if (trackData.file_image) {
      formData.append('file_image', trackData.file_image);
    }

    if (trackData.file_stems) {
      formData.append('file_stems', trackData.file_stems);
    }

    return this.http.post<UploadResponse>(`${this.apiUrl}/api/tracks/post`, formData);
  }

  putTrack(trackId: number, trackData: TrackData): Observable<EditResponse> {
    const formData = new FormData();

    // Ajouter les champs texte
    formData.append('title', trackData.title);
    formData.append('bpm', trackData.bpm.toString());
    formData.append('key', trackData.key);
    formData.append('style', trackData.style);
    formData.append('price_mp3', trackData.price_mp3.toString());
    formData.append('price_wav', trackData.price_wav.toString());
    formData.append('price_stems', trackData.price_stems.toString());

    if (trackData.tag_ids) {
      formData.append('tag_ids', trackData.tag_ids);
    }

    const contractFields: (keyof TrackData)[] = [
      'contract_price_exclusive', 'contract_price_duration_3y', 'contract_price_duration_5y',
      'contract_price_duration_10y', 'contract_price_lifetime', 'contract_price_mechanical',
      'contract_price_public_show', 'contract_price_arrangement',
      'contract_price_territory_eu', 'contract_price_territory_world',
    ];
    for (const field of contractFields) {
      const val = trackData[field];
      if (val !== null && val !== undefined) {
        formData.append(field, val.toString());
      }
    }

    if (trackData.file_wav) {
      formData.append('file_wav', trackData.file_wav);
    }

    if (trackData.file_image) {
      formData.append('file_image', trackData.file_image);
    }

    if (trackData.file_stems) {
      formData.append('file_stems', trackData.file_stems);
    }

    return this.http.put<EditResponse>(`${this.apiUrl}/api/tracks/put/${trackId}`, formData);
  }

  deleteTrack(trackId: number): Observable<EditResponse> {
    return this.http.delete<EditResponse>(`${this.apiUrl}/api/tracks/delete/${trackId}`);
  }



  /**
   * Récupère les options disponibles pour l'upload (clés, styles, tags)
   */
  getUploadOptions(): Observable<{
    success: boolean;
    keys: string[];
    styles: string[];
    tags: Tag [];
  }> {
    return this.http.get<{
      success: boolean;
      keys: string[];
      styles: string[];
      tags: Tag [];
    }>(`${this.apiUrl}/api/filters/tags/all`);
  }
}