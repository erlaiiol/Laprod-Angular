import { Component, inject, OnInit, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { NavbarComponent } from './layout/navbar/navbar.component';
import { ToastComponent } from './components/ui/toast.component/toast.component';
import { FooterComponent } from './layout/footer/footer.component';
import { PlayerComponent } from './layout/player/player.component';
import { AuthService } from './services/auth.service';
import { NotificationService } from './services/notification.service';
import { UploadProgressToastComponent } from './components/ui/upload-progress-toast/upload-progress-toast.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, NavbarComponent, ToastComponent, FooterComponent, PlayerComponent, UploadProgressToastComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App implements OnInit {
  protected readonly title = signal('Laprod-Angular');

  private auth    = inject(AuthService);
  private notifSvc = inject(NotificationService);

  ngOnInit(): void {
    if (this.auth.isLoggedIn()) {
      // Vérifie que le user localStorage est toujours valide en DB.
      // Si le token est expiré ou l'user supprimé, l'interceptor appelle silentLogout().
      this.auth.me().subscribe();
      this.notifSvc.load().subscribe();
    }
  }
}
