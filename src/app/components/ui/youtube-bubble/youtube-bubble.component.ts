import { Component, inject, signal } from '@angular/core';
import { YoutubeTemplateService } from '../../../services/youtube-template.service';

@Component({
  selector: 'app-youtube-bubble',
  standalone: true,
  imports: [],
  templateUrl: './youtube-bubble.component.html',
  styleUrl:    './youtube-bubble.component.scss',
})
export class YoutubeBubbleComponent {
  readonly ytSvc   = inject(YoutubeTemplateService);
  readonly open    = signal(false);
  readonly copied  = signal(false);

  toggle(): void { this.open.set(!this.open()); }

  copy(): void {
    const t = this.ytSvc.pending();
    if (!t) return;
    navigator.clipboard.writeText(t).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2500);
    });
  }

  dismiss(): void {
    this.open.set(false);
    this.ytSvc.clear();
  }
}
