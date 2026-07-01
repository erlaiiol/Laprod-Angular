import type { CheckoutOptions } from '../../app/services/payment.service';

// ── Presets CheckoutOptions ───────────────────────────────────────────────────
// Correspondent aux presets affichés dans TrackContractConfigComponent.

/** Starter : streaming seul, pas de droits annexes. Prix = base MP3 uniquement. */
export const CHECKOUT_STARTER: CheckoutOptions = {
  is_exclusive:            false,
  is_lifetime:             false,
  duration_years:          undefined,
  territory:               'France',
  mechanical_reproduction: false,
  public_show:             false,
  arrangement:             false,
  total_price:             9.99,
};

/**
 * Standard : 5 ans, Europe, mécanique + diffusion publique.
 * total = base(9.99) + durée_5y(10) + territoire_eu(5) + mécanique(30) + diffusion(40) = 94.99
 */
export const CHECKOUT_STANDARD: CheckoutOptions = {
  is_exclusive:            false,
  is_lifetime:             false,
  duration_years:          5,
  territory:               'Europe',
  mechanical_reproduction: true,
  public_show:             true,
  arrangement:             false,
  total_price:             94.99,
};

/**
 * Intégral : lifetime, monde entier, mécanique + arrangement.
 * La diffusion publique est auto-incluse (subtotalWithMechanical ≥ 74.99).
 * total = base(9.99) + lifetime(50) + territoire_world(10) + mécanique(30) + arrangement(10) = 109.99
 */
export const CHECKOUT_INTEGRAL: CheckoutOptions = {
  is_exclusive:            false,
  is_lifetime:             true,
  duration_years:          undefined,
  territory:               'Monde entier',
  mechanical_reproduction: true,
  public_show:             false,   // auto-incluse côté composant, non envoyée explicitement
  arrangement:             true,
  total_price:             109.99,
};

/** Exclusif : tous les droits, lifetime, monde entier. */
export const CHECKOUT_EXCLUSIVE: CheckoutOptions = {
  is_exclusive:            true,
  is_lifetime:             true,
  duration_years:          undefined,
  territory:               'Monde entier',
  mechanical_reproduction: true,
  public_show:             true,
  arrangement:             true,
  total_price:             259.99,
};
