/**
 * Mode Clip — filigrane visuel (docs/roadmap.md § 4.1.6).
 *
 * Le filigrane et la carte de fin sont dessinés ICI, une seule fois, en PNG
 * 1080×1920 transparents ; le natif (iOS AVVideoCompositionCoreAnimationTool,
 * Android Media3 OverlayEffect) ne fait que les superposer. Une seule source
 * pour les deux plateformes, et pour l'aperçu à l'écran (mêmes zones sûres).
 *
 * Zones sûres : Reels/TikTok/Shorts posent leur légende et leurs boutons sur
 * le bas (~20 %) et la bande droite (~15 %) de la vidéo — un filigrane placé
 * là serait masqué une fois posté (piège § 4.6.6). Ne modifier ces marges
 * qu'ici : l'aperçu de l'écran Clip et l'export les lisent toutes deux.
 */

export const CLIP_WIDTH  = 1080;
export const CLIP_HEIGHT = 1920;

/** Fractions de la hauteur/largeur interdites au filigrane. */
export const CLIP_SAFE_ZONES = {
  top:    0.10,   // onglets « Abonnements / Pour toi », titre « Reels »
  bottom: 0.20,   // légende, son, barre de progression
  right:  0.15,   // colonne de boutons (j'aime, commentaires, partage)
  left:   0.04,
} as const;

export interface Rect { x: number; y: number; w: number; h: number }

export interface OverlayLayout {
  logo:   Rect;
  handle: { x: number; y: number; size: number };
  credit: { x: number; y: number; size: number };
}

/**
 * Bloc filigrane ancré en bas à gauche de la zone sûre : juste au-dessus de la
 * bande de légende, à l'écart de la colonne de boutons.
 */
export function overlayLayout(width = CLIP_WIDTH, height = CLIP_HEIGHT): OverlayLayout {
  const left   = Math.ceil(width * CLIP_SAFE_ZONES.left);    // ceil : jamais 1 px dans la marge
  const bottom = Math.floor(height * (1 - CLIP_SAFE_ZONES.bottom));
  const logoSz = Math.round(width * 0.13);
  const handleSize = Math.round(width * 0.042);
  const creditSize = Math.round(width * 0.034);
  const gap = Math.round(width * 0.015);

  const creditY = bottom - gap;
  const handleY = creditY - creditSize - gap;
  const logoY   = handleY - handleSize - gap - logoSz;
  return {
    logo:   { x: left, y: logoY, w: logoSz, h: logoSz },
    handle: { x: left, y: handleY, size: handleSize },
    credit: { x: left, y: creditY, size: creditSize },
  };
}

/** true si le rectangle reste entièrement hors des zones réservées aux plateformes. */
export function isInSafeZone(r: Rect, width = CLIP_WIDTH, height = CLIP_HEIGHT): boolean {
  return r.x >= width * CLIP_SAFE_ZONES.left
      && r.y >= height * CLIP_SAFE_ZONES.top
      && r.x + r.w <= width * (1 - CLIP_SAFE_ZONES.right)
      && r.y + r.h <= height * (1 - CLIP_SAFE_ZONES.bottom);
}

export interface OverlayText {
  /** Pseudo de l'auteur, sans @. */
  username:    string;
  /** Pseudo du beatmaker, sans @. */
  beatmaker:   string;
}

export function handleLabel(t: OverlayText): string { return `@${t.username}`; }
export function creditLabel(t: OverlayText): string { return `prod. @${t.beatmaker}`; }

/** Largeur max des textes : jamais dans la colonne de boutons. */
export function maxTextWidth(width = CLIP_WIDTH): number {
  return Math.floor(width * (1 - CLIP_SAFE_ZONES.right - CLIP_SAFE_ZONES.left));
}

// ── Rendu canvas (navigateur / WebView uniquement) ───────────────────────────

const BRAND_RED  = '#A51929';   // = v.$primary (constante de marque, hors SCSS)
const FONT_STACK = '-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload  = () => resolve(img);
    img.onerror = () => reject(new Error('logo'));
    img.src = src;
  });
}

function canvasToPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) =>
    canvas.toBlob(b => (b ? resolve(b) : reject(new Error('toBlob'))), 'image/png'));
}

/** Texte tronqué à la largeur max, avec ombre portée pour rester lisible sur toute image. */
function drawShadowText(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, size: number, weight: number, maxW: number): void {
  ctx.font = `${weight} ${size}px ${FONT_STACK}`;
  let t = text;
  while (t.length > 2 && ctx.measureText(t).width > maxW) t = t.slice(0, -2) + '…';
  ctx.shadowColor   = 'rgba(0,0,0,0.65)';
  ctx.shadowBlur    = size * 0.35;
  ctx.shadowOffsetY = size * 0.06;
  ctx.fillStyle     = '#FFFFFF';
  ctx.textBaseline  = 'bottom';
  ctx.fillText(t, x, y);
  ctx.shadowColor = 'transparent';
}

/** Filigrane superposé à toute la vidéo (PNG transparent 1080×1920). */
export async function renderOverlayPng(t: OverlayText, logoSrc = 'assets/logo.png'): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = CLIP_WIDTH; canvas.height = CLIP_HEIGHT;
  const ctx = canvas.getContext('2d')!;
  const L = overlayLayout();

  try {
    const logo = await loadImage(logoSrc);
    ctx.globalAlpha = 0.92;
    ctx.drawImage(logo, L.logo.x, L.logo.y, L.logo.w, L.logo.h);
    ctx.globalAlpha = 1;
  } catch { /* logo indisponible : les textes suffisent à attribuer le clip */ }

  const maxW = maxTextWidth();
  drawShadowText(ctx, handleLabel(t), L.handle.x, L.handle.y, L.handle.size, 700, maxW);
  drawShadowText(ctx, creditLabel(t), L.credit.x, L.credit.y, L.credit.size, 500, maxW);
  return canvasToPng(canvas);
}

/** Carte de fin plein écran (PNG opaque 1080×1920). */
export async function renderEndCardPng(t: OverlayText, logoSrc = 'assets/logo.png'): Promise<Blob> {
  const canvas = document.createElement('canvas');
  canvas.width = CLIP_WIDTH; canvas.height = CLIP_HEIGHT;
  const ctx = canvas.getContext('2d')!;

  const grad = ctx.createLinearGradient(0, 0, 0, CLIP_HEIGHT);
  grad.addColorStop(0, '#120406');
  grad.addColorStop(1, BRAND_RED);
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, CLIP_WIDTH, CLIP_HEIGHT);

  const logoSz = Math.round(CLIP_WIDTH * 0.42);
  try {
    const logo = await loadImage(logoSrc);
    ctx.drawImage(logo, (CLIP_WIDTH - logoSz) / 2, CLIP_HEIGHT * 0.28, logoSz, logoSz);
  } catch { /* fond + textes seuls */ }

  ctx.textAlign = 'center';
  ctx.fillStyle = '#FFFFFF';
  ctx.textBaseline = 'alphabetic';
  ctx.font = `800 ${Math.round(CLIP_WIDTH * 0.062)}px ${FONT_STACK}`;
  ctx.fillText('Fais ta maquette sur LaProd', CLIP_WIDTH / 2, CLIP_HEIGHT * 0.62);
  ctx.font = `500 ${Math.round(CLIP_WIDTH * 0.04)}px ${FONT_STACK}`;
  ctx.fillText(`${handleLabel(t)} · ${creditLabel(t)}`, CLIP_WIDTH / 2, CLIP_HEIGHT * 0.67, CLIP_WIDTH * 0.9);
  return canvasToPng(canvas);
}
