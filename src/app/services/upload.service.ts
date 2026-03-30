import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Tag } from './tags.service';

export interface UploadTrackData {
  title: string;
  bpm: number;
  key: string;
  style: string;
  price_mp3: number;
  price_wav: number;
  price_stems: number;
  sacem_percentage_composer: number;
  tag_ids?: string; // IDs des tags séparés par des virgules
  file_mp3: File;
  file_wav?: File;
  file_image?: File;
  file_stems?: File;
}

export interface UploadResponse {
  success: boolean;
  message?: string;
  error?: string;
  track?: any; // Même structure que Track
}

@Injectable({
  providedIn: 'root'
})
export class UploadService {
  private apiUrl = environment.apiUrl;

  constructor(private http: HttpClient) {}

  /**
   * Upload un nouveau track
   */
  uploadTrack(trackData: UploadTrackData): Observable<UploadResponse> {
    const formData = new FormData();

    // Ajouter les champs texte
    formData.append('title', trackData.title);
    formData.append('bpm', trackData.bpm.toString());
    formData.append('key', trackData.key);
    formData.append('style', trackData.style);
    formData.append('price_mp3', trackData.price_mp3.toString());
    formData.append('price_wav', trackData.price_wav.toString());
    formData.append('price_stems', trackData.price_stems.toString());
    formData.append('sacem_percentage_composer', trackData.sacem_percentage_composer.toString());

    if (trackData.tag_ids) {
      formData.append('tag_ids', trackData.tag_ids);
    }

    // Ajouter les fichiers
    formData.append('file_mp3', trackData.file_mp3);

    if (trackData.file_wav) {
      formData.append('file_wav', trackData.file_wav);
    }

    if (trackData.file_image) {
      formData.append('file_image', trackData.file_image);
    }

    if (trackData.file_stems) {
      formData.append('file_stems', trackData.file_stems);
    }

    return this.http.post<UploadResponse>(`${this.apiUrl}/tracks`, formData);
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
    }>(`${this.apiUrl}/filters/tags/all`);
  }
}