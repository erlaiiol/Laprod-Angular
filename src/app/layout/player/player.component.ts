import {
  Component,
  OnDestroy,
  AfterViewInit,
  ViewChild,
  ElementRef,
  inject,
  effect,
  ChangeDetectionStrategy
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import WaveSurfer from 'wavesurfer.js';
import { PlayerService } from '../../services/player.service';
import { TrackService } from '../../services/track.service';

@Component({
  selector: 'app-player',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './player.component.html',
  styleUrls: ['./player.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class PlayerComponent implements AfterViewInit, OnDestroy {

  // The waveform container is ALWAYS in the DOM (shown/hidden via CSS).
  // This guarantees @ViewChild resolves at ngAfterViewInit time.
  @ViewChild('waveformContainer') waveformContainer!: ElementRef<HTMLDivElement>;

  player   = inject(PlayerService);
  trackSvc = inject(TrackService);

  private wavesurfer: WaveSurfer | null = null;

  constructor() {
    // Fires every time currentTrack changes.
    // At this point wavesurfer is already initialized (ngAfterViewInit ran first).
    effect(() => {
      const track = this.player.currentTrack();
      if (!track || !this.wavesurfer) return;
      const url = this.player.buildAudioUrl(track);
      if (url) this.wavesurfer.load(url);
    });
  }

  ngAfterViewInit(): void {
    this.wavesurfer = WaveSurfer.create({
      container:     this.waveformContainer.nativeElement,
      waveColor:     '#4a5568',
      progressColor: '#a78bfa',
      cursorColor:   '#ffffff',
      height:        40,
      barWidth:      2,
      barGap:        1,
      barRadius:     2,
      // Share the HTMLAudioElement — WaveSurfer controls src, PlayerService controls play/pause/seek
      media: this.player.audioEl,
    });

    this.wavesurfer.on('ready', () => {
      if (this.player.playOnReady) {
        this.player.playOnReady = false;
        this.player.audioEl.play().catch(err =>
          console.warn('PlayerComponent: autoplay blocked', err)
        );
      }
    });

    // User clicked/dragged the waveform → sync PlayerService seek position
    this.wavesurfer.on('interaction', (newTime) => {
      this.player.seek(newTime);
    });
  }

  // ── Template helpers ─────────────────────────────────────────────────────

  getImageUrl(): string {
    const track = this.player.currentTrack();
    if (!track?.image_file) return 'assets/placeholder-track.png';
    return this.trackSvc.getStaticFileUrl(track.image_file);
  }

  formatTime(seconds: number): string {
    if (!seconds || isNaN(seconds) || !isFinite(seconds)) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  onVolumeChange(event: Event): void {
    const val = parseFloat((event.target as HTMLInputElement).value);
    this.player.setVolume(val);
  }

  ngOnDestroy(): void {
    this.wavesurfer?.destroy();
    this.wavesurfer = null;
  }

}
