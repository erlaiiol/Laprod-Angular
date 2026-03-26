// ─────────────────────────────────────────────────────────────────────────────
// Un "service" Angular est une classe dont le rôle est de centraliser
// la logique réutilisable — ici : toutes les requêtes HTTP vers Flask.
// Les composants (HomeComponent, etc.) l'injectent et appellent ses méthodes
// sans jamais manipuler HttpClient directement.
// ─────────────────────────────────────────────────────────────────────────────

import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
//        │              └── construit les query strings (?bpm_min=80&style=Trap)
//        └── service Angular qui effectue les requêtes HTTP (fetch côté navigateur)

import { Observable, tap } from 'rxjs';
// Observable = "promesse améliorée" de RxJS.
// Représente une valeur qui arrivera dans le futur (la réponse HTTP).
// Le composant s'y abonne avec .subscribe().

import { environment } from '../../environments/environment';
// environment.ts (dev) → { apiUrl: 'http://localhost:5000' }
// Permet de changer l'URL entre dev et prod sans toucher au code.


// ─────────────────────────────────────────────────────────────────────────────
// INTERFACES TYPESCRIPT
// Décrivent la "forme" des données JSON reçues de Flask.
// TypeScript peut ainsi vérifier à la compilation que le code utilise
// correctement les champs retournés par l'API.
// ─────────────────────────────────────────────────────────────────────────────

// Correspond au dict Python construit dans get_tracks() → tracks_data.append({...})
export interface Track {
  id:            number;
  title:         string;
  composer_user: { username: string };  // objet imbriqué  ← {'username': ...}
  audio_file:    string;
  image_file:    string;
  bpm:           number;
  key:           string;
  style:         string;
  price_mp3:     number;
  tags:          { name: string; category: string; color: string }[];  // tableau d'objets
  is_approved:   boolean;
}

// Correspond au JSON global retourné par jsonify({...}) dans get_tracks()
export interface TracksResponse {
  success: boolean;
  data: {
    tracks:     Track[];
    pagination: {
      page:     number;
      per_page: number;
      total:    number;
      pages:    number;
    };
  };
}

// Paramètres de filtre optionnels → querystring Flask (?search=trap&bpm_min=80)
// Chaque champ ici correspond à un request.args.get('...') dans get_tracks()
export interface TrackFilters {
  search?:   string;
  bpm_min?:  number;
  bpm_max?:  number;
  keys?:     string;
  styles?:   string; 
  tags?:     string;
  page?:     number;
  per_page?: number;
}


// ─────────────────────────────────────────────────────────────────────────────
// @Injectable({ providedIn: 'root' })
// Enregistre ce service dans l'injecteur global de l'application.
// → une seule instance partagée par tous les composants (singleton).
// ─────────────────────────────────────────────────────────────────────────────

@Injectable({ providedIn: 'root' })
export class TrackService {

  // URL de base du blueprint Flask tracks_api_bp (url_prefix='/tracks')
  // → 'http://localhost:5000/tracks'
  private tracksApiUrl = `${environment.apiUrl}/tracks`;

  constructor(private http: HttpClient) {}
  // Angular injecte HttpClient automatiquement (déclaré dans app.config.ts).


  // ── GET /tracks/tracks ──────────────────────────────────────────────────
  // Correspond à la route @tracks_api_bp.route('/tracks') dans tracks_api.py
  // Flask reçoit les filtres en query string et retourne le JSON paginé.

  getTracks(filters?: TrackFilters): Observable<TracksResponse> {

    // HttpParams construit le query string de façon sécurisée.
    // Ex : filters = { bpm_min: 80, style: 'Trap' }
    //   → ?bpm_min=80&style=Trap  (ajouté à l'URL automatiquement)
    let params = new HttpParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params = params.set(key, value.toString());
        }
      });
    }

    // http.get<T>(url, options) envoie une requête GET et retourne
    // un Observable qui émettra un objet de type T (ici TracksResponse).
    // Rien n'est envoyé tant que le composant ne s'abonne pas (.subscribe()).
    return this.http.get<TracksResponse>(`${this.tracksApiUrl}/tracks`, { params })
    .pipe(tap(data=> console.log('TrackService called getTracks()', data)));
  }


  // ── GET /tracks/track/:id ───────────────────────────────────────────────
  // Correspond à @tracks_api_bp.route('/track/<int:track_id>') dans tracks_api.py

  getTrack(trackId: number): Observable<{ success: boolean; data: { track: Track } }> {
    return this.http.get<{ success: boolean; data: { track: Track } }>(
      `${this.tracksApiUrl}/track/${trackId}`
    ).pipe(tap(data => console.log('TrackService called getTrack()', data)));
  }


  // ── Utilitaire : URL d'un fichier statique Flask ────────────────────────
  // Flask sert ses fichiers statiques via /static/<path>
  // track.image_file = "images/tracks/mon_beat.png"
  // → "http://localhost:5000/static/images/tracks/mon_beat.png"

  getStaticFileUrl(filename: string): string {
    return `${environment.apiUrl}/static/${filename}`;
  }


  // ── Utilitaire : assombrir une couleur hexadécimale ──────────────────────
  // Traduction de darken_color() (app.py) en TypeScript.
  //
  // Principe : chaque canal RGB est multiplié par `factor`.
  //   factor = 0.15 → très foncé  (fond des tags)
  //   factor = 0.35 → intermédiaire (bordure des tags)
  //   factor = 1.00 → couleur d'origine
  //
  // Exemple : '#e74c3c' (rouge vif) + factor 0.15
  //   R: 0xe7 = 231 → 231 * 0.15 ≈  34 → 0x22
  //   G: 0x4c =  76 →  76 * 0.15 ≈  11 → 0x0b
  //   B: 0x3c =  60 →  60 * 0.15 ≈   9 → 0x09
  //   → '#220b09'

  darkenColor(hex: string, factor = 0.15): string {
    if (!hex || typeof hex !== 'string') return '#1a1a1a';

    hex = hex.replace('#', '');
    if (hex.length !== 6) return '#1a1a1a';

    try {
      // parseInt(str, 16) : convertit une chaîne hexadécimale en entier
      // Math.floor()      : équivalent de int() Python (troncature)
      // .toString(16)     : repasse en hex
      // .padStart(2, '0') : garantit 2 chiffres (ex : 9 → '09')
      const r = Math.floor(parseInt(hex.slice(0, 2), 16) * factor);
      const g = Math.floor(parseInt(hex.slice(2, 4), 16) * factor);
      const b = Math.floor(parseInt(hex.slice(4, 6), 16) * factor);
      return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
    } catch {
      return '#1a1a1a';
    }
  }

}
