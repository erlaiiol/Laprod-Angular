import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { ToplineStatusService } from '../../../services/topline-status.service';
import { ImgFallbackDirective } from '../../../directives/img-fallback.directive';

@Component({
  selector:        'app-topline-progress-toast',
  standalone:      true,
  imports:         [RouterLink, ImgFallbackDirective],
  templateUrl:     './topline-progress-toast.component.html',
  styleUrl:        './topline-progress-toast.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToplineProgressToastComponent {

  protected toplineStatusSvc = inject(ToplineStatusService);

  protected isProcessing = computed(() => {
    const s = this.toplineStatusSvc.status();
    return s === 'uploading' || s === 'queued' || s === 'started' || s === 'finalizing';
  });
}
