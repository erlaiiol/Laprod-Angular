import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  selector: 'app-mixmaster-guide',
  standalone: true,
  templateUrl: './mixmaster-guide.component.html',
  styleUrl: './mixmaster-guide.component.scss',
})
export class MixmasterGuideComponent {}
