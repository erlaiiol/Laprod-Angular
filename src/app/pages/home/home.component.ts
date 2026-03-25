// ─────────────────────────────────────────────────────────────────────────────
// PAGE HOME
// Rôle : orchestrer. Elle charge les tracks depuis l'API et les distribue
// vers TrackCardComponent. Elle réagit aux filtres posés par Navbar.
// ─────────────────────────────────────────────────────────────────────────────

import { Component, OnInit, signal, effect, inject } from '@angular/core';
//                                          │       └── inject() : alternative moderne au constructeur
//                                          └── effect() : s'exécute quand un signal observé change
import { CommonModule } from '@angular/common';

import { TrackService, Track, TrackFilters } from '../../services/track.service';
import { TrackCardComponent } from '../../components/track-card/track-card.component';
import { FilterStateService, ActiveFilters } from '../../services/filter-state.service';
//                             └── service partagé : Navbar écrit, Home lit


@Component({
  selector: 'app-home',
  standalone: true,
  imports: [CommonModule, TrackCardComponent],
  templateUrl: './home.component.html',
  styleUrls:   ['./home.component.scss']
})
export class HomeComponent implements OnInit {

  tracks  = signal<Track[]>([]);
  loading = signal(true);
  error   = signal<string | null>(null);

  private trackService      = inject(TrackService);
  private filterStateService = inject(FilterStateService);
  // inject() est l'équivalent de "private x: X" dans le constructeur.
  // Il peut être utilisé en dehors du constructeur, pratique ici car
  // effect() doit être créé dans le contexte d'injection (champ de classe).

  constructor() {
    // ── effect() ──────────────────────────────────────────────────────────
    // effect() crée une réaction : Angular appelle cette fonction
    // automatiquement chaque fois qu'un signal LU À L'INTÉRIEUR change.
    //
    // Ici : filterStateService.applied() est lu → Angular observe ce signal.
    // Quand Navbar appelle filterStateService.apply() ou .reset(),
    // applied() s'incrémente → effect() se déclenche → loadTracks() recharge.
    //
    // allowSignalWrites: true est nécessaire car loadTracks() écrit dans
    // des signaux (loading, tracks, error) depuis l'intérieur d'un effect().

    effect(() => {
      this.filterStateService.applied(); // lecture → crée la dépendance
      this.loadTracks();
    }, { allowSignalWrites: true });
  }

  ngOnInit(): void {
    // loadTracks() est déjà appelé par effect() au démarrage
    // (effect() s'exécute une première fois lors de l'initialisation).
    // ngOnInit reste présent pour clarté architecturale.
  }

  loadTracks(): void {
    this.loading.set(true);
    this.error.set(null);

    // Convertit ActiveFilters (format Navbar) → TrackFilters (format API Flask)
    const apiFilters = this.toTrackFilters(this.filterStateService.filters());

    this.trackService.getTracks(apiFilters).subscribe({
      next: (response) => {
        if (response.success) {
          this.tracks.set(response.tracks);
        } else {
          this.error.set('Le serveur a répondu mais signale une erreur.');
        }
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Erreur API :', err);
        this.error.set('Impossible de contacter le serveur Flask.');
        this.loading.set(false);
      }
    });
  }

  // ── Conversion de format ──────────────────────────────────────────────────
  // ActiveFilters (Navbar) → TrackFilters (HTTP query string pour Flask)
  //
  // Flask attend :  ?search=trap&bpm_min=80&keys=Am,Gm&styles=Trap
  // Les tableaux sont joints en chaîne séparée par des virgules,
  // comme filters.js le faisait avec params.set('keys', keys.join(','))

  private toTrackFilters(f: ActiveFilters): TrackFilters {
    return {
      search:   f.search   || undefined,
      bpm_min:  f.bpmMin   ?? undefined,
      bpm_max:  f.bpmMax   ?? undefined,
      keys:     f.keys.length   ? f.keys.join(',')   : undefined,
      styles:   f.styles.length ? f.styles.join(',') : undefined,
      tags:     f.tags.length   ? f.tags.join(',')   : undefined,
    };
  }

  // Reçoit l'événement "play" émis par TrackCardComponent via @Output()
  onTrackPlay(track: Track): void {
    console.log('Page reçoit play :', track.title);
    // TODO : brancher sur un service player global
  }

}
