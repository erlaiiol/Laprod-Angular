import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

export interface UserTrack {
  id:            number;
  title:         string;
  bpm:           number;
  key:           string;
  style:         string | null;
  image_file:    string;
  stream_url:    string;
  price_mp3:     number | null;
  price_wav:     number | null;
  price_stems:   number | null;
  is_approved:   boolean;
  purchase_count: number;
  created_at:    string;
  tags: { id: number; name: string; category: string | null }[];
}

export interface UserProfile {
  id:            number;
  username:      string;
  profile_image: string;
  bio:           string | null;
  instagram:     string | null;
  twitter:       string | null;
  youtube:       string | null;
  soundcloud:    string | null;
  signature:     string | null;
  roles: {
    is_admin:                       boolean;
    is_artist:                      boolean;
    is_beatmaker:                   boolean;
    is_mix_engineer:                boolean;
    is_mixmaster_engineer:          boolean;
    is_certified_producer_arranger: boolean;
  };
  created_at: string;
  tracks:     UserTrack[];
  // Propriétaire uniquement
  email?:     string;
  oauth_provider?: string | null;
  has_password?:  boolean;
  mixmaster?: {
    reference_price: number | null;
    price_min:       number | null;
    bio:             string | null;
    sample_submitted: boolean;
  };
  is_certified_producer_arranger?:    boolean;
  producer_arranger_request_submitted?: boolean;
}

type ProfileResponse = {
  success: boolean;
  data?: { user: UserProfile };
  feedback?: { level: string; message: string };
};

type EditProfileResponse = {
  success: boolean;
  feedback: { level: string; message: string };
  data?: {
    user: Partial<UserProfile>;
    next: string | null;
  };
};

type SecurityResponse = {
  success: boolean;
  feedback: { level: string; message: string };
  data?: { username?: string; has_password?: boolean };
};

type ContactResponse = {
  success: boolean;
  feedback: { level: string; message: string };
};

@Injectable({ providedIn: 'root' })
export class UserService {

  private base = environment.apiUrl;

  constructor(private http: HttpClient, private auth: AuthService) {}

  private get headers() {
    return { Authorization: `Bearer ${this.auth.getToken()}` };
  }

  // ── Profil public ─────────────────────────────────────────────────────────
  getProfile(username: string): Observable<ProfileResponse> {
    return this.http.get<ProfileResponse>(`${this.base}/users/${username}`, {
      headers: this.headers,
    });
  }

  // ── Édition générale (multipart pour la photo) ────────────────────────────
  updateProfile(formData: FormData): Observable<EditProfileResponse> {
    return this.http.put<EditProfileResponse>(
      `${this.base}/users/edit-profile`,
      formData,
      { headers: this.headers },
    );
  }

  // ── Sécurité (JSON) ───────────────────────────────────────────────────────
  updateSecurity(payload: {
    current_password?: string;
    new_username?: string;
    new_password?: string;
    new_password_confirm?: string;
    new_email?: string;
    set_password?: string;
    set_password_confirm?: string;
  }): Observable<SecurityResponse> {
    return this.http.put<SecurityResponse>(
      `${this.base}/users/edit-profile/security`,
      payload,
      { headers: this.headers },
    );
  }

  // ── Contact ───────────────────────────────────────────────────────────────
  sendContact(subject: string, message: string, ref = ''): Observable<ContactResponse> {
    return this.http.post<ContactResponse>(
      `${this.base}/contact`,
      { subject, message, ref },
      { headers: this.headers },
    );
  }
}
