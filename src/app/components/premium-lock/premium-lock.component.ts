import { ChangeDetectionStrategy, Component, Input } from '@angular/core';
import { RouterModule } from '@angular/router';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-premium-lock',
  standalone: true,
  imports: [RouterModule],
  templateUrl: './premium-lock.component.html',
  styleUrl: './premium-lock.component.scss',
})
export class PremiumLockComponent {
  @Input() requiredPlan: 'amateur' | 'pro' = 'amateur';

  get planLabel(): string {
    return this.requiredPlan === 'pro' ? 'Pro' : 'LaProd+';
  }
}
