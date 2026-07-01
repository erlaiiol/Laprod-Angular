import type { Track, TrackDetail, ContractPrices } from '../../app/services/track.service';

// ── Prix de contrat par défaut (valeurs config.py) ────────────────────────────

export const CONTRACT_PRICES_DEFAULT: ContractPrices = {
  exclusive:       150,
  duration_3y:       5,
  duration_5y:      10,
  duration_10y:     15,
  lifetime:         50,
  territory_eu:      5,
  territory_world:  10,
  mechanical:       30,
  public_show:      40,
  arrangement:      10,
};

// ── Objets de référence Track ─────────────────────────────────────────────────
// Correspondent à la forme produite par serializers.track_card() côté Flask.

/** Track approuvée avec prix standard et tags vides. */
export const TRACK_STANDARD: Track = {
  id:            101,
  title:         'Test Beat Standard',
  composer_user: { username: 'beatmaker1' },
  stream_url:    '/api/stream/tracks/101/preview',
  full_stream_url: null,
  image_file:    'images/tracks/test.jpg',
  bpm:           120,
  key:           'C major',
  style:         'Trap',
  price_mp3:     9.99,
  tags:          [],
  similar_artists: [],
  is_approved:   true,
  playlist_count:       0,
  first_playlist_image: null,
};

/**
 * Track avec price_mp3=50€.
 * Couvre le bug fix public_show auto-inclus :
 *   base=50, mécanique=30 → subtotalWithMechanical=80 ≥ 74.99
 *   → publicShowAutoIncluded=true.
 */
export const TRACK_HIGH_PRICE: Track = {
  ...TRACK_STANDARD,
  id:        102,
  title:     'High Price Beat',
  price_mp3: 50,
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Construit un TrackDetail pour les tests de composants price/contract.
 * Remplace les factory functions `makeTrack(mp3)` dispersées dans les specs.
 *
 * @param price_mp3 - prix de base MP3 ; wav=×2, stems=×3
 */
export function makeTrackDetail(price_mp3: number): TrackDetail {
  return {
    ...TRACK_STANDARD,
    id:         1,
    price_mp3,
    price_wav:   price_mp3 * 2,
    price_stems: price_mp3 * 3,
    file_wav:    null,
    file_stems:  null,
    created_at:  null,
    composer_user: { id: 1, username: 'beatmaker', profile_image: null },
    toplines:    [],
    my_toplines: [],
    contract_prices:  CONTRACT_PRICES_DEFAULT,
    is_exclusive_sold: false,
  };
}
