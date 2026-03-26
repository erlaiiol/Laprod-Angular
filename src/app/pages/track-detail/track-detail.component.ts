import { Component, OnInit, signal, inject, ChangeDetectionStrategy, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { TrackService, TrackDetail, PublishedTopline } from '../../services/track.service';
import { PlayerService } from '../../services/player.service';
import { AuthService } from '../../services/auth.service';
import { ToplineRecorderComponent } from '../../components/topline-recorder/topline-recorder.component';

@Component({
  selector: 'app-track-detail',
  standalone: true,
  imports: [CommonModule, RouterModule, ToplineRecorderComponent],
  templateUrl: './track-detail.component.html',
  styleUrls: ['./track-detail.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class TrackDetailComponent implements OnInit {

  track   = signal<TrackDetail | null>(null);
  loading = signal(true);
  error   = signal<string | null>(null);
  showRecorder = signal(false);

  private route       = inject(ActivatedRoute);
  private trackSvc    = inject(TrackService);
  player              = inject(PlayerService);
  auth                = inject(AuthService);
  private cdr         = inject(ChangeDetectorRef);

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) { this.error.set('ID invalide'); this.loading.set(false); return; }

    this.trackSvc.getTrackDetail(id).subscribe({
      next: (res) => {
        if (res.success && res.data?.track) {
          this.track.set(res.data.track);
          // Auto-play preview
          this.player.play(res.data.track as any);
        } else {
          this.error.set('Track introuvable.');
        }
        this.loading.set(false);
        this.cdr.markForCheck();
      },
      error: () => {
        this.error.set('Impossible de contacter le serveur.');
        this.loading.set(false);
        this.cdr.markForCheck();
      }
    });
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(path);
  }

  getAudioUrl(path: string | null | undefined): string {
    if (!path) return '';
    return this.trackSvc.getStaticFileUrl(path);
  }

  tagBgColor(color: string): string     { return this.trackSvc.darkenColor(color, 0.15); }
  tagBorderColor(color: string): string { return this.trackSvc.darkenColor(color, 0.35); }

  formatDate(iso: string | null): string {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  playTopline(tl: PublishedTopline): void {
    // Build a minimal Track-like object for the player
    const t = this.track();
    if (!t) return;
    this.player.play({
      id:            tl.id,
      title:         `Topline par ${tl.artist_user.username}`,
      composer_user: tl.artist_user as any,
      audio_file:    tl.audio_file,
      image_file:    t.image_file,
      bpm:           t.bpm,
      key:           t.key,
      style:         t.style,
      price_mp3:     0,
      tags:          [],
      is_approved:   true,
    });
  }

  onToplinePublished(tl: PublishedTopline): void {
    const t = this.track();
    if (!t) return;
    this.track.set({ ...t, toplines: [...t.toplines, tl] });
    this.showRecorder.set(false);
    this.cdr.markForCheck();
  }

}
