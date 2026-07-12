import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { Subscription, filter } from 'rxjs';
import { AuthService } from '../../services/auth.service';

// Routes qui affichent déjà leur propre rappel de soumission de preview —
// éviter d'y superposer le bandeau global.
const EXCLUDED_ROUTES = ['/submit-sample', '/dashboard/mix-engineer'];

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-mix-sample-banner',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './mix-sample-banner.component.html',
  styleUrl: './mix-sample-banner.component.scss',
})
export class MixSampleBannerComponent implements OnInit, OnDestroy {
  private readonly auth   = inject(AuthService);
  private readonly router = inject(Router);
  private sub?: Subscription;

  private readonly currentPath = signal(this.router.url.split('?')[0]);

  readonly visible = computed(() =>
    this.auth.mixSamplePending() && !EXCLUDED_ROUTES.includes(this.currentPath())
  );

  ngOnInit(): void {
    this.sub = this.router.events
      .pipe(filter((e): e is NavigationEnd => e instanceof NavigationEnd))
      .subscribe(e => this.currentPath.set(e.urlAfterRedirects.split('?')[0]));
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }
}
