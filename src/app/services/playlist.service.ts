import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ApiResponse } from './topline.service';
import { Track } from './track.service';

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Playlist {
  id:                 number;
  title:              string;
  image_file:         string | null;
  image_thumb?:       string | null;
  track_count:        number;
  beatmaker_username: string;
  created_at:         string | null;
}

export interface PlaylistDetail extends Playlist {
  tracks: Track[];
}

// ── Service ───────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class PlaylistService {

  private http    = inject(HttpClient);
  private baseUrl = `${environment.apiUrl}/api/playlists`;

  getMyPlaylists(): Observable<ApiResponse<Playlist[]>> {
    return this.http.get<ApiResponse<Playlist[]>>(`${this.baseUrl}/my`);
  }

  getPlaylist(id: number): Observable<ApiResponse<PlaylistDetail>> {
    return this.http.get<ApiResponse<PlaylistDetail>>(`${this.baseUrl}/${id}`);
  }

  createPlaylist(formData: FormData): Observable<ApiResponse<Playlist>> {
    return this.http.post<ApiResponse<Playlist>>(this.baseUrl, formData);
  }

  updatePlaylist(id: number, formData: FormData): Observable<ApiResponse<Playlist>> {
    return this.http.put<ApiResponse<Playlist>>(`${this.baseUrl}/${id}`, formData);
  }

  deletePlaylist(id: number): Observable<ApiResponse<void>> {
    return this.http.delete<ApiResponse<void>>(`${this.baseUrl}/${id}`);
  }

  addTrack(playlistId: number, trackId: number): Observable<ApiResponse<void>> {
    return this.http.post<ApiResponse<void>>(
      `${this.baseUrl}/${playlistId}/tracks`,
      { track_id: trackId },
    );
  }

  removeTrack(playlistId: number, trackId: number): Observable<ApiResponse<void>> {
    return this.http.delete<ApiResponse<void>>(
      `${this.baseUrl}/${playlistId}/tracks/${trackId}`,
    );
  }

  getByBeatmaker(username: string): Observable<ApiResponse<Playlist[]>> {
    return this.http.get<ApiResponse<Playlist[]>>(`${this.baseUrl}/by-beatmaker/${username}`);
  }

  getContaining(trackId: number, username: string): Observable<ApiResponse<number[]>> {
    return this.http.get<ApiResponse<number[]>>(
      `${this.baseUrl}/containing/${trackId}/by/${username}`,
    );
  }
}
