import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { UserService, UserProfile, UserTrack } from '../../services/user.service';
import { AuthService } from '../../services/auth.service';
import { PlayerService } from '../../services/player.service';
import { ToastService } from '../../services/toast.service';
import { environment } from '../../../environments/environment';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, RouterLink],
  templateUrl: './profile.component.html',
  styleUrl:    './profile.component.scss',
})
export class ProfileComponent implements OnInit {

  staticBase = `${environment.apiUrl.replace('/api', '')}/static/`;

  loading = signal(true);
  error   = signal<string | null>(null);
  profile = signal<UserProfile | null>(null);

  constructor(
    private route:   ActivatedRoute,
    private router:  Router,
    private userSvc: UserService,
    readonly auth:   AuthService,
    private player:  PlayerService,
    private toast:   ToastService,
  ) {}

  ngOnInit(): void {
    this.route.paramMap.subscribe(params => {
      const username = params.get('username') ?? '';
      this.loadProfile(username);
    });
    
  }

  loadProfile(username: string): void {
    this.loading.set(true);
    this.error.set(null);
    this.userSvc.getProfile(username).subscribe({
      next: res => {
        this.loading.set(false);
        if (res.success && res.data) {
          this.profile.set(res.data.user);
        } else {
          this.error.set(res.feedback?.message ?? 'Profil introuvable.');
        }
      },
      error: err => {
        this.loading.set(false);
        if (!err?.error?.feedback) {
          this.toast.showToast({ level: 'error', message: 'Impossible de charger le profil.' });
        }
        this.error.set(err?.error?.feedback?.message ?? 'Impossible de charger le profil.');
      },
    });
  }

  isOwnProfile(): boolean {
    const currentUser = this.auth.currentUser();
    const profile     = this.profile();
    return !!(currentUser && profile && currentUser.id === profile.id);
  }

  playTrack(track: UserTrack): void {
    this.player.play({
      id:         track.id,
      title:      track.title,
      stream_url: track.stream_url,
      image_file: track.image_file,
      price_mp3:  track.price_mp3,
      composer_user: { username: this.profile()?.username ?? '' },
    } as any);
  }

  imgUrl(path: string): string {
    if (!path) return '/assets/placeholder-track.png';
    if (path.startsWith('http')) return path;
    return this.staticBase + path;
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleDateString('fr-FR', { month: 'long', year: 'numeric' });
  }
}
