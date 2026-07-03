import { Component, inject, OnInit, signal } from '@angular/core';
import { NavigationEnd, Router, RouterOutlet, RouterModule } from '@angular/router';
import { filter } from 'rxjs';
import { NavbarComponent } from './layout/navbar/navbar.component';
import { ToastComponent } from './components/ui/toast.component/toast.component';
import { FooterComponent } from './layout/footer/footer.component';
import { PlayerComponent } from './layout/player/player.component';
import { AuthService } from './services/auth.service';
import { NotificationService } from './services/notification.service';
import { UploadProgressToastComponent } from './components/ui/upload-progress-toast/upload-progress-toast.component';
import { ToplineProgressToastComponent } from './components/ui/topline-progress-toast/topline-progress-toast.component';
import { UserflowComponent } from './components/userflow/userflow.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterModule, NavbarComponent, ToastComponent, FooterComponent, PlayerComponent, UploadProgressToastComponent, ToplineProgressToastComponent, UserflowComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  protected readonly title = signal('Laprod-Angular');

  readonly auth    = inject(AuthService);
  private notifSvc = inject(NotificationService);
  private router   = inject(Router);

  ngOnInit(): void {
    if (this.auth.isLoggedIn()) {
      // Vérifie que le user localStorage est toujours valide en DB.
      // Si le token est expiré ou l'user supprimé, l'interceptor appelle silentLogout().
      this.auth.me().subscribe({
        next: (res) => {
          if (res.success && res.data?.user && !res.data.user.user_type_selected) {
            this.router.navigate(['/complete-profile']);
          }
        },
      });
      this.notifSvc.load().subscribe();
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
