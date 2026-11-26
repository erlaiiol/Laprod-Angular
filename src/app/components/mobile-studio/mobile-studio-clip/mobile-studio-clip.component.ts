import {
  ChangeDetectionStrategy, Component, DestroyRef, EventEmitter, Input, OnInit, Output,
  computed, effect, inject, signal,
} from '@angular/core';
import { DOCUMENT } from '@angular/common';

import { ClipStudioContext, SocialClipService } from '../../../services/social-clip.service';
import { ClipShareParams, ClipShareService } from '../../../services/clip-share.service';
import {
  CLIP_END_CARD_SECONDS, CLIP_MAX_SECONDS, CLIP_MIN_SECONDS, SYNC_THRESHOLDS,
} from '../../../utils/clip-sync';
import { CLIP_HEIGHT, CLIP_SAFE_ZONES, CLIP_WIDTH, creditLabel, handleLabel, overlayLayout } from '../../../utils/clip-overlay';
import { formatTimer } from '../../../utils/waveform.utils';
import { environment } from '../../../../environments/environment';

/** Classe posée sur <html> pendant l'aperçu caméra : la WebView devient transparente. */
export const CLIP_CAMERA_CLASS = 'clip-camera-active';

/** Longueurs proposées en un tap (s) — toutes ≤ CLIP_MAX_SECONDS. */
const LENGTH_PRESETS = [15, 30, 45] as const;

/**
 * Écran du Mode Clip (docs/roadmap.md § Chantier 4) — vue seulement, toute la
 * logique est dans SocialClipService. L'aperçu caméra est une couche native
 * SOUS la WebView ; cet écran reste transparent au-dessus pendant le cadrage.
 */
@Component({
  selector: 'app-mobile-studio-clip',
  standalone: true,
  templateUrl: './mobile-studio-clip.component.html',
  styleUrls: ['./mobile-studio-clip.component.scss'],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [SocialClipService, ClipShareService],
})
export class MobileStudioClipComponent implements OnInit {
  @Input({ required: true }) ctx!: ClipStudioContext;
  @Output() closed = new EventEmitter<void>();

  readonly clip  = inject(SocialClipService);
  readonly share = inject(ClipShareService);
  private readonly doc = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);

  readonly maxSec    = CLIP_MAX_SECONDS;
  readonly minSec    = CLIP_MIN_SECONDS;
  readonly presets   = LENGTH_PRESETS;
  readonly showMire  = !environment.production;
  readonly mireThresholds = SYNC_THRESHOLDS;
  /** formatTimer attend des secondes entières (chrono et bornes du passage sont flottants). */
  readonly fmt = (s: number) => formatTimer(Math.floor(s));
  readonly permissionError = computed(() =>
    ['CAMERA_DENIED', 'PHOTOS_DENIED', 'MIC_DENIED'].includes(this.clip.errorCode() ?? ''));
  readonly endCardSec = CLIP_END_CARD_SECONDS;

  readonly saved = signal(false);

  /** Aperçu du filigrane, positionné en % du cadre 9:16 (mêmes constantes que l'export). */
  readonly wm = (() => {
    const L = overlayLayout();
    const pctX = (x: number) => `${(x / CLIP_WIDTH) * 100}%`;
    const pctY = (y: number) => `${(y / CLIP_HEIGHT) * 100}%`;
    return {
      logo:   { left: pctX(L.logo.x), top: pctY(L.logo.y), width: pctX(L.logo.w) },
      handle: { left: pctX(L.handle.x), top: pctY(L.handle.y), size: `${(L.handle.size / CLIP_WIDTH) * 100}cqw` },
      credit: { left: pctX(L.credit.x), top: pctY(L.credit.y), size: `${(L.credit.size / CLIP_WIDTH) * 100}cqw` },
      safeBottom: `${CLIP_SAFE_ZONES.bottom * 100}%`,
      safeRight:  `${CLIP_SAFE_ZONES.right * 100}%`,
    };
  })();

  readonly handleText = computed(() => handleLabel({ username: this.ctx.username, beatmaker: this.ctx.beatmaker }));
  readonly creditText = computed(() => creditLabel({ username: this.ctx.username, beatmaker: this.ctx.beatmaker }));

  readonly maxStart = computed(() => Math.max(0, this.ctx.maquetteSec - this.clip.segmentSec()));
  readonly hasHeadphones = computed(() => !!this.ctx.headphone && this.ctx.headphone !== 'none');
  readonly btUncalibrated = computed(() =>
    (this.ctx.headphone === 'bluetooth' || this.ctx.headphone === 'bluetooth-a2dp') && this.ctx.calibratedBtMs === null);

  /** La WebView n'est transparente que pendant l'aperçu caméra. */
  private readonly _transparency = effect(() => {
    const on = this.clip.previewOn() && this.clip.stage() !== 'ready';
    this.doc.documentElement.classList.toggle(CLIP_CAMERA_CLASS, on);
  });

  ngOnInit(): void {
    void this.clip.open(this.ctx);
    void this.share.loadShortcuts();
    this.destroyRef.onDestroy(() => {
      this.doc.documentElement.classList.remove(CLIP_CAMERA_CLASS);
      void this.clip.close();
    });
  }

  async close(): Promise<void> {
    this.doc.documentElement.classList.remove(CLIP_CAMERA_CLASS);
    await this.clip.close();
    this.closed.emit();
  }

  /** Bouton retour Android : annule le tournage en cours, sinon quitte le Mode Clip. */
  async onBack(): Promise<void> {
    const s = this.clip.stage();
    if (s === 'rendering') return;                         // montage : on laisse finir
    if (s === 'preparing' || s === 'countdown' || s === 'rolling') { await this.clip.abort(null); return; }
    await this.close();
  }

  onStartInput(ev: Event): void {
    const v = Number((ev.target as HTMLInputElement).value);
    this.clip.setSegment(v, this.clip.segmentSec());
  }

  setLength(sec: number): void {
    this.clip.setSegment(this.clip.segment().startSec, sec);
  }

  async save(): Promise<void> {
    if (await this.clip.saveToGallery()) {
      this.saved.set(true);
      this.share.track('saved', this.shareParams());
    }
  }

  /** Paramètres de partage du clip affiché. */
  shareParams(): ClipShareParams {
    return {
      path:        this.clip.resultUri()!,
      trackId:     this.ctx.trackId,
      clipUid:     this.clip.clipUid() ?? '',
      beatmaker:   this.ctx.beatmaker,
      mode:        this.clip.mode(),
      durationSec: this.clip.clipDurationSec() || this.clip.segmentSec(),
    };
  }

  async retake(): Promise<void> {
    this.saved.set(false);
    this.share.reset();
    await this.clip.retake();
  }
}
