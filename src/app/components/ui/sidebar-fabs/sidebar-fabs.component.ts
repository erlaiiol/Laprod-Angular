import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Capacitor } from '@capacitor/core';
import { AuthService } from '../../../services/auth.service';
import { UserflowService } from '../../../services/userflow.service';

@Component({
  selector: 'app-sidebar-fabs',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './sidebar-fabs.component.html',
  styleUrl: './sidebar-fabs.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SidebarFabsComponent implements OnInit, OnDestroy {
  readonly isNative    = Capacitor.isNativePlatform();
  readonly collapsed   = signal(false);
  readonly auth        = inject(AuthService);
  readonly userflowSvc = inject(UserflowService);

  private _timer: ReturnType<typeof setTimeout> | null = null;

  ngOnInit(): void {
    this._timer = setTimeout(() => this.collapsed.set(true), 15_000);
  }

  ngOnDestroy(): void {
    if (this._timer) clearTimeout(this._timer);
  }
}
