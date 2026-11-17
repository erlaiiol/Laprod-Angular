import {
  CLIP_HEIGHT, CLIP_SAFE_ZONES, CLIP_WIDTH, creditLabel, handleLabel, isInSafeZone,
  maxTextWidth, overlayLayout,
} from './clip-overlay';

describe('clip-overlay — zones sûres', () => {
  const L = overlayLayout();

  it('le logo reste hors des zones masquées par Reels/TikTok/Shorts', () => {
    expect(isInSafeZone(L.logo)).toBe(true);
  });

  it('les textes (ancrés par leur base) restent au-dessus de la bande de légende', () => {
    const bottomLimit = CLIP_HEIGHT * (1 - CLIP_SAFE_ZONES.bottom);
    expect(L.handle.y).toBeLessThanOrEqual(bottomLimit);
    expect(L.credit.y).toBeLessThanOrEqual(bottomLimit);
    expect(L.handle.y - L.handle.size).toBeGreaterThanOrEqual(CLIP_HEIGHT * CLIP_SAFE_ZONES.top);
  });

  it('les textes ne débordent jamais sur la colonne de boutons', () => {
    expect(L.handle.x + maxTextWidth()).toBeLessThanOrEqual(CLIP_WIDTH * (1 - CLIP_SAFE_ZONES.right) + 1);
  });

  it('un rectangle en bas à droite est refusé', () => {
    expect(isInSafeZone({ x: CLIP_WIDTH - 100, y: CLIP_HEIGHT - 100, w: 80, h: 80 })).toBe(false);
  });

  it('libellés : @pseudo et crédit beatmaker', () => {
    const t = { username: 'nina', beatmaker: 'kbeats' };
    expect(handleLabel(t)).toBe('@nina');
    expect(creditLabel(t)).toBe('prod. @kbeats');
  });
});
