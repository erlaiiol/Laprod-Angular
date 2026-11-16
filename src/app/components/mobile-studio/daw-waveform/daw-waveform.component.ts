import {
  Component, Input, ViewChild, ElementRef, AfterViewInit, OnChanges, ChangeDetectionStrategy,
} from '@angular/core';

/**
 * Forme d'onde d'un clip de la timeline du studio, dessinée dans la couleur de
 * sa piste. La résolution interne est fixe : le CSS étire le canvas à la largeur
 * du clip (durée × zoom), sans redessin quand le zoom change.
 */
@Component({
  selector: 'app-daw-waveform',
  standalone: true,
  template: '<canvas #cv width="600" height="40" aria-hidden="true"></canvas>',
  styles: [':host, canvas { display: block; width: 100%; height: 100%; }'],
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DawWaveformComponent implements AfterViewInit, OnChanges {
  /** Points normalisés [0–1]. */
  @Input() points: number[] = [];
  @Input() color = '#ffffff';

  @ViewChild('cv') private canvasRef?: ElementRef<HTMLCanvasElement>;

  ngAfterViewInit(): void { this._draw(); }
  ngOnChanges(): void     { this._draw(); }

  private _draw(): void {
    const canvas = this.canvasRef?.nativeElement;
    const ctx    = canvas?.getContext?.('2d');
    if (!canvas || !ctx) return;
    const { width: W, height: H } = canvas;
    ctx.clearRect(0, 0, W, H);
    const n = this.points.length;
    if (!n) return;
    const barW = W / n;
    ctx.fillStyle = this.color;
    for (let i = 0; i < n; i++) {
      const barH = Math.max(2, this.points[i] * H * 0.9);
      ctx.fillRect(i * barW + 0.5, (H - barH) / 2, Math.max(1, barW - 1), barH);
    }
  }
}
