import type { MixEngineerPublic, MixOrderFull } from '../../app/services/mixmaster.service';

// ── Profils ingénieurs ────────────────────────────────────────────────────────

/** Ingénieur certifié, min_pct=10% — aucun service auto-forcé. */
export const ENGINEER_LOW_MIN: MixEngineerPublic = {
  id:                            201,
  username:                      'engineer_low_min',
  profile_image:                 null,
  mixmaster_bio:                 'Spécialiste mix rap/trap, 10 ans d\'expérience.',
  mixmaster_reference_price:     100,
  mixmaster_price_min:           10,
  price_max:                     180,  // cleaning(35)+effects(45)+mastering(20)+artistic(60)+stems(20) = 180%
  stripe_ready:                  true,
  is_certified_producer_arranger: false,
  is_certified_master_engineer:   true,
  subscription_plan:              'pro',
  sample_raw_url:                '/mixmaster/samples/raw_201.mp3',
  sample_processed_url:          '/mixmaster/samples/processed_201.mp3',
  active_orders:                 0,
  slots_available:               5,
};

/** Ingénieur avec plancher élevé, min_pct=30% — teste l'enforcement du prix minimum. */
export const ENGINEER_HIGH_MIN: MixEngineerPublic = {
  ...ENGINEER_LOW_MIN,
  id:                        202,
  username:                  'engineer_high_min',
  mixmaster_price_min:       30,
  active_orders:             2,
  slots_available:           3,
};

// ── Commandes mix/master ─────────────────────────────────────────────────────
// Correspondent à la forme produite par serializers.mix_order_full() côté Flask.
// Calculs de référence : total=35€, cleaning=35%, ref=100€

const ORDER_BRIEF_EMPTY = {
  brief_vocals:         null,
  brief_backing_vocals: null,
  brief_ambiance:       null,
  brief_bass:           null,
  brief_energy_style:   null,
  brief_references:     null,
  brief_instruments:    null,
  brief_percussion:     null,
  brief_effects:        null,
  brief_structure:      null,
};

/** Commande fraîche en attente d'acceptation. */
export const ORDER_AWAITING: MixOrderFull = {
  id:                    301,
  title:                 'Mix Session 301',
  artist_username:       'artist_user',
  artist_image:          null,
  engineer_username:     'engineer_low_min',
  engineer_image:        null,
  engineer_id:           201,
  status:                'awaiting_acceptance',
  stripe_payment_status: 'authorized',
  total_price:           35,
  deposit_amount:        10.50,
  remaining_amount:      24.50,
  engineer_revenue:      31.50,
  revision_count:        0,
  revision1_message:     null,
  revision2_message:     null,
  can_request_revision:  false,
  is_expired:            false,
  final_transfer_amount: 22.05,  // 24.50 × 90%
  services: { cleaning: true, effects: false, artistic: false, mastering: false },
  has_separated_stems:   false,
  artist_message:        null,
  ...ORDER_BRIEF_EMPTY,
  reference_file_url:              null,
  original_file_url:               '/static/stems/order_301.zip',
  processed_file_preview_url:      null,
  processed_file_preview_full_url: null,
  archive_file_tree:               [],
  created_at:   '2026-01-01T10:00:00',
  accepted_at:  null,
  deadline:     null,
  delivered_at: null,
  completed_at: null,
};

/** Commande en première révision — 10% de transfert révision déjà effectué. */
export const ORDER_REVISION1: MixOrderFull = {
  ...ORDER_AWAITING,
  id:                    302,
  title:                 'Mix Session 302',
  status:                'revision1',
  stripe_payment_status: 'partially_captured',
  revision_count:        1,
  revision1_message:     'Le kick manque de punch.',
  can_request_revision:  false,
  final_transfer_amount: 18.90,  // (24.50 - 3.50) × 90% = 21.00 × 90%
  accepted_at:           '2026-01-01T11:00:00',
  deadline:              '2026-01-08T11:00:00',
  delivered_at:          '2026-01-05T09:00:00',
};

/** Commande avec tous les services activés : total=180€. */
export const ORDER_ALL_SERVICES: MixOrderFull = {
  ...ORDER_AWAITING,
  id:                    303,
  title:                 'Mix Session 303 — Full Pack',
  status:                'accepted',
  stripe_payment_status: 'partially_captured',
  total_price:           180,
  deposit_amount:        54,
  remaining_amount:      126,
  engineer_revenue:      162,
  final_transfer_amount: 113.40,  // 126 × 90%
  services: { cleaning: true, effects: true, artistic: true, mastering: true },
  has_separated_stems:   true,
  accepted_at:           '2026-01-01T11:00:00',
  deadline:              '2026-01-08T11:00:00',
};

/** Commande complétée : paiement final capturé. */
export const ORDER_COMPLETED: MixOrderFull = {
  ...ORDER_AWAITING,
  id:                    304,
  title:                 'Mix Session 304',
  status:                'completed',
  stripe_payment_status: 'fully_captured',
  revision_count:        0,
  can_request_revision:  false,
  accepted_at:           '2026-01-01T11:00:00',
  deadline:              '2026-01-08T11:00:00',
  delivered_at:          '2026-01-06T09:00:00',
  completed_at:          '2026-01-07T14:00:00',
};
