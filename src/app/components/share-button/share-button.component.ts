import { Component, Input, inject } from '@angular/core';
import { ShareService } from '../../services/share.service';

@Component({
  selector: 'app-share-button',
  standalone: true,
  imports: [],
  templateUrl: './share-button.component.html',
  styleUrls: ['./share-button.component.scss'],
})
export class ShareButtonComponent {
  @Input() url!: string;
  @Input() title?: string;

  private shareSvc = inject(ShareService);

  share(event: MouseEvent): void {
    event.stopPropagation();
    this.shareSvc.share(this.url, this.title);
  }
}
