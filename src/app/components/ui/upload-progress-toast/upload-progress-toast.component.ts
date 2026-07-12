import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { UploadStatusService } from '../../../services/upload-status.service';
import { ImgFallbackDirective } from '../../../directives/img-fallback.directive';

@Component({
  selector:        'app-upload-progress-toast',
  standalone:      true,
  imports:         [RouterLink, ImgFallbackDirective],
  templateUrl:     './upload-progress-toast.component.html',
  styleUrl:        './upload-progress-toast.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class UploadProgressToastComponent {

  protected uploadStatusSvc = inject(UploadStatusService);



}
