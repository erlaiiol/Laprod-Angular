import { Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { NavbarComponent } from './layout/navbar/navbar.component';
import { ToastComponent } from './components/ui/toast.component/toast.component';
import { FooterComponent } from './layout/footer/footer.component';
import { PlayerComponent } from './layout/player/player.component';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, NavbarComponent, ToastComponent, FooterComponent, PlayerComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss'
})
export class App {
  protected readonly title = signal('Laprod-Angular');
}
