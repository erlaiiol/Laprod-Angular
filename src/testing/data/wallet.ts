import type { WalletData, WalletInfo, WalletTransaction } from '../../app/services/wallet.service';

// ── Transactions ──────────────────────────────────────────────────────────────

/** Vente MP3 en attente de disponibilité (J+7). */
export const TXN_PENDING_BEAT_SALE: WalletTransaction = {
  id:                401,
  type:              'credit_beat_sale',
  amount:            8.99,   // 90% de 9.99€
  status:            'pending',
  description:       'Vente MP3 — Test Beat Standard',
  available_at:      '2026-01-08T00:00:00',
  created_at:        '2026-01-01T10:00:00',
  stripe_transfer_id: null,
};

/** Vente WAV disponible (date dans le passé). */
export const TXN_AVAILABLE_BEAT_SALE: WalletTransaction = {
  id:                402,
  type:              'credit_beat_sale',
  amount:            17.99,  // 90% de 19.99€
  status:            'available',
  description:       'Vente WAV — Test Beat Standard',
  available_at:      '2025-12-25T00:00:00',
  created_at:        '2025-12-18T14:00:00',
  stripe_transfer_id: null,
};

/** Acompte (30%) d'une commande mix/master — cleaning=35€ → dépôt=10.50€ × 90%. */
export const TXN_MIXMASTER_DEPOSIT: WalletTransaction = {
  id:                403,
  type:              'credit_mixmaster_deposit',
  amount:            9.45,   // 10.50 × 90%
  status:            'available',
  description:       'Acompte mixage — Mix Session 301',
  available_at:      '2026-01-08T00:00:00',
  created_at:        '2026-01-01T11:00:00',
  stripe_transfer_id: 'tr_deposit_test_123',
};

// ── Wallets ───────────────────────────────────────────────────────────────────

const WALLET_NO_STRIPE: WalletInfo = {
  balance_available:         0,
  balance_pending:           0,
  stripe_account_id:         null,
  stripe_onboarding_complete: false,
  stripe_account_status:     null,
};

const WALLET_WITH_STRIPE: WalletInfo = {
  balance_available:         75.50,
  balance_pending:           20.00,
  stripe_account_id:         'acct_test_stripe_ready',
  stripe_onboarding_complete: true,
  stripe_account_status:     'active',
};

/** Wallet vide sans Stripe Connect configuré. show_connect_alert=true. */
export const WALLET_EMPTY: WalletData = {
  wallet:              WALLET_NO_STRIPE,
  transactions:        [],
  show_connect_alert:  true,
};

/** Wallet avec solde disponible, Stripe configuré, deux transactions. */
export const WALLET_WITH_BALANCE: WalletData = {
  wallet:             WALLET_WITH_STRIPE,
  transactions:       [TXN_AVAILABLE_BEAT_SALE, TXN_PENDING_BEAT_SALE],
  show_connect_alert: false,
};
