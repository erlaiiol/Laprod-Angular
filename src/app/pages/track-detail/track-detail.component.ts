import {
  Component, OnInit, OnDestroy, signal, inject,
  ChangeDetectionStrategy, ChangeDetectorRef, effect
} from '@angular/core';
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
export class TrackDetailComponent implements OnInit, OnDestroy {

  track        = signal<TrackDetail | null>(null);
  loading      = signal(true);
  error        = signal<string | null>(null);
  showRecorder = signal(false);

  private route    = inject(ActivatedRoute);
  private trackSvc = inject(TrackService);
  player           = inject(PlayerService);
  auth             = inject(AuthService);
  private cdr      = inject(ChangeDetectorRef);

  constructor() {
    // Open the recorder whenever the player requests it
    effect(() => {
      if (this.player.recRequested() > 0 && this.track()) {
        this.showRecorder.set(true);
        this.cdr.markForCheck();
      }
    });
  }

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) { this.error.set('ID invalide'); this.loading.set(false); return; }

    this.trackSvc.getTrackDetail(id).subscribe({
      next: (res) => {
        if (res.success && res.data?.track) {
          const t = res.data.track;
          this.track.set(t);
          // Register this page's track as the viewing context (no auto-play)
          this.player.viewingTrack.set(t as any);
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

  ngOnDestroy(): void {
    this.player.viewingTrack.set(null);
    this.player.recRequested.set(0);
  }

  getImageUrl(path: string | null | undefined): string {
    if (!path) return 'assets/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(path);
  }

  tagBgColor(color: string): string     { return this.trackSvc.darkenColor(color, 0.15); }
  tagBorderColor(color: string): string { return this.trackSvc.darkenColor(color, 0.35); }

  formatDate(iso: string | null): string {
    if (!iso) return '';
    return new Date(iso).toLocaleDateString('fr-FR', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  isThisTrackPlaying(): boolean {
    const t = this.track();
    return !!t && this.player.currentTrack()?.id === t.id && this.player.isPlaying();
  }

  playThisTrack(): void {
    const t = this.track();
    if (!t) return;
    if (this.player.currentTrack()?.id === t.id) {
      this.player.togglePlay();
    } else {
      this.player.play(t as any);
    }
  }

  playTopline(tl: PublishedTopline): void {
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
