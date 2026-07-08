import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class YoutubeTemplateService {
  readonly pending = signal<string | null>(null);

  set(template: string): void { this.pending.set(template); }
  clear(): void               { this.pending.set(null); }
}
