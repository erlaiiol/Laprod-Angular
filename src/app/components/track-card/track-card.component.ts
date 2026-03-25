// ─────────────────────────────────────────────────────────────────────────────
// COMPOSANT PRÉSENTATIONNEL TrackCard
// Rôle : afficher UN track. Ne sait pas d'où vient le track, ne fetch rien.
// Reçoit ses données de la page parente via @Input().
// Communique vers la page parente via @Output().
// ─────────────────────────────────────────────────────────────────────────────

import { Component, Input, Output, EventEmitter } from '@angular/core';
//                    │      │       └── classe qui encapsule un événement émis vers le parent
//                    │      └── @Output() : "je peux émettre cet événement vers ma page parente"
//                    └── @Input()  : "je reçois cette donnée de ma page parente"

import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';

import { Track, TrackService } from '../../services/track.service';
//        └── interface du track  (inchangée — même contrat de données)


@Component({
  selector: 'app-track-card',
  //         └── utilisé dans la page home : <app-track-card [track]="t">
  standalone: true,
  imports: [CommonModule, RouterModule],
  templateUrl: './track-card.component.html',
  styleUrls:   ['./track-card.component.scss']
})
export class TrackCardComponent {

  // ── @Input() : données reçues de la page parente ─────────────────────────

  @Input() track!: Track;
  // "!" = non-null assertion TypeScript : ce composant ne sera jamais
  // instancié sans recevoir un track (le *ngFor de la page le garantit).
  //
  // Dans la page home.html :  [track]="track"
  //   [ ]  = property binding : évalue l'expression à droite et l'assigne
  //          à la propriété @Input() du composant enfant.


  // ── @Output() : événements émis vers la page parente ─────────────────────

  @Output() play = new EventEmitter<Track>();
  // EventEmitter<T> : flux d'événements typé.
  // Quand on appelle this.play.emit(track), la page parente reçoit
  // l'événement via (play)="onTrackPlay($event)".
  //
  // $event = la valeur émise (ici, l'objet Track).


  // ── Injection de service (utilitaire uniquement, pas de fetch) ────────────

  constructor(private trackService: TrackService) {}
  // TrackService est injecté ici pour les utilitaires visuels (pas de fetch).
  // Ce composant ne doit JAMAIS appeler getTracks() ou getTrack() —
  // c'est le rôle des pages.

  getImageUrl(): string {
    return this.trackService.getStaticFileUrl(this.track.image_file);
  }

  // ── Couleurs dynamiques des tags ──────────────────────────────────────────
  // Délèguent à TrackService.darkenColor() — même logique que darken_color() (app.py).
  // On expose des méthodes publiques car le template Angular ne peut pas accéder
  // directement aux membres private d'un service injecté.

  tagBgColor(color: string): string {
    return this.trackService.darkenColor(color, 0.15);  // très foncé → fond
  }

  tagBorderColor(color: string): string {
    return this.trackService.darkenColor(color, 0.35);  // intermédiaire → bordure
  }

  // ── Gestionnaire d'événement interne ─────────────────────────────────────

  onPlay(): void {
    // Le clic sur l'image déclenche cette méthode.
    // Elle n'implémente pas le player — elle remonte l'info à la page parente
    // qui, elle, pourra décider quoi faire (ouvrir un player, logguer, etc.)
    this.play.emit(this.track);
  }

}
