import { Component, effect, inject, OnInit, signal } from '@angular/core';
import { NavigationEnd, Router, RouterOutlet, RouterModule } from '@angular/router';
import { filter } from 'rxjs';
import { NavbarComponent } from './layout/navbar/navbar.component';
import { ToastComponent } from './components/ui/toast.component/toast.component';
import { FooterComponent } from './layout/footer/footer.component';
import { PlayerComponent } from './layout/player/player.component';
import { AuthService } from './services/auth.service';
import { PlayerService } from './services/player.service';
import { NotificationService } from './services/notification.service';
import { UploadProgressToastComponent } from './components/ui/upload-progress-toast/upload-progress-toast.component';
import { ToplineProgressToastComponent } from './components/ui/topline-progress-toast/topline-progress-toast.component';
import { UserflowComponent } from './components/userflow/userflow.component';
import { NativeShellService } from './services/native-shell.service';
import { YoutubeBubbleComponent } from './components/ui/youtube-bubble/youtube-bubble.component';
import { SidebarFabsComponent } from './components/ui/sidebar-fabs/sidebar-fabs.component';
import { MixSampleBannerComponent } from './components/mix-sample-banner/mix-sample-banner.component';
import { TourOverlayComponent } from './components/tour-overlay/tour-overlay.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterModule, NavbarComponent, ToastComponent, FooterComponent, PlayerComponent, UploadProgressToastComponent, ToplineProgressToastComponent, UserflowComponent, YoutubeBubbleComponent, SidebarFabsComponent, MixSampleBannerComponent, TourOverlayComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  protected readonly title = signal('Laprod-Angular');

  readonly auth    = inject(AuthService);
  readonly player  = inject(PlayerService);
  private notifSvc = inject(NotificationService);
  private router   = inject(Router);
  private shell    = inject(NativeShellService);

  constructor() {
    // Compteur de notifications : rechargé à CHAQUE transition anonyme → connecté
    // (login, register, OAuth…), pas seulement au premier rendu — sinon un visiteur
    // qui se connecte en cours de session garde un badge à 0 jusqu'au prochain
    // heartbeat 90s (AppRefreshService) ou jusqu'à cliquer sur la cloche. isLoggedIn()
    // est un booléen mémoïsé (computed) : cet effect ne se redéclenche que sur un
    // vrai flip false→true/true→false, pas sur chaque rafraîchissement de currentUser.
    let firstLoad = true;
    effect(() => {
      if (!this.auth.isLoggedIn()) return;
      if (firstLoad) {
        // Premier chargement : hors du chemin critique du premier rendu,
        // différé jusqu'à ce que le navigateur soit idle.
        firstLoad = false;
        const scheduleWhenIdle = 'requestIdleCallback' in window
          ? (cb: () => void) => (window as Window).requestIdleCallback(cb, { timeout: 5000 })
          : (cb: () => void) => setTimeout(cb, 2500); // vieux WebViews sans requestIdleCallback
        scheduleWhenIdle(() => this.notifSvc.load().subscribe({ error: () => {} }));
      } else {
        // Connexion survenue pendant cette session : badge à jour immédiatement.
        this.notifSvc.load().subscribe({ error: () => {} });
      }
    });
  }

  ngOnInit(): void {
    this.shell.init();

    if (this.auth.isLoggedIn()) {
      // Vérifie que le user localStorage est toujours valide en DB.
      // Si le token est expiré ou l'user supprimé, l'interceptor appelle silentLogout().
      // Reste éager : c'est le check de session qui gate complete-profile.
      this.auth.me().subscribe({
        next: (res) => {
          if (res.success && res.data?.user && !res.data.user.user_type_selected) {
            this.router.navigate(['/complete-profile']);
          }
        },
      });
    }

    // Vérification silencieuse à chaque navigation :
    // si le token expire dans moins de 2 minutes (ex: retour d'onglet en veille),
    // on le rafraîchit avant que la prochaine requête ne reçoive un 401.
    this.router.events.pipe(
      filter(e => e instanceof NavigationEnd),
    ).subscribe(() => {
      if (this.auth.isLoggedIn()) {
        this.auth.refreshIfExpiringSoon(2 * 60 * 1000).subscribe({ error: () => {} });
      }
    });
  }
}
